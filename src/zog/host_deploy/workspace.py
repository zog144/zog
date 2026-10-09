"""Local workspace identity and recovery-critical JSON persistence (Linux)."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(directory, allow_retired=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'workspace.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another operation holds this workspace lock') from None
        if not allow_retired and (directory/'retired.json').exists():
            raise RuntimeError('Workspace retired by handoff; restore the checkpoint in a new directory')
        yield directory


def initialize(directory, name, profile, region):
    with locked(directory) as root:
        path = root/'workspace.json'
        if path.exists():
            value = json.loads(path.read_text())
            if any(value[k] != v for k,v in {'name':name,'profile':profile,'region':region}.items()):
                raise ValueError('Existing workspace has different settings; use a new directory')
            return value
        value = {'schema':1,'workspace_id':uuid.uuid4().hex,'name':name,'profile':profile,'region':region}
        save(path, value)
        return value


def load(directory):
    value = json.loads((Path(directory)/'workspace.json').read_text())
    if value.get('schema') != 1 or uuid.UUID(value['workspace_id']).hex != value['workspace_id']:
        raise ValueError('Invalid workspace identity')
    return value
