#!/usr/bin/env python3
"""Explicit source frontend installation. No service startup, migrations or npm on requests."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r'[a-f0-9]{32}')


class InstallError(Exception):
    pass


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise InstallError(message)


def regular_files(root):
    require(root.is_dir() and not root.is_symlink(), f'Expected a regular directory: {root}')
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), f'Symbolic links are not permitted: {path}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
        else:
            require(path.is_dir(), f'Nonregular file: {path}')
    return result


def sync_directory(path):
    descriptor = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_durably(path):
    path.unlink(missing_ok=True)
    sync_directory(path.parent)


def atomic_json(path, value):
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    with temporary.open('x') as stream:
        os.chmod(temporary, 0o644)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def load(path):
    require(path.is_file() and not path.is_symlink(), f'Missing regular metadata: {path}')
    return json.loads(path.read_text())


def named_directory(parent, identifier):
    require(bool(IDENTIFIER.fullmatch(identifier)), 'Invalid operation/release ID (expected 32 hex characters)')
    path = parent / identifier
    require(not path.is_symlink(), f'Unexpected symbolic link: {path}')
    return path


def validate_root(path):
    require(os.geteuid() == 0, 'Run the orchestrator as root; npm runs under the explicitly selected unprivileged build user.')
    require(path.is_absolute() and '..' not in path.parts, 'Application root must be an absolute path without ..')
    require(not path.is_relative_to(SOURCE), 'Application root must be outside the maintained source checkout')
    for item in [*reversed(path.parents), path]:
        require(not item.is_symlink(), f'Symlink in application-root path: {item}')
        if item.exists():
            require(item.stat().st_uid == 0 and not item.stat().st_mode & 0o022,
                    f'Application-root ancestors must be root-owned and not group/world writable: {item}')
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    return path


@contextlib.contextmanager
def locked(root):
    lock = root / '.frontend.lock'
    require(not lock.is_symlink(), 'Unexpected lock symlink')
    with lock.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError('Another frontend operation is running; retry after it finishes.') from None
        yield


def identity(name):
    try:
        user = pwd.getpwnam(name)
    except KeyError:
        raise InstallError(f'Missing local identity {name}; create a dedicated service account first.') from None
    require(user.pw_uid != 0, 'Build/runtime identities must be unprivileged')
    return user


def clean_environment(workspace, node):
    # No VITE_*, npm user configuration, cloud keys, station settings or login secrets.
    env = {'PATH': str(Path(node).parent) + ':/usr/bin:/bin',
           'HOME': str(workspace / 'home'), 'TMPDIR': str(workspace / 'tmp'),
           'npm_config_cache': str(workspace / 'npm-cache'),
           'npm_config_userconfig': str(workspace.parent / 'user.npmrc'),
           'npm_config_globalconfig': str(workspace.parent / 'global.npmrc'),
           'npm_config_audit': 'false', 'npm_config_fund': 'false', 'CI': 'true',
           'LANG': 'C.UTF-8'}
    # Transport settings only; never record their possibly credential-bearing values.
    for key in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy',
                'NPM_CONFIG_PROXY', 'NPM_CONFIG_HTTPS_PROXY', 'NPM_CONFIG_HTTP_PROXY',
                'npm_config_proxy', 'npm_config_https_proxy', 'npm_config_http_proxy',
                'NODE_EXTRA_CA_CERTS', 'SSL_CERT_FILE', 'NPM_CONFIG_CAFILE', 'npm_config_cafile'):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def execute(arguments, record, stage, cwd=None, log_name='command.log'):
    workspace = stage / 'work'
    env = clean_environment(workspace, record['node_path'])
    with (stage / log_name).open('ab') as log:
        os.chmod(stage / log_name, 0o600)
        result = subprocess.run(arguments, cwd=cwd or workspace / 'source/frontend',
                                env=env, stdout=log, stderr=subprocess.STDOUT,
                                user=record['build_uid'], group=record['build_gid'], extra_groups=[],
                                umask=0o022)
    require(result.returncode == 0, f'{arguments[0]} failed ({result.returncode}); inspect {stage / log_name}. Active frontend unchanged.')


def source_snapshot(source, revision):
    require(bool(re.fullmatch('[a-f0-9]{40}', revision)), 'An exact 40-character source commit is required')
    baseline = load(source / '.version-share/baseline.json')
    require(baseline['commit'] == revision and baseline['repository'] == 'zog144/station-access',
            'Source revision/repository differs from version-share checkout; retrieve the exact source first.')
    files = {}
    for name, entry in baseline['files'].items():
        # Curated build source, maintained verification/serving implementation and provenance.
        if not (name.startswith('frontend/') or name in (
                'LICENSE', 'pyproject.toml',
                'src/zog/station_access/web.py',
                'tools/check-frontend-release.py', 'tools/frontend-probe.py', 'tools/frontend-install.py')):
            continue
        require(entry['mode'] == '100644' or entry['mode'] == '100755', f'Nonregular source: {name}')
        path = source / name
        require(path.is_file() and not path.is_symlink(), f'Missing regular source file: {name}')
        data = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(blob == entry['sha'], f'Source differs from commit: {name}; publish/retrieve a clean revision before preparing.')
        require('/node_modules/' not in name and '/dist/' not in name, 'Generated frontend content must not be tracked')
        files[name] = digest(path)
    require('frontend/toolchain.json' in files and 'tools/frontend-probe.py' in files,
            'Source does not support the four-stage installer')
    actual = regular_files(source / 'frontend')
    require(set(actual) == {name.removeprefix('frontend/') for name in files if name.startswith('frontend/')},
            'Use a fresh frontend checkout without untracked files, dist, node_modules or compiler caches.')
    return files


def check_snapshot(stage, record):
    for name, expected in record['source_files'].items():
        path = stage / 'work/source' / name
        require(path.is_file() and not path.is_symlink() and digest(path) == expected,
                f'Prepared source changed: {name}; discard this operation and prepare again.')


def prepare(root, args):
    source = Path(args.source).resolve()
    require(sys.version_info >= (3, 12), 'Python 3.12 or newer is required')
    for module in ('django', 'waitress'):
        require(importlib.util.find_spec(module) is not None, f'Missing Python prerequisite {module}; install it into the orchestrator interpreter before preparing.')
    require(not root.is_relative_to(source) and not source.is_relative_to(root), 'Source and application directories must be separate')
    files = source_snapshot(source, args.source_revision)
    build_user, runtime_user = identity(args.build_user), identity(args.runtime_user)
    require(build_user.pw_uid != runtime_user.pw_uid and build_user.pw_gid != runtime_user.pw_gid
            and build_user.pw_gid != 0 and runtime_user.pw_gid != 0,
            'Build and runtime identities must have different unprivileged UIDs and primary groups')
    toolchain = load(source / 'frontend/toolchain.json')
    tools = {}
    for key in ('node', 'npm'):
        executable = Path(getattr(args, key))
        require(executable.is_absolute() and executable.is_file() and os.access(executable, os.X_OK),
                f'Missing {key}; install pinned {key} {toolchain[key]} and supply its absolute executable path.')
        tools[key] = str(executable)
    identifier = uuid.uuid4().hex
    stage = root / 'staging' / identifier
    stage.mkdir(parents=True, mode=0o755)
    for name in ('user.npmrc', 'global.npmrc'):
        (stage / name).write_text('')
    workspace = stage / 'work'
    workspace.mkdir()
    for name in ('home', 'tmp', 'npm-cache', 'source'):
        (workspace / name).mkdir()
    for name in files:
        target = workspace / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    for path in [workspace, *workspace.rglob('*')]:
        os.chown(path, build_user.pw_uid, build_user.pw_gid)
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    workspace.chmod(0o700)
    record = {'schema': 1, 'id': identifier, 'phase': 'prepared', 'source_revision': args.source_revision,
              'source_files': files, 'lockfile_sha256': files['frontend/package-lock.json'],
              'node_path': tools['node'], 'npm_path': tools['npm'], 'toolchain': toolchain,
              'toolchain_files': {key: digest(Path(value)) for key, value in tools.items()},
              'build_uid': build_user.pw_uid, 'build_gid': build_user.pw_gid,
              'runtime_uid': runtime_user.pw_uid, 'checks': []}
    atomic_json(stage / 'operation.json', record)
    check_toolchain(record, stage)
    print(json.dumps({'operation': identifier, 'phase': 'prepared', 'path': str(stage)}))
    return identifier


def check_toolchain(record, stage):
    for key in ('node', 'npm'):
        require(Path(record[key + '_path']).is_file(), f'Missing pinned {key} executable; restore the prepared toolchain.')
        if 'toolchain_files' in record:
            require(digest(Path(record[key + '_path'])) == record['toolchain_files'][key], f'Prepared {key} executable changed; prepare again with the reviewed toolchain.')
        result = subprocess.run([record[key + '_path'], '--version'],
                                cwd=stage / 'work', env=clean_environment(stage / 'work', record['node_path']),
                                user=record['build_uid'], group=record['build_gid'], extra_groups=[],
                                capture_output=True, text=True)
        require(result.returncode == 0 and result.stdout.strip().removeprefix('v') == record['toolchain'][key],
                f'Required {key} {record["toolchain"][key]} unavailable or wrong version; no automatic toolchain substitution.')


def get_operation(root, identifier, phase):
    stage = named_directory(root / 'staging', identifier)
    record = load(stage / 'operation.json')
    require(record['phase'] == phase, f'Operation must be {phase}; current phase is {record["phase"]}')
    check_snapshot(stage, record)
    check_toolchain(record, stage)
    return stage, record


def build(root, identifier):
    stage, record = get_operation(root, identifier, 'prepared')
    execute([record['npm_path'], 'ci', '--include=dev'], record, stage, log_name='dependencies.log')
    check_snapshot(stage, record)
    execute([record['npm_path'], 'run', 'build'], record, stage, log_name='build.log')
    check_snapshot(stage, record)
    record['phase'] = 'built'
    atomic_json(stage / 'operation.json', record)


def output_inventory(dist):
    files = regular_files(dist)
    manifest = load(dist / 'frontend-build.json')
    require(manifest['mode'] == manifest['node_env'] == 'production', 'Frontend is not a production build')
    require(files == dict(manifest['outputs'], **{'frontend-build.json': digest(dist / 'frontend-build.json')}),
            'Incomplete or changed frontend output inventory')
    require(manifest['licenses'] in files and 'index.html' in files, 'Missing entry point or license asset')
    return files


def verify(root, identifier):
    stage, record = get_operation(root, identifier, 'built')
    execute([record['npm_path'], 'test'], record, stage, log_name='frontend-tests.log')
    execute([record['npm_path'], 'run', 'test:licenses'], record, stage, log_name='license-tests.log')
    source = stage / 'work/source'
    execute([sys.executable, str(source / 'tools/check-frontend-release.py')], record, stage, log_name='output-check.log')
    check_snapshot(stage, record)
    dist = source / 'frontend/dist'
    files = output_inventory(dist)
    # Probe source is from the exact prepared revision; the orchestration Python needs Django/Waitress.
    execute([sys.executable, str(source / 'tools/frontend-probe.py'), '--directory', str(dist)],
            record, stage, log_name='serving-check.log')
    check_snapshot(stage, record)
    require(output_inventory(dist) == files, 'Output changed during verification')
    releases = root / 'releases'
    releases.mkdir(exist_ok=True)
    temporary = releases / ('.install-' + identifier)
    destination = named_directory(releases, identifier)
    require(not temporary.exists() and not destination.exists(), 'Release already exists; prepare a new operation')
    temporary.mkdir()
    try:
        shutil.copytree(dist, temporary / 'dist', symlinks=True)
        require(output_inventory(temporary / 'dist') == files, 'Output changed while copying into installation')
        manifest = {'schema': 1, 'id': identifier, 'source_revision': record['source_revision'],
                    'source_files': record['source_files'], 'lockfile_sha256': record['lockfile_sha256'],
                    'toolchain': record['toolchain'], 'toolchain_files': record['toolchain_files'], 'runtime_uid': record['runtime_uid'],
                    'configuration': {'mode': 'production', 'node_env': 'production'},
                    'outputs': files, 'notice_sha256': files[load(dist / 'frontend-build.json')['licenses']],
                    'serving_contract': 'station-frontend-selection-v1',
                    'checks': ['npm-ci-include-dev', 'npm-test', 'npm-test-licenses', 'production-output-and-notices', 'django-waitress-static-http']}
        atomic_json(temporary / 'installation.json', manifest)
        for path in [*temporary.rglob('*'), temporary]:
            os.chown(path, 0, 0)
            os.chmod(path, 0o555 if path.is_dir() else 0o444)
            if path.is_file():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
        for path in sorted([temporary, *[p for p in temporary.rglob('*') if p.is_dir()]], key=lambda p: len(p.parts), reverse=True):
            sync_directory(path)
        os.rename(temporary, destination)
        sync_directory(releases)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    record['phase'] = 'verified'
    atomic_json(stage / 'operation.json', record)
    print(json.dumps({'release': identifier, 'path': str(destination), 'activated': False}))


def validate_release(root, identifier):
    directory = named_directory(root / 'releases', identifier)
    manifest = load(directory / 'installation.json')
    require(manifest['id'] == identifier and manifest['serving_contract'] == 'station-frontend-selection-v1', 'Incompatible release manifest')
    require(output_inventory(directory / 'dist') == manifest['outputs'], 'Installed output hashes differ; activation refused')
    for path in [root, root / 'releases', directory, *directory.rglob('*')]:
        require(not path.is_symlink() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022,
                f'Installed output must be root-owned and not writable by runtime/build identities: {path}')
    return manifest


def check_http(url, manifest, directory, previous=None):
    # Use maintained probe code from this installer, never arbitrary installed executable hooks.
    command = [sys.executable, str(SOURCE / 'tools/frontend-probe.py'), '--url', url,
               '--directory', str(directory)]
    if previous:
        command += ['--retained-directory', str(previous)]
    subprocess.run(command, check=True, timeout=90)


def restore_selection(root, previous):
    if previous is None:
        remove_durably(root / 'selection.json')
    else:
        atomic_json(root / 'selection.json', previous)


def recover(root):
    transaction = root / 'activation.json'
    require(transaction.exists(), 'No interrupted activation to recover')
    previous = load(transaction)['previous']
    if previous:
        for identifier in previous['retained']:
            validate_release(root, identifier)
    restore_selection(root, previous)
    remove_durably(transaction)
    print('Restored the selection recorded before interrupted activation; verify the service before another activation.')


def activate(root, identifier, health_url):
    require(not (root / 'activation.json').exists(), 'Interrupted activation exists; run recover and inspect service health first.')
    candidate = validate_release(root, identifier)
    selection = root / 'selection.json'
    previous = load(selection) if selection.exists() else None
    retained = list(dict.fromkeys([identifier, *(previous['retained'] if previous else [])]))
    # An old browser URL must never silently start identifying different bytes.
    asset_hashes = {}
    for release in retained:
        manifest = validate_release(root, release)
        for name, sha in manifest['outputs'].items():
            if name.startswith('assets/'):
                require(name not in asset_hashes or asset_hashes[name] == sha, f'Asset name collision across releases: {name}')
                asset_hashes[name] = sha
    atomic_json(root / 'activation.json', {'previous': previous, 'candidate': identifier})
    atomic_json(selection, {'schema': 1, 'active': identifier, 'retained': retained})
    try:
        check_http(health_url, candidate, root / 'releases' / identifier / 'dist',
                   root / 'releases' / previous['active'] / 'dist' if previous else None)
    except BaseException as error:
        restore_selection(root, previous)
        remove_durably(root / 'activation.json')
        raise InstallError('Activation health check failed; previous selection restored. Inspect the serving service. ' + type(error).__name__) from None
    remove_durably(root / 'activation.json')
    atomic_json(root / 'last-activation.json', {'active': identifier, 'previous': previous['active'] if previous else None,
                                             'checked_at': int(time.time()), 'http_check': 'passed'})
    print(json.dumps({'active': identifier, 'retained': retained, 'http_check': 'passed'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-root', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'install'):
        command = commands.add_parser(name, help='Prepare only' if name == 'prepare' else 'Prepare, build and verify; no activation')
        command.add_argument('--source', required=True)
        command.add_argument('--source-revision', required=True)
        command.add_argument('--build-user', required=True)
        command.add_argument('--runtime-user', required=True)
        command.add_argument('--node', required=True)
        command.add_argument('--npm', required=True)
    for name in ('build', 'verify'):
        commands.add_parser(name).add_argument('--operation', required=True)
    command = commands.add_parser('activate')
    command.add_argument('--release', required=True)
    command.add_argument('--health-url', required=True)
    commands.add_parser('recover')
    commands.add_parser('discard').add_argument('--operation', required=True)
    args = parser.parse_args()
    try:
        root = validate_root(args.application_root)
        with locked(root):
            if args.command in ('prepare', 'install'):
                identifier = prepare(root, args)
                if args.command == 'install':
                    build(root, identifier)
                    verify(root, identifier)
            elif args.command == 'build':
                build(root, args.operation)
            elif args.command == 'verify':
                verify(root, args.operation)
            elif args.command == 'activate':
                activate(root, args.release, args.health_url)
            elif args.command == 'recover':
                recover(root)
            elif args.command == 'discard':
                directory = named_directory(root / 'staging', args.operation)
                load(directory / 'operation.json')
                shutil.rmtree(directory)
                print('Removed only the selected staging operation; installed and active assets retained.')
    except (InstallError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'Frontend installation failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
