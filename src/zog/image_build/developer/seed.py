"""Amazon Linux distribution seed assembly; RPM is confined to this developer module."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from .catalogue import load_catalogue, host_plan
from .host import detect
from ..errors import ImageBuildError
from ..filesystem import inventory, digest, ensure_directory, sync_tree, write_json, discard_staging
from ..metadata import identity

EXCLUDED = ('/usr/share/doc/', '/usr/share/man/', '/usr/share/info/', '/usr/share/locale/', '/usr/lib/.build-id/')


def command(*arguments):
    return subprocess.check_output(arguments, text=True).strip()


def discover(catalogue):
    profile = detect()
    if profile['id'] != 'amazon-linux-2023':
        raise ImageBuildError('seed file discovery currently supports Amazon Linux 2023 only')
    plan = host_plan(load_catalogue(catalogue), profile['id'])
    # Full installed RPM dependency closure, not only ELF DT_NEEDED entries:
    # interpreters, compiler helpers and data files also matter.
    selected = set(plan['packages']) | {'file', 'bzip2'}
    command('rpm', '-q', *sorted(selected))
    dependencies = command('dnf', '-q', 'repoquery', '--installed', '--requires', '--resolve',
                           '--recursive', '--qf', '%{name}', *sorted(selected)).splitlines()
    packages = sorted(selected | set(dependencies))
    versions = command('rpm', '-q', '--qf', '%{NAME}|%{EPOCHNUM}:%{VERSION}-%{RELEASE}|%{ARCH}\n', *packages).splitlines()
    files = {}
    omitted = []
    for package in packages:
        for name in command('rpm', '-ql', package).splitlines():
            if not name.startswith(('/usr/', '/bin/', '/sbin/', '/lib/', '/lib64/')) or name.startswith(EXCLUDED):
                continue
            path = Path(name)
            if not path.exists():
                omitted.append({'path': name, 'package': package, 'reason': 'absent or dangling RPM entry'})
                continue
            if path.is_symlink() and not str(path.resolve()).startswith('/usr/'):
                omitted.append({'path': name, 'package': package, 'reason': 'link to excluded host configuration', 'target': str(path.resolve())})
                continue
            files.setdefault(name, []).append('rpm:' + package)
    for name in ('/bin', '/sbin', '/lib', '/lib64', '/usr/bin/yacc'):
        files.setdefault(name, []).append('required layout or command alias')
    return dict(schema=1, host=profile, plan=plan, packages=versions, files=files, omitted=omitted,
                exclusions=list(EXCLUDED), policy='installed-rpm-usr-closure-v1')


def assemble_files(files, destination, host_root=Path('/'), *, user_id=21001, group_id=21001):
    """Directories are shallow: never recursively import arbitrary host trees."""
    host_root = Path(host_root).resolve()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    queue = list(files)
    records = {}
    while queue:
        name = queue.pop()
        if name in records:
            continue
        if not name.startswith('/') or '..' in Path(name).parts:
            raise ImageBuildError(f'unsafe host seed path: {name}')
        source = host_root / name.lstrip('/')
        if not source.exists() and not source.is_symlink():
            raise ImageBuildError(f'missing seed input: {name}')
        canonical_parent = source.parent.resolve().relative_to(host_root)
        target = destination / canonical_parent / source.name
        # Only selected /usr files, root layout aliases and alternatives may be copied.
        canonical_name = '/' + (canonical_parent / source.name).as_posix()
        if not (canonical_name.startswith('/usr/') or canonical_name.startswith('/etc/alternatives/')
                or canonical_name in ('/bin', '/sbin', '/lib', '/lib64')):
            raise ImageBuildError(f'host seed input outside allowed trees: {canonical_name}')
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = source.lstat().st_mode
        reason = files.get(name, ['symlink-target'])
        record = dict(path=canonical_name, reasons=reason, original_mode=stat.S_IMODE(mode))
        if stat.S_ISLNK(mode):
            resolved = source.resolve(strict=True).relative_to(host_root)
            link = '/' + resolved.as_posix()
            if target.is_symlink():
                if str(target.readlink()) != link:
                    raise ImageBuildError('conflicting seed symlink')
            elif not target.exists():
                target.symlink_to(link)
            else:
                raise ImageBuildError('seed alias conflicts with copied directory')
            queue.append(link)
            record.update(kind='symlink', target=link)
        elif stat.S_ISDIR(mode):
            target.mkdir(exist_ok=True)
            record.update(kind='directory')
        elif stat.S_ISREG(mode):
            before = digest(source)
            shutil.copyfile(source, target)
            target.chmod(stat.S_IMODE(mode) & 0o777)
            if before != digest(source) or before != digest(target):
                raise ImageBuildError(f'host input changed while copied: {name}')
            record.update(kind='file', sha256=before)
        else:
            raise ImageBuildError(f'unsupported host seed file: {name}')
        records[name] = record
    for name in ('etc', 'tmp', 'run', 'image-build/source', 'image-build/output'):
        (destination / name).mkdir(parents=True, exist_ok=True)
    # No host users, machine identity, credentials or package database are copied.
    (destination / 'etc/passwd').write_text(f'root:x:0:0:root:/root:/bin/bash\nbuilder:x:{user_id}:{group_id}:builder:/tmp:/bin/bash\n')
    (destination / 'etc/group').write_text(f'root:x:0:\nbuilder:x:{group_id}:\n')
    (destination / 'etc/nsswitch.conf').write_text('passwd: files\ngroup: files\nhosts: files\n')
    for name in ('passwd', 'group', 'nsswitch.conf'):
        records['/etc/' + name] = {'kind': 'generated', 'reasons': ['minimal seed configuration'],
                                   'sha256': digest(destination / 'etc' / name)}
    return records


def prepare(catalogue, directory, *, user_id=21001, group_id=21001):
    if any(type(v) is not int or not 0 < v < 2**31 for v in (user_id, group_id)):
        raise ImageBuildError("seed requires nonzero execution UID/GID")
    execution_identity = dict(user_id=user_id, group_id=group_id)
    directory = Path(directory)
    ensure_directory(directory)
    with (directory / 'assembly.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prepared = directory / 'prepared.json'
        if prepared.exists():
            saved = json.loads(prepared.read_text())
            if saved.get('execution_identity') != execution_identity or saved['catalogue'] != inventory(catalogue) or saved['root'] != inventory(directory / 'root'):
                raise ImageBuildError('recorded seed inputs changed')
            return saved
        intent = directory / 'intent.json'
        if intent.exists():
            saved = json.loads(intent.read_text())
            if saved.get('execution_identity') != execution_identity or saved['catalogue'] != inventory(catalogue):
                raise ImageBuildError('seed catalogue changed; preserve attempt and choose a new directory')
        else:
            saved = {'catalogue': inventory(catalogue), 'discovery': discover(catalogue), 'execution_identity': execution_identity}
            write_json(intent, saved)
        # Incomplete assembly has never been registered with the controller.
        if (directory / 'controller-resources.json').exists():
            raise ImageBuildError('unrecorded seed with controller resources')
        if (directory / 'root').exists():
            discard_staging(directory / 'root')
        provenance = assemble_files(saved['discovery']['files'], directory / 'root', user_id=user_id, group_id=group_id)
        current = command('rpm', '-q', '--qf', '%{NAME}|%{EPOCHNUM}:%{VERSION}-%{RELEASE}|%{ARCH}\n',
                          *[x.split('|')[0] for x in saved['discovery']['packages']]).splitlines()
        if sorted(current) != sorted(saved['discovery']['packages']):
            raise ImageBuildError('installed package versions changed during seed assembly')
        sync_tree(directory / 'root')
        saved.update(root=inventory(directory / 'root'), provenance=provenance)
        write_json(prepared, saved)
        return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.package_dir, args.directory)
    print(json.dumps({'root': str(args.directory / 'root'), 'identity': identity(result),
                      'files': len(result['root']), 'status': 'assembled-unverified'}))


if __name__ == '__main__':
    main()
