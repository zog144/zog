"""Resumable identity preparation. Authorization/admission belongs to host-install.

Call only after verifying STATE and the root-owned installation transaction.
This module never interprets `mode=fresh` as authorization or consumes installer
transactions. The returned public receipt must be committed by that coordinator.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import stat
import uuid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .signatures import fingerprint


class IdentityStateError(ValueError):
    """Identity needs explicit reconciliation; do not generate a replacement."""


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


def validate_authorization(value):
    fields={'schema','kind','authorization_id','installation_id','state_volume_id',
            'identity_directory','account_profile','expected_fingerprint'}
    if not isinstance(value,dict) or set(value)!=fields or type(value['schema']) is not int or value['schema']!=1 or value['kind']!='zog-identity-initialization':
        raise IdentityStateError('Unsupported initialization authorization')
    for name in ('authorization_id','installation_id','state_volume_id'):
        if str(uuid.UUID(value[name]))!=value[name]:raise IdentityStateError('Noncanonical authorization UUID')
    if value['account_profile']!='zog-host-accounts-v1' or value['expected_fingerprint'] is not None:
        raise IdentityStateError('Fresh initialization only; migration requires a separate operation')
    path=value['identity_directory']
    if not isinstance(path,str) or not path.startswith('/') or any(p in ('','.','..') for p in path.split('/')[1:]):
        raise IdentityStateError('Invalid identity directory')
    return value


@contextmanager
def directory_fd(path):
    """Walk without symlinks and keep operations anchored to the checked directory."""
    path=os.fspath(path)
    if not path.startswith('/') or any(p in ('','.','..') for p in path.split('/')[1:]):raise IdentityStateError('Absolute canonical directory required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        parts=path.split('/')[1:]
        for i,part in enumerate(parts):
            following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=following
            info=os.fstat(fd)
            if info.st_uid not in (0,os.geteuid()) or (info.st_mode&0o022 and not info.st_mode&stat.S_ISVTX):
                raise PermissionError('Unsafe directory ancestor')
            if i==len(parts)-1 and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700):
                raise PermissionError('Identity directory must be owned by service account, mode 0700')
        yield fd
    finally:os.close(fd)


def read(fd,name):
    try:handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    except FileNotFoundError:return None
    with os.fdopen(handle,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>32768:
            raise PermissionError('Unsafe identity file')
        data=stream.read(32769)
        if len(data)>32768:raise IdentityStateError('Oversize identity file')
        return data


def create(fd,name,data):
    # O_EXCL intentionally never replaces existing keys/receipts. Partial files
    # after an interrupted write cause refusal, never implicit regeneration.
    handle=os.open(name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=fd)
    with os.fdopen(handle,'wb') as stream:
        os.fchmod(stream.fileno(),0o600)
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.fsync(fd)


def decode_key(data):
    try:key=serialization.load_pem_private_key(data,password=None)
    except (ValueError,TypeError):raise IdentityStateError('Missing or corrupt identity key') from None
    if not isinstance(key,Ed25519PrivateKey):raise IdentityStateError('Ed25519 identity required')
    return key


@contextmanager
def locked(fd):
    handle=os.open('key.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
    try:
        info=os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise PermissionError('Unsafe key lock')
        fcntl.flock(handle,fcntl.LOCK_EX)
        yield
    finally:os.close(handle)  # Never unlink the shared lock inode.


def prepare(root, authorization):
    """Prepare the same key/receipt on retries; does NOT authorize networking.

