"""Root-only remote staging helper. No host secrets leave this process."""
import argparse
import contextlib
import fcntl
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

BASE = Path('/opt/host-discover')
CONFIG = Path('/etc/host-discover/configuration.json')
UNIT = Path('/etc/systemd/system/host-discover.service')
IDENTITY = '/var/lib/host-discover/identity'
CREDENTIALS = '/var/lib/host-discover/credentials'

def run(args, **kw):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw).stdout.strip()

def safe_path(path):
    for p in [*reversed(path.parents),path]:
        if p.is_symlink(): raise ValueError('Symlink installation path')
        if p.exists():
            s=p.stat()
            if s.st_uid != 0 or s.st_mode & 0o022: raise ValueError('Unsafe installation ownership/mode')

def atomic(path, data, mode=0o640, gid=0):
    safe_path(path.parent)
    if path.is_symlink(): raise ValueError('Symlink destination')
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            os.fchmod(f.fileno(),mode);os.fchown(f.fileno(),0,gid)
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(name):os.unlink(name)

def candidate(old, request):
    from urllib.parse import urlsplit
    settings=request.get('settings',{})
    if not isinstance(settings, dict):raise ValueError('Installer configuration must be a JSON object')
    if {'token','password','private_key'} & set(settings):raise ValueError('Do not supply secrets in installer configuration')
    cloud=request['cloud']
    if old and (old.get('provider')!='aws' or old.get('cloud')!=cloud):raise ValueError('Installed cloud identity mismatch')
    if old.get('token') and not request['migrate']:raise ValueError('Bearer installation requires --migrate')
    if request.get('expected_host_id') and old.get('host_id') and old['host_id']!=request['expected_host_id']:raise ValueError('Registry UUID differs from receipt')
    for k in ('host_id','identity_directory','credential_directory','station_login_file','mirror_box_control'):
        if k in old and k in settings and old[k]!=settings[k]:raise ValueError('Cannot replace existing identity or runtime ownership settings')
    value=old | settings
    value.pop('token',None)
    if value.get('cloud',cloud)!=cloud:raise ValueError('Configured cloud identity mismatch')
    if value.get('provider','aws')!='aws':raise ValueError('AWS provider required')
    server=request.get('server') if request.get('server') is not None else value.get('server')
    if not isinstance(server,str) or not server or any(c.isspace() for c in server):
        raise ValueError('An explicit HTTPS server is required for a fresh installation')
    o=urlsplit(server)
    try: o.port
    except ValueError: raise ValueError('HTTPS origin required') from None
    if o.scheme!='https' or not o.hostname or o.username or o.password or o.path not in ('','/') or o.query or o.fragment:raise ValueError('HTTPS origin required')
    if old.get('server') and old['server'].rstrip('/')!=server.rstrip('/') and not request['migrate']:raise ValueError('Server change requires --migrate')
    value.update(server=server.rstrip('/'),provider='aws',cloud=cloud)
    value.setdefault('identity_directory',IDENTITY);value.setdefault('credential_directory',CREDENTIALS)
    if value['identity_directory']!=IDENTITY or value['credential_directory']!=CREDENTIALS:raise ValueError('Custom state paths require a separately reviewed installer')
    if value.get('host_id'):uuid.UUID(value['host_id'])
    if request['system_ca']:value.pop('ca_file',None)
    if request.get('ca_path'):value['ca_file']=request['ca_path']
    return value

def state_directories():
    try:u=pwd.getpwnam('host-discover')
    except KeyError:
        run(['useradd','--system','--no-create-home','--shell','/sbin/nologin','host-discover']);u=pwd.getpwnam('host-discover')
    try:g=grp.getgrnam('archive-consumers')
    except KeyError:
        run(['groupadd','--system','archive-consumers']);g=grp.getgrnam('archive-consumers')
    parent=Path(IDENTITY).parent;safe_path(parent);parent.mkdir(mode=0o755,parents=True,exist_ok=True)
    for name,mode,gid in [(IDENTITY,0o700,u.pw_gid),(CREDENTIALS,0o750,g.gr_gid)]:
        p=Path(name)
        if p.is_symlink():raise ValueError('Symlink state directory')
        if not p.exists():p.mkdir(mode=mode);os.chown(p,u.pw_uid,gid)
        st=p.stat()
        if not p.is_dir() or st.st_uid!=u.pw_uid or st.st_gid!=gid or stat.S_IMODE(st.st_mode)!=mode:raise ValueError('Unsafe existing state directory')
        for f in p.iterdir():
            st=f.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=u.pw_uid or stat.S_IMODE(st.st_mode)!=(0o600 if name==IDENTITY else 0o640):raise ValueError('Unsafe existing state file')
    safe_path(CONFIG.parent);CONFIG.parent.mkdir(mode=0o750,parents=True,exist_ok=True);os.chown(CONFIG.parent,0,u.pw_gid)
    return u

# Runs as service user, outputs only public/sanitized observations.
PROBE = '''import json,sys,time
from pathlib import Path
from zog.host_discover.daemon import validate_configuration,collect,announce
from zog.host_identify import storage,signatures
c=validate_configuration(json.loads(Path(sys.argv[1]).read_text()))
k=storage.load_key(c['identity_directory']); fingerprint=signatures.fingerprint(k.public_key())
p=Path(c['identity_directory'])/'binding.json'
before=json.loads(storage.read_owned(p,0o600)) if p.exists() else {}
announce(c,collect(c))
after=json.loads(storage.read_owned(p,0o600)) if p.exists() else {}
a=Path(c['credential_directory'])/'archive.json'
grant=json.loads(storage.read_owned(a,0o640)) if a.exists() else {}
from zog.host_discover.roles import Controller
role=Controller(c).status()
print(json.dumps(dict(fingerprint=fingerprint,host_id=after.get('host_id') or c.get('host_id'),enrollment='approved' if after else 'pending',heartbeat='signed-accepted' if before else 'binding-received' if after else 'pending',archive_access='granted' if grant.get('expires_at',0)>time.time() else 'not-granted',mirror_state=role['state'])))
'''

