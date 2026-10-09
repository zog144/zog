"""Anchored, durable, no-replacement primitives for installer-owned metadata."""
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import os
import stat
from .state_contract import StateError, canonical, decode, require
from .state_inspect import metadata


def raw(fd, name, uid=0, gid=0, mode=0o600, links=(1,)):
    require('/' not in name and name not in ('', '.', '..'), 'unsafe-path', name)
    try: f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError: return None
    try:
        s = os.fstat(f)
        require(stat.S_ISREG(s.st_mode) and s.st_nlink in links and
                (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) == (uid, gid, mode),
                'unsafe-record', name)
        data = bytearray()
        while len(data) <= 65536:
            part = os.read(f, min(8192, 65537 - len(data)))
            if not part: break
            data.extend(part)
        require(len(data) <= 65536, 'record-size', name)
        return bytes(data)
    finally: os.close(f)


def sync_file(fd, name):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try: os.fsync(f)
    finally: os.close(f)


def publish(fd, name, data, mode=0o600, *, uid=0, gid=0, checkpoint=lambda _: None):
    """Same bytes resume; conflicting/partial bytes require reconciliation.

A fixed temporary name is safe only under the installer's durable lock. The
recognized transient two-link publication is reconciled before success.
"""
    require(type(data) is bytes and len(data) <= 65536, 'record-size', name)
    pending = '.pending.' + name
    existing = raw(fd, name, uid, gid, mode, (1, 2))
    staged = raw(fd, pending, uid, gid, mode, (1, 2))
    if existing is not None:
        require(existing == data, 'record-conflict', name)
        s = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if staged is not None:
            t = os.stat(pending, dir_fd=fd, follow_symlinks=False)
            require(staged == data and (s.st_dev, s.st_ino) == (t.st_dev, t.st_ino) and s.st_nlink == 2,
                    'publication-conflict', name)
            os.unlink(pending, dir_fd=fd)
        else: require(s.st_nlink == 1, 'publication-conflict', name)
        sync_file(fd, name); os.fsync(fd)
        return
    if staged is None:
        f = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
        try:
            os.fchmod(f, mode)
            view = memoryview(data)
            while view:
                n = os.write(f, view)
                require(n > 0, 'short-write', name)
                view = view[n:]
            os.fsync(f)
        finally: os.close(f)
    else:
        require(staged == data and os.stat(pending, dir_fd=fd, follow_symlinks=False).st_nlink == 1,
                'publication-conflict', name)
        sync_file(fd, pending)
    os.fsync(fd); checkpoint('staged:' + name)
    os.link(pending, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    checkpoint('linked:' + name)
    os.unlink(pending, dir_fd=fd); os.fsync(fd)
    checkpoint('published:' + name)


def rename_new(fd, old, new):
    libc = ctypes.CDLL(None, use_errno=True)
    require(hasattr(libc, 'renameat2'), 'rename-unavailable', 'Linux renameat2 required')
    call = libc.renameat2
    call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    call.restype = ctypes.c_int
    if call(fd, os.fsencode(old), fd, os.fsencode(new), 1):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), new)


def ensure_directory(fd, name, uid, gid, mode, checkpoint=lambda _: None):
    """Never repair existing directories; resume only our empty staging name."""
    require('/' not in name and name not in ('', '.', '..'), 'unsafe-path', name)
    pending = '.pending-dir.' + name
    try: result = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    except FileNotFoundError:
        try: os.mkdir(pending, 0o700, dir_fd=fd)
        except FileExistsError: pass
        p = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            s = os.fstat(p)
            require(s.st_uid in (0, uid) and s.st_gid in (0, gid) and stat.S_IMODE(s.st_mode) in (0o700, mode)
                    and not os.listdir(p), 'directory-conflict', pending)
            os.fchown(p, uid, gid); os.fchmod(p, mode); os.fsync(p)
            checkpoint('directory-staged:' + name)
            rename_new(fd, pending, name); os.fsync(fd)
        finally: os.close(p)
        result = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        metadata(result, uid, gid, mode)
        require(os.fstat(result).st_dev == os.fstat(fd).st_dev, 'nested-mount', name)
        require(pending not in os.listdir(fd), 'directory-conflict', pending)
        os.fsync(result); os.fsync(fd)
        return result
    except BaseException:
        os.close(result)
        raise


@contextmanager
def lock(fd, name='.host-install.lock'):
    handle = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
    try:
        metadata(handle, 0, 0, 0o600, False)
        fcntl.flock(handle, fcntl.LOCK_EX)
        os.fsync(handle); os.fsync(fd)
        yield
    finally: os.close(handle)  # Never unlink a live lock inode.