Caller authenticates authorization and verified mount before this call. No
credential, root receipt or authorization can be supplied by a remote beacon.
"""
    validate_authorization(authorization)
    if os.fspath(root)!=authorization['identity_directory']:raise IdentityStateError('Authorization directory mismatch')
    with directory_fd(root) as fd, locked(fd):
        transaction=read(fd,'initialization.json')
        fresh=transaction is None
        if transaction is None:
            # No adoption of a legacy/published/orphan key by a new transaction.
            if any(n!='key.lock' for n in os.listdir(fd)):raise IdentityStateError('Nonempty identity directory requires reconciliation')
            create(fd,'initialization.json',encode(authorization))
        elif transaction!=encode(authorization):raise IdentityStateError('Different or corrupt initialization transaction')
        # Recover only our interrupted atomic publication: the two names must
        # refer to exactly the same regular inode owned by this account.
        names=os.listdir(fd)
        if set(names)-{'key.lock','initialization.json','prepared-key.pem','receipt.json','identity.pem','publish-key.tmp'}:
            raise IdentityStateError('Unexpected initialization candidate/state')
        if 'publish-key.tmp' in names and 'identity.pem' in names:
            a=os.stat('publish-key.tmp',dir_fd=fd,follow_symlinks=False)
            b=os.stat('identity.pem',dir_fd=fd,follow_symlinks=False)
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino) or not stat.S_ISREG(a.st_mode) or a.st_uid!=os.geteuid() or stat.S_IMODE(a.st_mode)!=0o600 or a.st_nlink!=2:
                raise IdentityStateError('Conflicting publication candidate')
            os.unlink('publish-key.tmp',dir_fd=fd);os.fsync(fd)
        staged=read(fd,'prepared-key.pem');published=read(fd,'identity.pem');receipt=read(fd,'receipt.json')
        if staged is None:
            if not fresh or published is not None or receipt is not None:raise IdentityStateError('Prepared key missing; recovery required')
            key=Ed25519PrivateKey.generate()
            staged=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            create(fd,'prepared-key.pem',staged)
        key=decode_key(staged)
        # Re-establish barriers after an earlier fsync failure before publishing.
        for name in ('initialization.json','prepared-key.pem'):
            handle=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            try:os.fsync(handle)
            finally:os.close(handle)
        os.fsync(fd)
        expected={'schema':1,'kind':'zog-identity-receipt','authorization_sha256':hashlib.sha256(encode(authorization)).hexdigest(),
                  'authorization_id':authorization['authorization_id'],'installation_id':authorization['installation_id'],
                  'state_volume_id':authorization['state_volume_id'],'fingerprint':fingerprint(key.public_key())}
        # Persist receipt before publication. A damaged receipt is never replaced.
        if receipt is None:
            if published is not None:raise IdentityStateError('Published identity without receipt')
            create(fd,'receipt.json',encode(expected))
        elif receipt!=encode(expected):raise IdentityStateError('Identity receipt mismatch')
        handle=os.open('receipt.json',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:os.fsync(handle)
        finally:os.close(handle)
        os.fsync(fd)
        if published is None:
            # Durable stage permits retry even if this expendable temporary file
            # was interrupted. Atomic replace is serialized by key.lock; existing
            # identity.pem is never replaced by this code path.
            temporary='publish-key.tmp'
            if temporary in os.listdir(fd):
                read(fd,temporary);os.unlink(temporary,dir_fd=fd);os.fsync(fd)
            create(fd,temporary,staged)
            # Link publishes atomically without replacement. Remove temporary
            # hard link before return; retry handles an interrupted unlink.
            os.link(temporary,'identity.pem',src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
            os.unlink(temporary,dir_fd=fd);os.fsync(fd)
        elif published!=staged:raise IdentityStateError('Published identity differs from prepared key')
        return expected


def load_existing(root, completion):
    """Load only after caller verifies the root-owned consumption receipt.

completion is the exact public receipt committed by host-install, not a boolean.
No file or lock is created here. Network admission requires this successful load.
"""
    with directory_fd(root) as fd:
        return load_existing_fd(fd, os.fspath(root), completion)


def load_existing_fd(fd, identity_directory, completion):
    """Read a consumed identity through the caller's retained STATE descriptor.

    The caller verifies the mount and independent privileged completion first.
    Does not close fd, reopen identity_directory, create files, or acquire a
    write lock. identity_directory is only the authorization's canonical name.
    """
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError('Unsafe identity directory')
    if not isinstance(completion, dict):
        raise IdentityStateError('Independent consumption receipt required')
    allowed = {'key.lock', 'initialization.json', 'prepared-key.pem', 'receipt.json', 'identity.pem'}
    if set(os.listdir(fd)) - allowed:
        raise IdentityStateError('Unexpected initialization candidate/state')
    raw_authorization=read(fd,'initialization.json')
    authorization=json.loads(raw_authorization or b'null')
    validate_authorization(authorization)
    if raw_authorization!=encode(authorization):
        raise IdentityStateError('Noncanonical initialization authorization')
    if authorization['identity_directory']!=identity_directory:raise IdentityStateError('Identity directory changed')
    key=decode_key(read(fd,'identity.pem'))
    staged=read(fd,'prepared-key.pem')
    if staged is None or fingerprint(decode_key(staged).public_key())!=fingerprint(key.public_key()):
        raise IdentityStateError('Prepared identity mismatch')
    expected={'schema':1,'kind':'zog-identity-receipt','authorization_sha256':hashlib.sha256(encode(authorization)).hexdigest(),
              'authorization_id':authorization['authorization_id'],'installation_id':authorization['installation_id'],
              'state_volume_id':authorization['state_volume_id'],'fingerprint':fingerprint(key.public_key())}
    if read(fd,'receipt.json')!=encode(expected) or encode(completion)!=encode(expected):
        raise IdentityStateError('Initialization not durably consumed by installer')
    return key
