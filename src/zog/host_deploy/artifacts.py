"""Resumable filesystem artifact store. A shared mount can outlive the compute VM."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

CHUNK = 1024 * 1024


def digest(data): return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def write(path, value): atomic(path, json.dumps(value, sort_keys=True).encode())


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if json.loads((self.root/'store.json').read_text()) != {'format':'host-deploy-artifacts-1'}:
            raise ValueError('Not a host-deploy artifact store')

    @contextlib.contextmanager
    def locked(self, identity):
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}', identity): raise ValueError('Invalid artifact identity')
        with (self.root/'locks'/identity).open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            if (self.root/'deleted'/identity).exists(): raise ValueError('Artifact was pruned; identity cannot be reused')
            yield self.root/'artifacts'/identity

    def put(self, path, data):
        if path.exists():
            if path.read_bytes() != data: raise ValueError('Stored chunk differs')
        else: atomic(path, data)


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (root/'store.json').exists(): Store(root); return
    if any(root.iterdir()): raise ValueError('Store initialization requires an empty directory')
    for name in ['locks','artifacts','deleted']: (root/name).mkdir()
    write(root/'store.json', {'format':'host-deploy-artifacts-1'})


def publish(source, directory, identity, retention_seconds=604800, metadata=None):
    if type(retention_seconds) is not int or not 60 <= retention_seconds <= 31536000:
        raise ValueError('Retention must be 60..31536000 seconds')
    source = Path(source)
    chunks=[]; whole=hashlib.sha256(); size=0
    with source.open('rb') as stream:
        for data in iter(lambda:stream.read(CHUNK), b''):
            chunks.append(digest(data)); whole.update(data); size+=len(data)
    binding={'sha256':whole.hexdigest(),'bytes':size,'chunks':chunks,'metadata':metadata or {},'retention_seconds':retention_seconds}
    store=Store(directory)
    with store.locked(identity) as root:
        intent=root/'intent.json'
        if intent.exists():
            receipt=json.loads(intent.read_text())
            if receipt['binding']!=binding: raise ValueError('Artifact identity already bound to different content')
        else:
            receipt={'schema':1,'artifact_id':identity,'binding':binding,'created_at':time.time()}
            receipt['expires_at']=receipt['created_at']+retention_seconds
            write(intent,receipt)
        if time.time() >= receipt['expires_at']: raise ValueError('Artifact retention expired')
        with source.open('rb') as stream:
            for index, expected in enumerate(chunks):
                data=stream.read(CHUNK)
                if digest(data)!=expected: raise ValueError('Source changed during publication')
                store.put(root/(str(index)+'-'+expected),data)
            if stream.read(1): raise ValueError('Source changed during publication')
        # Only the final receipt makes an artifact visible for retrieval.
        write(root/'published.json',receipt)
        return receipt


def fetch(directory, identity, output):
    store=Store(directory); output=Path(output)
    if output.exists(): raise ValueError('Output exists')
    with store.locked(identity) as root:
        receipt=json.loads((root/'published.json').read_text())
        if time.time() >= receipt['expires_at']: raise ValueError('Artifact retention expired')
        binding=receipt['binding']; partial=output.with_name(output.name+'.partial')
        output.parent.mkdir(parents=True,exist_ok=True)
        with partial.open('r+b' if partial.exists() else 'w+b') as target:
            for index, expected in enumerate(binding['chunks']):
                offset=index*CHUNK; length=min(CHUNK,binding['bytes']-offset)
                target.seek(offset); data=target.read(length)
                if len(data)==length and digest(data)==expected: continue
                data=(root/(str(index)+'-'+expected)).read_bytes()
                if len(data)!=length or digest(data)!=expected: raise ValueError('Stored artifact corrupted')
                target.seek(offset); target.write(data); target.flush(); os.fsync(target.fileno())
            target.truncate(binding['bytes']); target.flush(); os.fsync(target.fileno())
        with partial.open('rb') as stream:
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=binding['sha256']: raise ValueError('Artifact hash mismatch')
        os.link(partial,output); partial.unlink()
        fd=os.open(output.parent,os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return receipt


def prune(directory, now=None):
    store=Store(directory); now=time.time() if now is None else now; removed=[]
    for root in (store.root/'artifacts').iterdir():
        if root.is_symlink() or not root.is_dir(): continue
        identity=root.name
        if (store.root/'deleted'/identity).exists():
            # Complete cleanup after a crash following the durable tombstone.
            with (store.root/'locks'/identity).open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX); shutil.rmtree(root)
            removed.append(identity); continue
        with store.locked(identity):
            receipt=json.loads((root/'intent.json').read_text())
            if now < receipt['expires_at']: continue
            write(store.root/'deleted'/identity,{'expired_at':receipt['expires_at']})
            shutil.rmtree(root); removed.append(identity)
    fd=os.open(store.root/'artifacts',os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return removed
