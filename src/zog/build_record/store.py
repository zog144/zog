"""Local immutable record store. POSIX hard-link publication prevents clobbering."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .graph import inspect
from .model import (MAX_BUNDLE_BYTES, MAX_RECORD_BYTES, MAX_RECORDS, RecordError,
                    canonical, digest, loads, record_id, references, require)


class Store:
    """Trusted owner-controlled directory; not a sandbox for hostile local writers."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def put(self, record: dict) -> str:
        identity = record_id(record)
        raw = canonical(record)
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / (identity[7:] + ".json")
        fd, temporary = tempfile.mkstemp(prefix=".prepared-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                require(self.get(identity) == record, "existing immutable record conflicts")
            # Includes idempotent retry: confirm directory durability again.
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            os.unlink(temporary)
        return identity

    def get(self, identity: str) -> dict:
        digest(identity)
        path = self.directory / (identity[7:] + ".json")
        try:
            require(not path.is_symlink(), "record symlinks are not supported")
            with path.open("rb") as stream:
                record = loads(stream.read(MAX_RECORD_BYTES + 1))
        except FileNotFoundError:
            raise RecordError("record unavailable: " + identity) from None
        require(record_id(record) == identity, "stored record digest mismatch")
        return record

    def bundle(self, roots: list[str]) -> dict:
        records, stack, total = {}, list(roots), 0
        while stack:
            identity = stack.pop()
            if identity in records:
                continue
            require(len(records) < MAX_RECORDS, "record count limit exceeded")
            record = self.get(identity)
            total += len(canonical(record)) + len(identity) + 4
            require(total <= MAX_BUNDLE_BYTES, "bundle byte limit exceeded")
            records[identity] = record
            stack.extend(target for target, _ in references(record))
        bundle = {"schema_version": 1, "roots": roots, "records": records}
        inspect(bundle)
        return bundle
