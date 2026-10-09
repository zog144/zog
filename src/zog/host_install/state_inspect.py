"""Read-only Linux inspection; never reads keys or creates directories."""
import errno
import grp
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from pathlib import Path
from .state_contract import ACCOUNTS, CONFIG, PROFILE, StateError, canonical, decode, host_slots, require, validate


def directory(path):
    require(path.startswith('/') and all(p not in ('.', '..') for p in path.split('/')), 'unsafe-path', path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in filter(None, path.split('/')):
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def metadata(fd, uid, gid, mode, is_directory=True):
    s = os.fstat(fd)
    require((stat.S_ISDIR(s.st_mode) if is_directory else stat.S_ISREG(s.st_mode)) and
            (s.st_uid, s.st_gid, stat.S_IMODE(s.st_mode)) == (uid, gid, mode),
            'ownership-mode', 'unexpected type, ownership or permissions')
    if not is_directory: require(s.st_nlink == 1, 'hardlink', 'record must have one link')


def read_at(fd, name, uid=0, gid=0, mode=0o444):
    require('/' not in name and name not in ('', '.', '..'), 'unsafe-path', name)
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        metadata(child, uid, gid, mode, False)
        before = os.fstat(child)
        data = bytearray()
        while len(data) <= 65536:
            part = os.read(child, min(8192, 65537 - len(data)))
            if not part: break
            data.extend(part)
        after = os.fstat(child)
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'record-changed', name)
        require(len(data) <= 65536, 'record-size', name)
        return bytes(data)
    finally: os.close(child)


def load_configuration():
    for path in ('/', '/etc', '/etc/zog', CONFIG):
        fd = directory(path)
        try:
            s = os.fstat(fd)
            require(s.st_uid == 0 and s.st_gid == 0 and not s.st_mode & 0o022, 'configuration-owner', path)
        finally: os.close(fd)
    fd = directory(CONFIG)
    try:
        b, i, a = (decode(read_at(fd, n + '.json')) for n in ('bootstrap', 'installation', 'accounts'))
        try:
            m = {'schema': 1, 'kind': 'zog-state-volume', 'installation_id': b['installation_id'], 'account_profile': PROFILE,
                 **{k: b['state'][k] for k in ('state_volume_id', 'partition_partuuid', 'filesystem_uuid')}}
        except (KeyError, TypeError) as exc:
            raise StateError('record-fields', 'invalid STATE binding') from exc
        bundle = validate(dict(bootstrap=b, installation=i, accounts=a, marker=m))
        for reg in b['registries']:
            if reg['ca'] is not None:
                ca_fd = directory(CONFIG + '/ca')
                try:
                    metadata(ca_fd, 0, 0, 0o755)
                    raw = read_at(ca_fd, reg['registry_id'] + '.pem')
                finally: os.close(ca_fd)
                require(hashlib.sha256(raw).hexdigest() == reg['ca']['sha256'], 'ca-digest', reg['registry_id'])
        return bundle
    finally: os.close(fd)


def mounts(text):
    def unescape(s): return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), s)
    out = []
    for line in text.splitlines():
        left, right = line.split(' - ', 1)
        a, b = left.split(), right.split()
        out.append(dict(id=a[0], device=a[2], root=unescape(a[3]), target=unescape(a[4]),
                        options=a[5].split(','), type=b[0], super_options=b[2].split(',')))
    return out


def topology():
    r = subprocess.run(['lsblk', '--json', '--list', '--output', 'MAJ:MIN,TYPE,PARTUUID,UUID,FSTYPE'],
                       check=True, capture_output=True, text=True, timeout=15)
    return json.loads(r.stdout)['blockdevices']


def assess_mount(rows, devices, expected, root_device):
    """Pure fixture helper, not proof when supplied with untrusted observations."""
    matching = [r for r in rows if r['target'] == '/state']
    require(len(matching) == 1, 'state-not-mounted', 'exactly one /state mount required')
    m = matching[0]
    require(m['root'] == '/' and m['type'] == 'ext4', 'wrong-mount', 'whole ext4 filesystem required')
    require(all('rw' in m[k] and 'ro' not in m[k] for k in ('options', 'super_options')), 'state-read-only', 'writable mount and superblock required')
    require(m['device'] != root_device, 'host-root-device', 'STATE shares host root')
    require(not any(r['target'].startswith('/state/') for r in rows), 'nested-mount', 'unexpected mount below STATE')
    p = [d for d in devices if d.get('partuuid') == expected['partition_partuuid']]
    f = [d for d in devices if d.get('uuid') == expected['filesystem_uuid']]
    require(len(p) == len(f) == 1, 'volume-ambiguous-or-missing', 'UUID and PARTUUID must each resolve uniquely')
    require(p[0] == f[0] and p[0]['maj:min'] == m['device'] and p[0]['type'] == 'part' and p[0]['fstype'] == 'ext4', 'wrong-volume', 'partition/filesystem/mount mismatch')
    return m


def accounts_match():
    for name, gid in ACCOUNTS['groups'].items():
        require(grp.getgrnam(name).gr_gid == gid and grp.getgrgid(gid).gr_name == name and
                len([g for g in grp.getgrall() if g.gr_gid == gid]) == 1, 'account-mismatch', name)
    for name, wanted in ACCOUNTS['users'].items():
        r = pwd.getpwnam(name)
        require((r.pw_uid, r.pw_gid, r.pw_dir, r.pw_shell) ==
                (wanted['uid'], wanted['gid'], '/state/' + name, '/usr/sbin/nologin') and
                len([p for p in pwd.getpwall() if p.pw_uid == wanted['uid']]) == 1, 'account-mismatch', name)
        require(set(os.getgrouplist(name, wanted['gid'])) == {wanted['gid'], *wanted['groups']}, 'account-mismatch', 'unexpected supplementary groups')


