"""Versioned application mount policy; image-build owns published software."""
from pathlib import Path, PurePosixPath
from .errors import RuntimeOperationError

VERSION = 'zog-mounts-v1'
SOFTWARE = ('/usr', '/bin', '/sbin', '/lib', '/lib64', '/boot', '/opt')
RESERVED = ('/proc', '/sys', '/dev', '/run/zog-workspace', '/tmp/.X11-unix')


def within(path, parent):
    return path == parent or path.startswith(parent + '/')


def destination(value):
    if (not isinstance(value, str) or not value.startswith('/') or
        str(PurePosixPath(value)) != value or value.startswith('//') or
        '..' in PurePosixPath(value).parts or '\x00' in value):
        raise RuntimeOperationError(f'invalid mount destination: {value!r}')
    return value


def resolved_destination(root, value):
    """Resolve links inside the selected root, including absolute guest links."""
    pending = list(PurePosixPath(value).parts[1:]); parts = []; links = 0
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            if not parts:
                raise RuntimeOperationError('mount destination escapes generation')
            parts.pop(); continue
        candidate = Path(root).joinpath(*parts, part)
        if candidate.is_symlink():
            links += 1
            if links > 40:
                raise RuntimeOperationError('mount destination has cyclic links')
            target = candidate.readlink()
            if target.is_absolute():
                parts = []
            pending = list(target.parts[1:] if target.is_absolute() else target.parts) + pending
        else:
            parts.append(part)
    return '/' + '/'.join(parts)


def validate(root, mounts, command=(), *, require_targets=False):
    """Validate ordinary data mounts separately from trusted controller mounts."""
    targets = []
    for source, target in mounts:
        destination(target)
        if root is not None and Path(source).is_absolute() and Path(source).resolve() != Path(source).absolute():
            raise RuntimeOperationError(f'application data source is redirected: {source}')
        resolved = resolved_destination(root, target) if root is not None else target
        for candidate in (target, resolved):
            if candidate in ('/', '/etc', '/var', '/run') or any(within(candidate, p) or within(p, candidate) for p in SOFTWARE + RESERVED):
                raise RuntimeOperationError(f'writable mount overlaps software or controller path: {target}')
        if resolved != target:
            raise RuntimeOperationError(f'mount destination is redirected: {target} -> {resolved}')
        if any(within(target, old) or within(old, target) for old in targets):
            raise RuntimeOperationError(f'overlapping writable mounts: {target}')
        targets.append(target)
        if require_targets and not Path(root).joinpath(target.lstrip('/')).is_dir():
            raise RuntimeOperationError(f'mount target must be supplied by image-build: {target}')
    if command:
        executable = resolved_destination(root, command[0]) if root is not None else command[0]
        if any(within(executable, target) for target in targets):
            raise RuntimeOperationError('executable is in writable application data; publish software in a generation and explicitly upgrade')


def validate_workspace_targets(root):
    for target in ('/run/zog-workspace', '/tmp/.X11-unix'):
        if resolved_destination(root, target) != target or not Path(root).joinpath(target.lstrip('/')).is_dir():
            raise RuntimeOperationError(f'workspace mount target must be supplied without redirection by image-build: {target}')


def inventory(root, mounts, *, persistent_storage_id=None, workspace_binding=None):
    workspace = workspace_binding or {}
    entries = []
    for source, target in mounts:
        managed = str(source) in (workspace.get('access_directory'), workspace.get('x11_directory'))
        entries.append(dict(source=str(source), destination=target, access='read-write',
            kind='workspace' if managed else 'application-data',
            lifetime='desktop-incarnation' if managed else ('persistent' if persistent_storage_id else 'runtime'),
            owner_id=workspace.get('incarnation') if managed else (persistent_storage_id or Path(source).parent.parent.name),
            name=Path(source).name))
    if workspace.get('role') == 'client':
        for source, target in ((workspace['access_directory'], '/run/zog-workspace'), (workspace['x11_directory'], '/tmp/.X11-unix')):
            entries.append(dict(source=source, destination=target, access='read-only', kind='workspace',
                                lifetime='desktop-incarnation', owner_id=workspace['incarnation'], name=Path(source).name))
    return dict(schema=VERSION, software=dict(root=str(root), access='read-only'), mounts=entries,
                facilities=dict(api_filesystems=['/proc', '/sys', '/dev'], private_temporary=['/tmp', '/var/tmp']))
