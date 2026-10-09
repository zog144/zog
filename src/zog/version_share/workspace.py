"""Local snapshots, secret checks and durable publication records (Linux)."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from .core import ShareError, safe_path

MAXIMUM_SOURCE = 16 * 1024 * 1024
IGNORED_DIRECTORIES = {'.git', '.version-share', '__pycache__', '.pytest_cache', '.venv'}
SECRET_NAMES = {'github-token.txt', 'credentials', 'credentials.json', 'credentials.csv',
                'id_rsa', 'id_ed25519', '.netrc', '.pypirc'}
SECRET_PATTERN = re.compile(rb'(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|'
                            rb'(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def object_hash(kind, content):
    return hashlib.sha1(kind.encode() + b' ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def ignored(path):
    parts = Path(path).parts
    name = parts[-1].lower()
    return (any(p in IGNORED_DIRECTORIES for p in parts) or name.endswith(('.pyc', '.pyo')) or
            name in SECRET_NAMES or name.endswith(('.pem', '.key')) or
            (name.startswith('.env') and name not in ('.env.example', '.env.sample')) or
            name.endswith(('_credentials.csv', '_accesskeys.csv')))


def guard_secret(content, token):
    if (token and token.encode() in content) or SECRET_PATTERN.search(content):
        raise ShareError('secret', 'Possible credential in outgoing content; publication stopped.', 'not-published')


def snapshot(directory, token=''):
    root = Path(directory).resolve()
    files, excluded, total = {}, [], 0
    def visit(folder):
        nonlocal total
        for entry in sorted(folder.iterdir()):
            name = entry.relative_to(root).as_posix()
            if ignored(name):
                excluded.append(name)
                continue
            safe_path(name)
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(entry)
                try:
                    resolved = entry.resolve().relative_to(root)
                except (ValueError, RuntimeError):
                    raise ShareError('unsafe-tree', 'Symbolic link escapes source or forms a cycle.') from None
                if os.path.isabs(target) or '\\' in target or ignored(str(resolved)):
                    raise ShareError('unsafe-tree', 'Symbolic link points outside publishable source.')
                content, git_mode = target.encode('utf-8'), '120000'
            elif stat.S_ISDIR(mode):
                visit(entry)
                continue
            elif stat.S_ISREG(mode):
                # Do not follow a symlink substituted between lstat and open.
                descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, 'rb') as source:
                    content = source.read(MAXIMUM_SOURCE + 1)
                git_mode = '100755' if mode & 0o111 else '100644'
            else:
                raise ShareError('unsupported', 'Only regular files and safe symbolic links can be published.')
            total += len(content)
            if total > MAXIMUM_SOURCE or len(files) >= 10000:
                raise ShareError('unsupported', 'Publication limit is 16 MiB and 10000 source files.')
            guard_secret(name.encode() + b'\0' + content, token)
            files[name] = {'sha': object_hash('blob', content), 'mode': git_mode,
                           'content': base64.b64encode(content).decode()}
    visit(root)
    return files, excluded


def manifest(files):
    return {name: {'sha': item['sha'], 'mode': item['mode']} for name, item in files.items()}


def changes(before, after):
    return {'added': sorted(after.keys() - before.keys()),
            'deleted': sorted(before.keys() - after.keys()),
            'modified': sorted(name for name in before.keys() & after.keys() if before[name] != after[name])}


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError, UnicodeError):
        raise ShareError('local', 'Cannot read working-copy state; retrieve a fresh copy if state is damaged.') from None


def state_directory(directory):
    root = Path(directory).resolve()
    state = root / '.version-share'
    if state.is_symlink() or not state.is_dir():
        raise ShareError('configuration', 'Expected a retrieved working copy with .version-share state.')
    return state


@contextmanager
def locked(directory):
    state = state_directory(directory)
    descriptor = os.open(state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ShareError('conflict', 'Another publication is using this working copy.') from None
        yield state


def save_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.record-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, sort_keys=True, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
