"""Self-contained, fixed-path SSM helper for station-access. No arbitrary commands/paths."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit
from uuid import UUID

CONFIG = Path('/etc/host-discover/configuration.json')
DESTINATIONS = Path('/var/lib/host-discover/beacon-destinations.json')
RECEIPTS = Path('/var/lib/host-deploy/station-deployments')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def origin(value):
    if not isinstance(value, str) or len(value) > 300 or any(c.isspace() for c in value):
        raise ValueError('origin')
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
        raise ValueError('origin')
    name = p.hostname.encode('idna').decode().lower()
    if ':' in name: name = '[' + name + ']'
    return 'https://' + name + (':' + str(p.port) if p.port and p.port != 443 else '')


def read(path, limit=32768):
    if any(p.is_symlink() for p in [path, *path.parents]): raise ValueError('symlink')
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    if len(value) > limit: raise ValueError('size')
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_nlink != 1: raise ValueError('file')
    return value


def validate_destinations(value, primary):
    if not isinstance(value, dict) or set(value) != {'version', 'destinations'} or value['version'] != 1:
        raise ValueError('schema')
    rows = value['destinations']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16 or len(encoded(value)) > 30000: raise ValueError('size')
    seen = set()
    for row in rows:
        if set(row) != {'id', 'label', 'server', 'enabled', 'ca_certificate', 'revision'}: raise ValueError('fields')
        UUID(row['id'])
        if not isinstance(row['label'], str) or not 1 <= len(row['label']) <= 100: raise ValueError('label')
        if type(row['revision']) is not int or row['revision'] < 1 or type(row['enabled']) is not bool: raise ValueError('revision')
        server = origin(row['server'])
        if server != row['server'] or server in seen: raise ValueError('origin')
        seen.add(server)
        pem = row['ca_certificate']
        if not isinstance(pem, str) or len(pem) > 12000 or 'PRIVATE KEY' in pem: raise ValueError('ca')
        if pem: ssl.create_default_context(cadata=pem)
    if not any(r['server'] == primary and r['enabled'] for r in rows): raise ValueError('primary-must-remain-enabled')
    return value


def service(name):
    result = subprocess.run(['systemctl', 'show', name, '-p', 'ActiveState', '-p', 'MainPID'],
                            capture_output=True, text=True, timeout=8, check=False)
    if result.returncode: return 'unknown', 0
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    state = fields.get('ActiveState')
    return state if state in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown', int(fields.get('MainPID', '0'))


def version(venv, package):
    if not venv: return None
    candidates = list(venv.glob('lib/python*/site-packages/' + package + '-*.dist-info/METADATA'))
    if len(candidates) != 1: return None
    for line in candidates[0].read_text()[:16000].splitlines():
        if re.fullmatch(r'Version: [A-Za-z0-9.+_-]{1,40}', line): return line[9:]
    return None


def inspect_host(target):
    config = json.loads(read(CONFIG))
    cloud = config.get('cloud', {})
    if config.get('provider') != 'aws' or cloud != {k:target[k] for k in ('account_id', 'region', 'instance_id')}:
        raise ValueError('target-mismatch')
    if config.get('host_id') and config['host_id'] != target['host_id']: raise ValueError('host-mismatch')
    primary = origin(config['server'])
    active, pid = service('host-discover.service')
    argv = read(Path('/proc') / str(pid) / 'cmdline', 8192).decode().split('\0') if pid else []
    # proc files report link count one but size zero; bounded read still works.
    configured = all(flag in argv and argv.index(flag) + 1 < len(argv) and argv[argv.index(flag)+1] == str(path)
                     for flag, path in [('--configuration', CONFIG), ('--destinations', DESTINATIONS)])
    executable = next((a for a in argv if a.startswith('/opt/host-discover/') and a.endswith('/bin/host-discover')), '')
    venv = Path(executable).parent.parent if executable else None
    current, current_hash, file_ok = None, None, False
    if DESTINATIONS.exists():
        raw = read(DESTINATIONS)
        current = json.loads(raw);current_hash = digest(raw)
        try:
            validate_destinations(current, primary)
            st = DESTINATIONS.stat()
            file_ok = stat.S_IMODE(st.st_mode) == 0o600 and (not pid or st.st_uid == (Path('/proc')/str(pid)).stat().st_uid)
        except Exception: pass
    summaries = []
    if current and file_ok:
        summaries = [dict(id=r['id'], label=r['label'], server=r['server'], enabled=r['enabled'], revision=r['revision'],
                          ca_sha256=digest(r['ca_certificate'].encode()) if r['ca_certificate'] else None) for r in current['destinations']]
    station_state, _ = service('station-access.service')
    return dict(primary=primary, destinations_sha256=current_hash, destinations=summaries,
                beacon_state=active, station_state=station_state,
                beacon_version=version(venv, 'host_discover'),
                station_version=version(Path('/opt/station-access/venv'), 'station_access'),
                apply_supported=bool(active == 'active' and configured and file_ok),
                reason='ready' if active == 'active' and configured and file_ok else 'Existing active beacon and a valid configured destination file are required.')


def atomic(path, data, uid=0, gid=0, mode=0o600):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), uid, gid);os.fchmod(stream.fileno(), mode)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def guard_receipts():
    for p in reversed([RECEIPTS, *RECEIPTS.parents]):
        if p.exists() and (p.is_symlink() or p.stat().st_uid != 0 or p.stat().st_mode & 0o022): raise ValueError('receipt-directory')
    RECEIPTS.mkdir(parents=True, mode=0o700, exist_ok=True)


def handle(request):
    identifier = str(UUID(request['id']))
    if identifier != request['id']: raise ValueError('id')
    action = request['action']
    if action == 'inspect':
        return dict(schema=1, id=identifier, status='inspected', observation=inspect_host(request['target']))
    if action not in ('apply', 'recover'): raise ValueError('action')
    intent = {k:request[k] for k in ('id', 'target', 'expected_sha256', 'destinations')}
    intent_hash = digest(encoded(intent))
    receipt_path = RECEIPTS / (identifier + '.json')
    if action == 'recover':
        # Read-only recovery: absence never authorizes another submission.
        if not receipt_path.exists(): return dict(schema=1,id=identifier,status='uncertain')
        receipt = json.loads(read(receipt_path, 65536))
        if receipt['intent_hash'] != intent_hash: raise ValueError('intent-mismatch')
        observed = inspect_host(request['target'])
        installed = observed['destinations_sha256'] == receipt['desired_sha256']
        return dict(schema=1,id=identifier,status='installed' if installed else 'uncertain',sha256=observed['destinations_sha256'])
    guard_receipts()
    with (RECEIPTS / 'apply.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        observed = inspect_host(request['target'])
        validate_destinations(request['destinations'], observed['primary'])
        data = encoded(request['destinations']) + b'\n'
        desired = digest(data)
        if receipt_path.exists():
            receipt = json.loads(read(receipt_path, 65536))
            if receipt['intent_hash'] != intent_hash: raise ValueError('intent-mismatch')
            return dict(schema=1,id=identifier,status='installed' if observed['destinations_sha256']==desired else 'uncertain',sha256=observed['destinations_sha256'])
        if not observed['apply_supported'] or observed['destinations_sha256'] != request['expected_sha256']:
            return dict(schema=1,id=identifier,status='blocked')
        before = read(DESTINATIONS);st = DESTINATIONS.stat()
        if digest(before) != request['expected_sha256']: return dict(schema=1,id=identifier,status='blocked')
        atomic(RECEIPTS/(identifier+'.before.json'), before)
        # Prepared receipt is durable before replacing the file. Recovery never substitutes new intent.
        receipt = dict(intent_hash=intent_hash, desired_sha256=desired, phase='prepared')
        atomic(receipt_path, encoded(receipt))
        atomic(DESTINATIONS, data, st.st_uid, st.st_gid)
        if digest(read(DESTINATIONS)) != desired: raise RuntimeError('verification')
        atomic(receipt_path, encoded(dict(receipt,phase='installed')))
        return dict(schema=1,id=identifier,status='installed',sha256=desired)


def main(request):
    try:
        if os.geteuid() != 0: raise ValueError('root-required')
        value = handle(request)
    except Exception:
        value = dict(schema=1,id=request.get('id'),status='uncertain' if request.get('action') in ('apply','recover') else 'unavailable')
    print(json.dumps(value, separators=(',', ':')))
