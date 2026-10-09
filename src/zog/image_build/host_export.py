"""Offline host-install interchange. Does not install disks or execute payloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

from .engine import read_selection, SCHEMA as GENERATION_SCHEMA
from .errors import ImageBuildError
from .filesystem import digest, inventory, sync_tree, sync_directory, write_json
from .metadata import identity

SCHEMA = 1
OWNERSHIP = 'all-root-v1'
REQUIRED = {
    'pid1': 'usr/lib/systemd/systemd',
    'shell': 'usr/bin/bash',
    'python': 'usr/bin/python3',
    'network': 'usr/lib/systemd/systemd-networkd',
}
WRITABLE = {
    'state': {'partition': 'STATE', 'read_only': False},
    'applications': {'partition': 'APPLICATIONS', 'read_only': False},
    'host': {'partition': 'HOST-A-or-HOST-B', 'read_only': True},
    'runtime': {'paths': ['/run', '/tmp', '/dev', '/proc', '/sys'], 'persistent': False},
}


def fail(message):
    raise ImageBuildError(message)


def safe_name(name):
    """Restricted interchange metadata name (not a POSIX payload member)."""
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        fail('invalid artifact path')
    return safe_payload_name(name)


def safe_payload_name(name):
    """Validate a relative POSIX path; backslashes are literal filename bytes.

    Consumers must not unescape names or treat backslashes as separators.
    """
    if not isinstance(name, str) or not name or '\x00' in name:
        fail('invalid artifact path')
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
        fail('unsafe artifact path: ' + name)
    return name


def _secret_path(name):
    return (name.startswith(('root/', 'home/', 'var/lib/host-identify/',
                             'var/lib/host-discover/', 'var/lib/cloud/'))
            or name in ('etc/machine-id', 'var/lib/dbus/machine-id', 'etc/shadow', 'etc/gshadow')
            or (name.startswith('etc/ssh/ssh_host_') and not name.endswith('.pub')))


def records(root):
    """Explicit normalized ownership; no silently discarded xattrs or hard links."""
    result = inventory(root)
    for p in [Path(root), *(Path(root)/r['path'] for r in result)]:
        if os.listxattr(p, follow_symlinks=False):
            fail('extended attributes unsupported: ' + str(p))
        info = p.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            fail('hard links unsupported: ' + str(p))
    for r in result:
        safe_payload_name(r['path'])
        r.update(uid=0, gid=0)
    return result


def readiness(root_records, evidence):
    paths = {r['path']: r for r in root_records}
    checks = {k: bool(paths.get(p, {}).get('kind') == 'file'
                      and paths[p]['mode'] & 0o111) for k, p in REQUIRED.items()}
    return {
        'profile': 'foreign-kernel-host-v1',
        'installable': False,
        'presence_checks': checks,
        'blockers': ['missing executable: ' + REQUIRED[k] for k, v in checks.items() if not v] + [
            'Host service composition and writable-path mapping require acceptance',
            'Python SSL/SQLite and network operation have not been executed by this verifier',
            'Foreign initramfs root/state mounting compatibility requires acceptance',
            'First boot, enrollment and authenticated control operation remain untested'],
        'evidence_status': 'caller-supplied; preserved, not independently accepted',
        'acceptance_records': evidence['acceptance'],
    }


def validate_evidence(evidence):
    if (not isinstance(evidence, dict) or set(evidence) != {'packages', 'acceptance'}
            or not isinstance(evidence['packages'], list) or not isinstance(evidence['acceptance'], list)):
        fail('evidence requires packages and acceptance lists')
    # Arbitrary JSON records retained verbatim; these never grant readiness.
    return evidence


def boot_record(root_records, provenance):
    required = {'distribution', 'release', 'architecture', 'kernel_release', 'packages', 'acquisition'}
    if not isinstance(provenance, dict) or set(provenance) != required:
        fail('invalid foreign boot provenance fields')
    if any(not isinstance(provenance[k], str) or not provenance[k].strip()
           for k in required - {'packages'}):
        fail('empty foreign boot provenance')
    if provenance['distribution'] != 'amazon-linux' or provenance['release'] != '2023':
        fail('foreign boot profile requires Amazon Linux 2023')
    if not isinstance(provenance['packages'], list) or not provenance['packages'] or any(
            not isinstance(x, str) or not x for x in provenance['packages']):
        fail('foreign boot package versions required')
    release = safe_name(provenance['kernel_release'])
    if '/' in release:
        fail('kernel release must be one path component')
    paths = {r['path']: r for r in root_records}
    if any(paths.get(p, {}).get('kind') != 'file' for p in ('kernel', 'initramfs')):
        fail('foreign boot tree requires kernel and initramfs files')
    prefix = 'modules/' + release + '/'
    if not any(p.startswith(prefix) and r['kind'] == 'file' for p, r in paths.items()):
        fail('foreign boot tree lacks matching module directory')
    if any(p not in ('kernel', 'initramfs', 'modules', 'modules/'+release)
           and not p.startswith(prefix) for p in paths):
        fail('unexpected foreign boot bundle member')
    return {'origin': 'foreign', 'provenance': provenance, 'verified_boot': False,
            'compatibility': 'unverified; release directory is not kernel/initramfs compatibility proof'}


def _write_tar(root, output, entries):
    with tarfile.open(output, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for r in entries:
            member = tarfile.TarInfo(r['path'])
            member.mode = r['mode']; member.uid = member.gid = 0; member.mtime = 0
            if r['kind'] == 'directory':
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            elif r['kind'] == 'symlink':
                member.type = tarfile.SYMTYPE; member.linkname = r['target']
                archive.addfile(member)
            else:
                p = Path(root)/r['path']; member.size = p.stat().st_size
                with p.open('rb') as stream:
                    archive.addfile(member, stream)


def _tar_records(path):
    result = []; seen = set(); kinds = {}
    with tarfile.open(path, 'r:') as archive:
        for m in archive:
            name = safe_payload_name(m.name)
            if name in seen:
                fail('duplicate archive path')
            seen.add(name)
            if m.uid != 0 or m.gid != 0 or m.mode & ~0o1777 or m.pax_headers:
                fail('unsupported archive metadata')
            r = {'path': name, 'mode': m.mode, 'uid': 0, 'gid': 0}
            if m.isdir(): r['kind'] = 'directory'
            elif m.issym(): r.update(kind='symlink', target=m.linkname)
            elif m.isfile():
                h = hashlib.sha256()
                with archive.extractfile(m) as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
                r.update(kind='file', sha256=h.hexdigest())
            else: fail('unsupported archive member type')
            kinds[name] = r['kind']; result.append(r)
    for name in seen:
        for parent in PurePosixPath(name).parents:
            if str(parent) != '.' and kinds.get(str(parent)) != 'directory':
                fail('missing directory or symlink parent in archive')
    # Match inventory's component-wise path order (not full-string order).
    return sorted(result, key=lambda r: PurePosixPath(r['path']))


def _payload(root, destination):
    before = records(root)
    _write_tar(root, destination, before)
    if records(root) != before:
        fail('source changed during export')
    if _tar_records(destination) != before:
        fail('archive contents differ from source')
    return {'file': destination.name, 'sha256': digest(destination),
            'bytes': destination.stat().st_size, 'entries': before}


def export(generation, destination, evidence, *, boot_tree=None, boot_provenance=None):
    selected = read_selection(generation)
    evidence = validate_evidence(evidence)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink(): fail('export destination must be new')
    source_roots = [Path(generation).resolve()]
    if boot_tree is not None: source_roots.append(Path(boot_tree).resolve())
    if any(destination.resolve().is_relative_to(p) for p in source_roots):
        fail('export destination overlaps an input')
    if (boot_tree is None) != (boot_provenance is None): fail('boot tree and provenance required together')
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix='.host-export-', dir=destination.parent))
    try:
        root = _payload(selected.root, pending/'rootfs.tar')
        for r in root['entries']:
            if r['kind'] != 'directory' and _secret_path(r['path']):
                fail('host-specific state forbidden in reusable image: ' + r['path'])
        boot = None
        if boot_tree is not None:
            payload = _payload(boot_tree, pending/'boot.tar')
            boot = boot_record(payload['entries'], boot_provenance)
            if boot_provenance['architecture'] != selected.manifest['inputs']['architecture']:
                fail('boot and userspace architecture mismatch')
            boot['payload'] = payload
        if read_selection(generation).manifest != selected.manifest:
            fail('generation changed during export')
        manifest = {'schema': SCHEMA, 'kind': 'host-install-artifact',
                    'ownership_policy': OWNERSHIP, 'generation': selected.manifest,
                    'rootfs': root, 'boot_bundle': boot, 'evidence': evidence,
                    'storage_intent': WRITABLE, 'readiness': readiness(root['entries'], evidence),
                    'security': {'verified_boot': False, 'measured_boot': False,
                                 'public_release_reviewed': False}}
        manifest['artifact_id'] = identity(manifest)
        write_json(pending/'manifest.json', manifest)
        verify(pending, manifest['artifact_id'])
        sync_tree(pending)
        # Destination is caller-owned; no replacement of existing exports.
        if destination.exists(): fail('export destination appeared during publication')
        os.rename(pending, destination); sync_directory(destination.parent)
        return manifest
    finally:
        if pending.exists(): shutil.rmtree(pending)


def verify(directory, expected_id):
    """Hash verification requires a separately trusted ID; never extracts or executes."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir(): fail('artifact directory must be real')
    mpath = directory/'manifest.json'
    if mpath.is_symlink() or not mpath.is_file(): fail('manifest must be a regular file')
    try:
        m = json.loads(mpath.read_text())
        body = {k:v for k,v in m.items() if k != 'artifact_id'}
        if identity(body) != expected_id or m['artifact_id'] != expected_id:
            fail('artifact identity mismatch')
        if m['schema'] != SCHEMA or m['kind'] != 'host-install-artifact' or m['ownership_policy'] != OWNERSHIP:
            fail('unsupported host artifact schema or policy')
        g = m['generation']
        if (g['schema'] != GENERATION_SCHEMA or identity(g['inputs']) != g['generation']
                or g['kind'] != g['inputs']['kind']): fail('invalid source generation identity')
        if g['kind'] == 'toolchain' and (g.get('stage') != g['inputs'].get('stage')
                or g.get('self_hosted') != (g['inputs'].get('stage') == 2)):
            fail('invalid source toolchain stage')
        expected_files = {'manifest.json', 'rootfs.tar'}
        payloads = [m['rootfs']]
        if m['rootfs']['file'] != 'rootfs.tar': fail('invalid rootfs payload name')
        if m['boot_bundle'] is not None:
            b = m['boot_bundle']; payloads.append(b['payload']); expected_files.add('boot.tar')
            if b['payload']['file'] != 'boot.tar': fail('invalid boot payload name')
            if b != {**boot_record(b['payload']['entries'], b['provenance']), 'payload': b['payload']}:
                fail('invalid foreign boot claims')
            if b['provenance']['architecture'] != g['inputs']['architecture']: fail('architecture mismatch')
        if {p.name for p in directory.iterdir()} != expected_files: fail('unexpected artifact files')
        for payload in payloads:
            path = directory/safe_name(payload['file'])
            if (path.is_symlink() or not path.is_file() or path.stat().st_size != payload['bytes']
                    or digest(path) != payload['sha256']): fail('payload hash/size mismatch')
            if _tar_records(path) != payload['entries']: fail('payload inventory mismatch')
        original = [{k:v for k,v in r.items() if k not in ('uid','gid')} for r in m['rootfs']['entries']]
        if original != g['outputs']: fail('payload differs from generation inventory')
        if any(r['kind'] != 'directory' and _secret_path(r['path']) for r in original):
            fail('host-specific state in artifact')
        e = validate_evidence(m['evidence'])
        if m['readiness'] != readiness(m['rootfs']['entries'], e) or m['storage_intent'] != WRITABLE:
            fail('invalid readiness or storage claims')
        if m['security'] != {'verified_boot': False, 'measured_boot': False, 'public_release_reviewed': False}:
            fail('unsupported security claim')
        return m
    except (KeyError, TypeError, ValueError, tarfile.TarError, OSError) as error:
        raise ImageBuildError('invalid host artifact: ' + str(error)) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    p = sub.add_parser('export'); p.add_argument('generation'); p.add_argument('destination')
    p.add_argument('--evidence', required=True); p.add_argument('--boot-tree'); p.add_argument('--boot-provenance')
    p = sub.add_parser('verify'); p.add_argument('directory'); p.add_argument('--expected-id', required=True)
    args = parser.parse_args()
    try:
        if args.operation == 'verify': result = verify(args.directory, args.expected_id)
        else:
            result = export(args.generation, args.destination, json.loads(Path(args.evidence).read_text()),
                            boot_tree=args.boot_tree, boot_provenance=json.loads(Path(args.boot_provenance).read_text()) if args.boot_provenance else None)
        print(json.dumps({'artifact_id':result['artifact_id'], 'readiness':result['readiness']}, indent=2))
    except (ImageBuildError, OSError, ValueError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__': main()