def _mount(bundle):
    rows = mounts(Path('/proc/self/mountinfo').read_text())
    root = os.stat('/').st_dev
    return assess_mount(rows, topology(), bundle['bootstrap']['state'], f'{os.major(root)}:{os.minor(root)}')


def root_partition_partuuid():
    rows = mounts(Path('/proc/self/mountinfo').read_text())
    roots = [row for row in rows if row['target'] == '/']
    require(len(roots) == 1, 'host-root-ambiguous', 'exactly one host root mount required')
    devices = [device for device in topology() if device.get('maj:min') == roots[0]['device']]
    if len(devices) != 1 or devices[0].get('type') != 'part':
        return None
    value = devices[0].get('partuuid')
    return value if isinstance(value, str) and value else None


def host_generation_report(context):
    """Verified host-generation metadata; read-only and bound to current STATE."""
    context.recheck()
    installation = context.bundle['installation']
    recorded = installation['installer_recorded']
    slots = host_slots(installation)
    root_partuuid = root_partition_partuuid()
    booted = [
        slot for slot, row in slots.items()
        if row is not None and root_partuuid is not None and row['root_partuuid'] == root_partuuid
    ]
    require(len(booted) <= 1, 'slot-binding', 'root partition matches multiple host slots')
    result = {
        'schema': 1,
        'source': 'verified-host-install-state-v1',
        'installation': {
            'installation_id': installation['installation_id'],
            'record_id': installation['record_id'],
            'record_schema': installation['schema'],
            'operation': installation['operation'],
        },
        'selected_slot': recorded['expected_slot'],
        'booted_slot': booted[0] if booted else None,
        'slots': {
            slot: (None if row is None else {
                'generation': row['generation'],
                'root_partuuid': row['root_partuuid'],
            })
            for slot, row in slots.items()
        },
        'transitional_boot_bundle': recorded['foreign_boot_bundle'],
    }
    context.recheck()
    return result


class VerifiedState:
    """Anchored lifetime for a trusted caller; not an authorization token."""
    def __init__(self, bundle, fd, mount): self.bundle, self.fd, self.mount = bundle, fd, mount
    def close(self):
        if self.fd is not None: os.close(self.fd); self.fd = None
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def recheck(self):
        require(self.fd is not None, 'closed-inspection', 'descriptor closed')
        require(_mount(self.bundle) == self.mount, 'mount-changed', 'mount changed since inspection')
        fd = directory('/state')
        try:
            a, b = os.fstat(fd), os.fstat(self.fd)
            require((a.st_dev, a.st_ino) == (b.st_dev, b.st_ino), 'mount-changed', 'path replaced')
        finally: os.close(fd)
        require(not os.fstatvfs(self.fd).f_flag & os.ST_RDONLY, 'state-read-only', 'statvfs reports read-only')


def _inspect_live():
    bundle = load_configuration()
    mount = _mount(bundle)  # Do not inspect STATE children before this check.
    fd = directory('/state')
    context = VerifiedState(bundle, fd, mount)
    try:
        metadata(fd, 0, 0, 0o755)
        dev = os.fstat(fd).st_dev
        require(f'{os.major(dev)}:{os.minor(dev)}' == mount['device'], 'mount-changed', 'descriptor device mismatch')
        require(canonical(decode(read_at(fd, '.zog-state.json'))) == canonical(bundle['marker']), 'marker-mismatch', 'marker mismatch')
        accounts_match()
        child = os.open('host-discover', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            metadata(child, 970, 970, 0o700)
            for name in ('identity', 'trust', 'control', 'registries', 'health'):
                try:
                    sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=child)
                except FileNotFoundError:
                    if name == 'identity': continue  # Gate/host-identify handle absence.
                    raise
                try:
                    metadata(sub, 970, 970, 0o700)
                    require(os.fstat(sub).st_dev == dev, 'nested-mount', name)
                finally: os.close(sub)
        finally: os.close(child)
        context.recheck()
        return context
    except BaseException:
        context.close()
        raise


def inspect_live():
    """Public read-only boundary with stable diagnostic codes."""
    try:
        return _inspect_live()
    except StateError:
        raise
    except OSError as exc:
        code = {errno.ENOENT: 'required-path-missing', errno.EACCES: 'state-access-denied',
                errno.EPERM: 'state-access-denied', errno.ELOOP: 'unsafe-path',
                errno.ENOTDIR: 'unsafe-path', errno.EROFS: 'state-read-only',
                errno.EIO: 'state-io-failure'}.get(exc.errno, 'state-inspection-io')
        raise StateError(code, str(exc)) from exc
    except subprocess.SubprocessError as exc:
        raise StateError('topology-unavailable', str(exc)) from exc
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise StateError('inspection-data-invalid', str(exc)) from exc


def inspect_report():
    with inspect_live() as c:
        return dict(status='read-only-preconditions-verified', mount=c.mount,
                    installation_id=c.bundle['bootstrap']['installation_id'],
                    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                    write_probe='not-run', identity='not-read', control_authorized=False)
