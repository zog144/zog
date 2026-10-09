"""Explicit bounded probe; separate from read-only inspection and identity APIs."""
import os
import secrets
from .state_contract import StateError, require
from .state_inspect import inspect_live, metadata


def _probe_directory(fd):
    """Internal primitive for disposable tests; caller owns a verified directory.

Failure propagates, including cleanup/directory-fsync failure. Success is not a
lasting health guarantee. At most 4096 data bytes and two transient names used.
"""
    name = '.probe-' + secrets.token_hex(16)
    renamed = name + '.done'
    current = None
    child = None
    try:
        child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        current = name
        data = memoryview(b'ZOG STATE probe\n' + b'\0' * (4096 - 16))
        while data:
            n = os.write(child, data)
            require(n > 0, 'probe-short-write', 'write made no progress')
            data = data[n:]
        os.fsync(child)
        os.close(child); child = None
        os.rename(name, renamed, src_dir_fd=fd, dst_dir_fd=fd)
        current = renamed
        os.fsync(fd)
        os.unlink(current, dir_fd=fd); current = None
        os.fsync(fd)
    finally:
        if child is not None: os.close(child)
        if current is not None:
            # Best-effort cleanup does not turn a failed operation into success.
            try:
                os.unlink(current, dir_fd=fd)
                os.fsync(fd)
            except OSError: pass


def _probe_live():
    require(os.geteuid() == 970 and os.getegid() == 970 and set(os.getgroups()) <= {970, 972, 973},
            'probe-account', 'run explicitly as host-discover, not root')
    with inspect_live() as c:
        home = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=c.fd)
        try:
            metadata(home, 970, 970, 0o700)
            fd = os.open('health', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
            try:
                metadata(fd, 970, 970, 0o700)
                require(os.fstat(fd).st_dev == os.fstat(c.fd).st_dev, 'probe-device', 'health directory on another device')
                c.recheck()
                _probe_directory(fd)
                c.recheck()
            finally: os.close(fd)
        finally: os.close(home)
    return {'status': 'probe-passed', 'control_authorized': False, 'identity': 'not-read'}


def probe_live():
    try:
        return _probe_live()
    except OSError as exc:
        raise StateError('storage-probe-failed', str(exc)) from exc
