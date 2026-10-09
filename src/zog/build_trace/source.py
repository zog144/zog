"""Read only the schema-1 image-build evidence tree, never workspaces or recipes."""
import json
import os
from pathlib import Path, PurePosixPath
import stat
from dataclasses import dataclass

from .model import TraceError

MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_RECORDS = 10000


@dataclass(frozen=True)
class InspectionLimits:
    source_bytes: int = MAX_TOTAL
    list_source_bytes: int = 16 * 1024 * 1024
    file_bytes: int = MAX_FILE
    records: int = MAX_RECORDS
    scan_builds: int = 100

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise TraceError('invalid-query', 'Inspection limits must be positive integers.')


def component(value):
    if not isinstance(value, str) or not value or value in ('.', '..') or len(value) > 255 or any(c in value for c in '/\\\x00'):
        raise TraceError('invalid-query', 'Invalid evidence identity.')
    return value


class Snapshot:
    """No-follow dirfd reads; detect replacement during a request without writer locks.

    The configured root is trusted. A request is a best-effort coherent observation,
    not a transactional snapshot with image-build or the controller.
    """
    def __init__(self, root, *, limits=None, listing=False, json_loader=None):
        self.limits = limits or InspectionLimits()
        self.json_loader = json_loader
        self.byte_limit = self.limits.list_source_bytes if listing else self.limits.source_bytes
        self.root = Path(root).resolve()
        self.observed = {}
        self.total = 0

    def metrics(self):
        return dict(source_bytes=self.total, visited_records=len(self.observed),
                    source_byte_limit=self.byte_limit, file_byte_limit=self.limits.file_bytes,
                    record_limit=self.limits.records)

    def exhausted(self, budget, path, required=None):
        raise TraceError('source-too-large', 'Inspection resource budget exhausted.',
                         details=dict(self.metrics(), budget=budget, record=path,
                                      required_bytes=required))

    def _open(self, relative, directory=False):
        parts = PurePosixPath(relative).parts
        if not parts or PurePosixPath(relative).is_absolute():
            raise TraceError('invalid-record', 'Evidence path is not relative.')
        for part in parts:
            component(part)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if directory or index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                new = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = new
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _signature(self, fd):
        s = os.fstat(fd)
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    def _read(self, path, directory=False):
        try:
            fd = self._open(path, directory)
        except FileNotFoundError:
            return None, None
        except OSError:
            raise TraceError('source-unavailable', 'Evidence cannot be opened safely.') from None
        try:
            before = self._signature(fd)
            if directory:
                value = sorted(os.listdir(fd))
                if len(value) > self.limits.records:
                    self.exhausted('directory-entries', path)
            else:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise TraceError('invalid-record', 'Evidence must be a regular file.')
                if before[2] > self.limits.file_bytes:
                    self.exhausted('file-bytes', path, before[2])
                if self.total + before[2] > self.byte_limit:
                    self.exhausted('source-bytes', path, before[2])
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    value = stream.read(min(self.limits.file_bytes, self.byte_limit - self.total) + 1)
                if len(value) > self.limits.file_bytes or self.total + len(value) > self.byte_limit:
                    self.exhausted('source-bytes', path, len(value))
            if before != self._signature(fd):
                raise TraceError('concurrent-change', 'Evidence changed during inspection; repeat the read.')
            return value, before
        finally:
            os.close(fd)

    def read(self, path, *, directory=False):
        key = (path, directory)
        if key in self.observed:
            return self.observed[key][0]
        if len(self.observed) >= self.limits.records:
            self.exhausted('records', path)
        value, signature = self._read(path, directory)
        if value is not None and not directory:
            self.total += len(value)
            try:
                value = self.json_loader(value) if self.json_loader else json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(value, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise TraceError('invalid-record', 'Evidence is not a JSON object.') from None
        self.observed[key] = (value, signature)
        return value

    def names(self, path):
        return self.read(path, directory=True) or []

    def finish(self):
        for (path, directory), (_, before) in self.observed.items():
            try:
                fd = self._open(path, directory)
            except FileNotFoundError:
                after = None
            except OSError:
                raise TraceError('concurrent-change', 'Evidence access changed during inspection.') from None
            else:
                try:
                    after = self._signature(fd)
                finally:
                    os.close(fd)
            if after != before:
                raise TraceError('concurrent-change', 'Evidence changed during inspection; repeat the read.')


class BoxControlReader:
    """Only read-only methods are exposed. No refresh, recovery or mutation calls."""
    def __init__(self, control):
        self.control = control

    def inspect(self, job_id):
        from zog.box_control.errors import RuntimeOperationError
        try:
            return self.control.inspect_build_job(job_id)
        except RuntimeOperationError as error:
            if str(error) == 'unknown build identity: job:' + job_id:
                return None
            raise

    def logs(self, job_id, *, cursor=None, limit=50):
        return self.control.build_job_logs(job_id, cursor=cursor, limit=limit)
