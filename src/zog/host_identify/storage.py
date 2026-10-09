"""Linux local state. Directories are provisioned explicitly, never copied into images."""
import json
import os
import stat
import tempfile
import time
import fcntl
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .archive import verify
from .signatures import origin


def directory(path, *, shared=False):
    path=Path(path)
    # Reject symlinks in every component and writable ancestors owned by others.
    for parent in [*reversed(path.parents),path]:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):raise PermissionError('Unsafe state directory')
        if parent == path:
            expected=0o750 if shared else 0o700
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode)!=expected:raise PermissionError('Incorrect state ownership or mode')
        elif info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            raise PermissionError('Writable ancestor directory')
    return path


def read_owned(path, mode):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode)!=mode or info.st_nlink!=1:
            raise PermissionError('Unsafe state file')
        if info.st_size>32768:raise ValueError('State file too large')
        return f.read()


def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic(path,data,mode=0o600,gid=None):
    path=Path(path)
    if path.is_symlink():raise PermissionError('Symlink destination')
    fd,name=tempfile.mkstemp(prefix='.new-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode)
            if gid is not None:os.fchown(f.fileno(),-1,gid)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path);sync_directory(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def load_existing_key(root):
    """Read-only legacy-key loader; never initializes missing identity material."""
    root=Path(root)
    if Path(os.path.abspath(root)).is_relative_to('/state') or any(os.path.lexists(root/name) for name in ('initialization.json','receipt.json','prepared-key.pem')):
        raise PermissionError('Managed identity requires installer consumption receipt')
    from .initialization import directory_fd, read, decode_key, IdentityStateError
    with directory_fd(root) as fd:
        # Open the existing lock without creating it. Serialize with both
        # legacy bootstrap and managed preparation before checking markers.
        try:handle=os.open('key.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except FileNotFoundError:raise IdentityStateError('Existing key lock missing; recovery required') from None
        try:
            info=os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
                raise PermissionError('Unsafe key lock')
            fcntl.flock(handle,fcntl.LOCK_SH)
            if set(os.listdir(fd)) & {'initialization.json','receipt.json','prepared-key.pem'}:
                raise PermissionError('Managed identity requires installer consumption receipt')
            return decode_key(read(fd,'identity.pem'))
        finally:os.close(handle)


def load_key(root):
    """Legacy bootstrap only. Managed host-install identities require receipts."""
    root=Path(root)
    if Path(os.path.abspath(root)).is_relative_to('/state') or any(os.path.lexists(root/name) for name in ('initialization.json','receipt.json','prepared-key.pem')):
        raise PermissionError('Managed identity requires explicit initialization/admission API')
    root=directory(root)
    # Serialize first creation across multiple daemon invocations, survive restarts.
    fd=os.open(root/'key.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+b') as lock:
        info=os.fstat(lock.fileno())
        if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise PermissionError('Unsafe key lock')
        fcntl.flock(lock,fcntl.LOCK_EX)
        # The preliminary check may have happened before another initializer
        # acquired the lock. Recheck under the SAME never-unlinked lock inode.
        if any(os.path.lexists(root/name) for name in ('initialization.json','receipt.json','prepared-key.pem')):
            raise PermissionError('Managed identity requires explicit initialization/admission API')
        path=root/'identity.pem'
        if not path.exists():
            key=Ed25519PrivateKey.generate()
            atomic(path,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key=serialization.load_pem_private_key(read_owned(path,0o600),password=None)
        if not isinstance(key,Ed25519PrivateKey):raise ValueError('Ed25519 required')
        return key


def clear_credentials(root):
    root=directory(root,shared=True)
    path=root/'archive.json'
    if path.is_symlink():raise PermissionError('Symlink credential')
    if path.exists():path.unlink();sync_directory(root)


def save_response(root, response, *, expected_host, expected_mirror, expected_issuer, expected_audience):
    root=directory(root,shared=True)
    if response.get('version')!=2 or response.get('host_id')!=str(expected_host) or 'archive' not in response:
        raise ValueError('Malformed heartbeat response')
    grant=response['archive']
    if grant is None:
        clear_credentials(root);return
    if not isinstance(grant,dict) or set(grant)!={'version','format','mirror','token','expires_at','issuer','audience'}:
        raise ValueError('Malformed archive grant')
    if grant['version']!=1 or grant['format']!='zog-archive-jwt-v1' or origin(grant['mirror'])!=origin(expected_mirror) or grant['issuer']!=expected_issuer or grant['audience']!=expected_audience:
        raise ValueError('Unexpected archive destination or format')
    if type(grant['expires_at']) is not int or not time.time()<grant['expires_at']<=time.time()+905 or not isinstance(grant['token'],str) or not 1<len(grant['token'])<=16384:
        raise ValueError('Invalid credential expiry')
    # Parse for consistency only: HTTPS authenticates delivery; this is NOT JWT verification.
    import jwt
    try:
        header=jwt.get_unverified_header(grant['token'])
        claims=jwt.decode(grant['token'],options={'verify_signature':False})
        if set(header)!={'alg','kid','typ'} or header['alg']!='EdDSA' or header['typ']!='at+jwt':raise ValueError()
        if claims['sub']!=str(expected_host) or claims['iss']!=expected_issuer or claims['aud']!=expected_audience or claims['exp']!=grant['expires_at']:raise ValueError()
    except (jwt.PyJWTError,KeyError,ValueError):raise ValueError('Malformed archive token') from None
    # Consumers and mirror independently verify the JWT against configured public keys.
    atomic(root/'archive.json',json.dumps(grant).encode(),0o640,root.stat().st_gid)


def read_credentials(path, public_keys, issuer, audience, operation, collection, expected_mirror):
    """Consumer API. Requires group read access; checks token expiry on EVERY use."""
    path=Path(path)
    for parent in [*path.parents]:
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):raise PermissionError('Symlink credential directory')
        if info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:raise PermissionError('Writable credential ancestor')
    info=path.parent.lstat()
    owner=info.st_uid
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o750:raise PermissionError('Unsafe credential directory')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o640 or info.st_uid!=owner or info.st_size>32768 or info.st_nlink!=1:
            raise PermissionError('Unsafe credential file')
        grant=json.load(f)
    if grant['expires_at']<=time.time():raise PermissionError('Expired credential')
    if grant['format']!='zog-archive-jwt-v1' or grant['version']!=1 or origin(grant['mirror'])!=origin(expected_mirror):raise PermissionError('Invalid credential')
    verify(grant['token'],public_keys,issuer,audience,operation,collection)
    return grant


def purge_expired(root):
    root=directory(root,shared=True)
    path=root/'archive.json'
    if path.exists():
        try:
            value=json.loads(read_owned(path,0o640))
            expired=type(value.get('expires_at')) is not int or value['expires_at']<=time.time()
        except (ValueError,KeyError):expired=True
        if expired:clear_credentials(root)
