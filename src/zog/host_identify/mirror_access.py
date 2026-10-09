"""Authorized consumers select ready mirrors; every use checks the per-host token."""
import json
import os
import stat
import time
from pathlib import Path
from . import storage
from .archive import verify
from .signatures import origin


def save_candidates(root,host_id,roles):
    root=storage.directory(root,shared=True)
    value={'version':1,'host_id':host_id,'expires_at':roles['desired']['lease_expires_at'],'candidates':roles['candidates']}
    storage.atomic(root/'mirror-intent.json',json.dumps({'version':1,'host_id':host_id,'desired':roles['desired']}).encode(),0o640,root.stat().st_gid)
    storage.atomic(root/'mirror-candidates.json',json.dumps(value).encode(),0o640,root.stat().st_gid)


def read_access(root,public_keys,issuer,audience,operation,collection,expected_mirror):
    """Return ready HTTPS origins and one short-lived host token; never log this result.

    expected_mirror pins the original grant's configured cluster entry point. Each
    mirror must independently validate the same configured cluster audience.
    """
    root=Path(root)
    grant=storage.read_credentials(root/'archive.json',public_keys,issuer,audience,operation,collection,expected_mirror)
    fd=os.open(root/'mirror-candidates.json',os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o640 or info.st_uid!=root.stat().st_uid or info.st_nlink!=1 or info.st_size>32768:raise PermissionError('Unsafe candidate file')
        value=json.load(f)
    if value['version']!=1 or type(value['expires_at']) is not int or not time.time()<value['expires_at']<=time.time()+905:raise PermissionError('Expired mirror discovery')
    claims=verify(grant['token'],public_keys,issuer,audience,operation,collection)
    if value['host_id']!=claims['sub']:raise PermissionError('Mirror discovery identity mismatch')
    if not isinstance(value['candidates'],list) or len(value['candidates'])>32:raise PermissionError('Invalid mirror discovery')
    endpoints=[origin(c['endpoint']) for c in value['candidates'] if c['ready'] is True and c['state']=='ready']
    if not endpoints:raise PermissionError('No ready authorized mirror')
    return {'endpoints':endpoints,'token':grant['token'],'expires_at':min(grant['expires_at'],value['expires_at']),'format':grant['format']}
