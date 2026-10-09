"""Bounded ZIP handling shared by migration and fast GitHub retrieval."""
import base64
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile
from .core import ShareError, safe_path, repository_path
from .workspace import ignored, guard_secret, manifest, object_hash

MAXIMUM_ARCHIVE = 64 * 1024 * 1024
MAXIMUM_EXPANDED = 128 * 1024 * 1024


def zip_files(archive, source_root, token='', exclude=False):
    """Return exact source bytes, modes and explicit exclusions; never extract paths directly."""
    if isinstance(archive, (str, Path)) and Path(archive).stat().st_size > MAXIMUM_ARCHIVE:
        raise ShareError('unsupported', 'ZIP exceeds 64 MiB.')
    if source_root != '.':
        safe_path(source_root)
    prefix = '' if source_root == '.' else source_root.rstrip('/') + '/'
    files, excluded, seen, expanded = {}, [], set(), 0
    try:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > 20000:
                raise ShareError('unsupported', 'ZIP contains too many entries.')
            for entry in entries:
                name = entry.filename.rstrip('/')
                # Validate every archive member, including members outside the selected root.
                parts = name.split('/')
                if not name or any(p in ('', '.', '..') for p in parts) or '\\' in name or '\0' in name or name.startswith('/'):
                    raise ShareError('unsafe-tree', 'ZIP contains an unsafe path.')
                if entry.filename in seen:
                    raise ShareError('unsafe-tree', 'ZIP contains duplicate paths.')
                seen.add(entry.filename)
                expanded += entry.file_size
                if expanded > MAXIMUM_EXPANDED or entry.flag_bits & 1:
                    raise ShareError('unsupported', 'ZIP exceeds the size limit or is encrypted.')
                if entry.is_dir() or not entry.filename.startswith(prefix):
                    continue
                relative = entry.filename[len(prefix):]
                if exclude and ignored(relative):
                    excluded.append(relative)
                    continue
                safe_path(relative)
                mode = entry.external_attr >> 16 if entry.create_system == 3 else 0
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFLNK):
                    raise ShareError('unsupported', 'ZIP contains a special file.')
                content = package.read(entry)
                if exclude:
                    guard_secret(relative.encode() + b'\0' + content, token)
                files[relative] = {'mode': '120000' if kind == stat.S_IFLNK else '100755' if mode & 0o111 else '100644',
                                   'sha': object_hash('blob', content), 'content': base64.b64encode(content).decode()}
    except (zipfile.BadZipFile, RuntimeError, EOFError):
        raise ShareError('unsafe-tree', 'ZIP is invalid or cannot be decoded safely.') from None
    if not files:
        raise ShareError('configuration', 'Selected ZIP source root contains no source files.')
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ShareError('unsafe-tree', 'ZIP has conflicting file and directory paths.')
    return files, sorted(excluded)


def write_files(files, destination):
    root = Path(destination)
    links = []
    for name, item in files.items():
        path = root.joinpath(*safe_path(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        content = base64.b64decode(item['content'])
        if item['mode'] == '120000':
            try:
                target = content.decode('utf-8')
            except UnicodeError:
                raise ShareError('unsafe-tree', 'Non-UTF-8 symbolic link.') from None
            if not target or os.path.isabs(target) or '\\' in target or '\0' in target:
                raise ShareError('unsafe-tree', 'Unsafe symbolic link target.')
            links.append((path, target))
        else:
            path.write_bytes(content)
            path.chmod(0o755 if item['mode'] == '100755' else 0o644)
    for path, target in links:
        path.symlink_to(target)
    for path, _ in links:
        try:
            path.resolve().relative_to(root.resolve())
        except (ValueError, RuntimeError):
            raise ShareError('unsafe-tree', 'Symbolic link escapes source tree or forms a cycle.') from None


def install_snapshot(files, destination, metadata):
    from .workspace import save_json
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise ShareError('conflict', 'Destination exists; choose a fresh directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.version-share-', dir=destination.parent))
    try:
        write_files(files, staging)
        (staging / '.version-share').mkdir()
        save_json(staging / '.version-share/baseline.json', metadata)
        destination.mkdir()
        try:
            os.replace(staging, destination)
        except BaseException:
            destination.rmdir()
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def preview_zip(archive, source_root, token=''):
    files, excluded = zip_files(archive, source_root, token, exclude=True)
    return {'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            'source_root': source_root, 'files': [{'path': name, 'mode': item['mode'],
            'bytes': len(base64.b64decode(item['content']))} for name, item in sorted(files.items())],
            'excluded': excluded}


def import_zip(client, owner, program, archive, destination, source_root, reference=None):
    from .publication import remote_manifest
    from .workspace import save_json
    if os.path.lexists(destination):
        raise ShareError('conflict', 'Destination exists; choose a fresh directory.')
    files, excluded = zip_files(archive, source_root, client._token, exclude=True)
    path = repository_path(owner, program)
    repository = client.request('GET', path)
    reference = reference or repository['default_branch']
    commit, baseline_files = remote_manifest(client, path, reference)
    metadata = {'schema': 1, 'repository': repository['full_name'], 'repository_id': repository['id'],
                'requested_reference': reference, 'commit': commit, 'destination': str(Path(destination).absolute()),
                'files': baseline_files}
    install_snapshot(files, destination, metadata)
    provenance = {'schema': 1, 'archive_name': Path(archive).name,
                  'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
                  'source_root': source_root, 'excluded': excluded, 'source_files': manifest(files)}
    save_json(Path(destination) / '.version-share/import.json', provenance)
    return {'repository': metadata['repository'], 'baseline': commit, 'source_root': source_root,
            'file_count': len(files), 'excluded': excluded, 'archive_sha256': provenance['archive_sha256'],
            'destination': metadata['destination']}
