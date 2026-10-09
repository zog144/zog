"""Single-host process/thread locks; never hold a DB transaction across controller calls."""
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import threading
from django.conf import settings

_threads = {}
_guard = threading.Lock()

@contextmanager
def workspace_lock(identity):
    key = hashlib.sha256(str(identity).encode()).hexdigest()
    with _guard:
        lock = _threads.setdefault(key, threading.RLock())
    directory = Path(settings.STATE_DIRECTORY) / "workspace-locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock, (directory / key).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
