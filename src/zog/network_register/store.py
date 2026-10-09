"""Reference durable StateStore, plus the single-writer process lock.

SQLite transactions protect metadata; worker_lock must span dispatch and its
completion in a future provider worker. No expiring lease is used.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading
from .contracts import NetworkError


class SqliteStateStore:
    def __init__(self, path, *, create=False):
        self.path = Path(path).absolute()
        self._local = threading.local()
        if not self.path.parent.is_dir():
            raise NetworkError('storage')
        if create:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise NetworkError('conflict') from None
            os.close(fd)
        elif not self.path.is_file():
            raise NetworkError('storage')
        with self.transaction():
            if create:
                self._local.db.execute('CREATE TABLE objects (kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(kind,key))')
                self.write('meta', 'schema', {'version': 1})
            elif self.read('meta', 'schema') != {'version': 1}: raise NetworkError('storage')
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    @contextmanager
    def transaction(self):
        if getattr(self._local, 'db', None) is not None:
            raise RuntimeError('Nested store transaction')
        db = None
        try:
            # Never recreate a lost database during recovery or a later call.
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            self._local.db = db
            yield self
            db.execute('COMMIT')
        except sqlite3.Error:
            raise NetworkError('storage') from None
        finally:
            self._local.db = None
            if db is not None: db.close()  # rolls back any uncommitted transaction

    def _db(self):
        db = getattr(self._local, 'db', None)
        if db is None: raise RuntimeError('Store access requires a transaction')
        return db

    def read(self, kind, key):
        row = self._db().execute('SELECT value FROM objects WHERE kind=? AND key=?', (kind, key)).fetchone()
        try: return None if row is None else json.loads(row[0])
        except (ValueError, TypeError): raise NetworkError('storage') from None

    def write(self, kind, key, value):
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self._db().execute('INSERT INTO objects VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET value=excluded.value', (kind, key, encoded))

    def delete(self, kind, key):
        self._db().execute("DELETE FROM objects WHERE kind=? AND key=?", (kind, key))

    def all(self, kind):
        rows = self._db().execute('SELECT value FROM objects WHERE kind=? ORDER BY key', (kind,)).fetchall()
        try: return [json.loads(row[0]) for row in rows]
        except (ValueError, TypeError): raise NetworkError('storage') from None

    @contextmanager
    def worker_lock(self):
        # This lock is intentionally separate from short metadata transactions.
        fd = os.open(str(self.path) + '.worker-lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise NetworkError('conflict') from None
            yield
        finally: os.close(fd)