def install(request, release):
    # Python/version and disk checks precede service or identity changes.
    python=request['python']
    run([python,'-c','import sys,venv; assert sys.version_info >= (3,12), "Python 3.12 required"'])
    if shutil.disk_usage('/opt').free<512*1024**2:raise ValueError('At least 512 MiB free required')
    safe_path(BASE);safe_path(CONFIG);safe_path(UNIT)
    old=json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    value=candidate(old,request)
    # Fail before activation if explicit CA path is unavailable or invalid.
    import ssl
    ssl.create_default_context(cafile=value.get('ca_file') or None)
    owner=BASE/'identity-owner.json'
    if owner.exists():
        if json.loads(owner.read_text())['cloud']!=request['cloud']:raise ValueError('Identity belongs to another instance')
    elif not old and any(Path(p).exists() and any(Path(p).iterdir()) for p in (IDENTITY,CREDENTIALS)):
        raise ValueError('Unbound existing identity state: refuse image-cloned or orphan state')
    if not owner.exists():atomic(owner,json.dumps({'cloud':request['cloud']}).encode(),0o600)
    u=state_directories()
    venv=release/'venv'
    if not (release/'ready').exists():
        run([python,'-m','venv',str(venv)])
        run([str(venv/'bin/python'),'-m','pip','install','--disable-pip-version-check','-c',str(release/'requirements-security-tested.txt'),str(release/'host-identify'),str(release/'host-install'),str(release/'host-discover')],timeout=600)
        atomic(release/'ready',b'host-discover=0.4.6 host-identify=0.3.4 host-install=0.4.4\n',0o644)
    executable=str(venv/'bin/python')
    staged=release/'configuration.json'
    atomic(staged,json.dumps(value).encode(),gid=u.pw_gid)
    # Generate missing key and validate existing key with the service UID; never copy it.
    fingerprint=run(['runuser','-u','host-discover','-g','host-discover','-G','archive-consumers','--',executable,'-m','zog.host_discover','--configuration',str(staged),'--fingerprint'])
    unit=(release/'deployment/signed-identity/host-discover.service').read_text().replace('/opt/host-discover/venv',str(venv))
    # Preserve administrator drop-ins. Keep a root-only rollback reference, including legacy token.
    backup=BASE/'rollback'/uuid.uuid4().hex;backup.mkdir(parents=True,mode=0o700)
    for p in (CONFIG,UNIT):
        if p.exists():atomic(backup/p.name,p.read_bytes(),0o600)
    was_active=subprocess.run(['systemctl','is-active','--quiet','host-discover.service']).returncode==0
    was_enabled=subprocess.run(['systemctl','is-enabled','--quiet','host-discover.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    run(['systemctl','stop','host-discover.service']) if UNIT.exists() else None
    # Persist transaction before switch. If interrupted, retries keep state and never restore an old key.
    atomic(BASE/'activation.json',json.dumps({'release':str(release),'rollback':str(backup),'phase':'activating'}).encode(),0o600)
    try:
        atomic(CONFIG,json.dumps(value).encode(),gid=u.pw_gid)
        atomic(UNIT,unit.encode(),0o644)
        run(['systemctl','daemon-reload'])
        result=json.loads(run(['runuser','-u','host-discover','-g','host-discover','-G','archive-consumers','--',executable,'-c',PROBE,str(CONFIG)],timeout=90))
        if request.get('expected_host_id') and result.get('host_id')!=request['expected_host_id']:raise ValueError('Signed binding differs from saved UUID')
        run(['systemctl','enable','host-discover.service']);run(['systemctl','restart','host-discover.service']);run(['systemctl','is-active','--quiet','host-discover.service'])
    except Exception:
        # Preserve identity/roles. Roll back only service/config, never private state.
        subprocess.run(['systemctl','stop','host-discover.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for p in (CONFIG,UNIT):
            saved=backup/p.name
            if saved.exists():atomic(p,saved.read_bytes(),0o644 if p==UNIT else 0o640,gid=0 if p==UNIT else u.pw_gid)
            elif p.exists():p.unlink()
        run(['systemctl','daemon-reload'])
        if not was_enabled:subprocess.run(['systemctl','disable','host-discover.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if was_active:run(['systemctl','restart','host-discover.service'])
        raise
    result.update(daemon='installed',service='active',enabled=True,release=str(release),server=value['server'],fingerprint=fingerprint)
    atomic(BASE/'activation.json',json.dumps({'release':str(release),'rollback':str(backup),'phase':'installed','result':result}).encode(),0o600)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--release',required=True);a=p.parse_args()
    try:
        BASE.mkdir(mode=0o755,parents=True,exist_ok=True);safe_path(BASE)
        fd=os.open(BASE/'install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result=install(json.loads(Path(a.request).read_text()),Path(a.release))
        print(json.dumps(result))
    except Exception as e:
        print('Beacon installation failed ('+type(e).__name__+'); existing state retained. Check Python >=3.12, server pass3 readiness, package access and protected path ownership.',file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
