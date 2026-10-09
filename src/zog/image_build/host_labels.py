"""Explicit host-label omission for a new, provenance-bound composition only."""
import hashlib
import os
import shutil
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import inventory, merge, sync_tree, write_json, discard_staging
from .metadata import identity

POLICY = 'omit-host-security-selinux-v1'


def labels(root, entries):
    result = []
    for name in ['.', *[entry['path'] for entry in entries]]:
        path = Path(root) / name
        names = os.listxattr(path, follow_symlinks=False)
        if set(names) - {'security.selinux'}:
            raise ImageBuildError('unhandled extended attributes: ' + str(path))
        if names:
            raw = os.getxattr(path, 'security.selinux', follow_symlinks=False)
            result.append({'path': name, 'name': 'security.selinux',
                           'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    return result


def snapshot(built):
    return {'policy': POLICY, 'packages': {
        name: {'identity': record['identity'], 'labels': labels(record['root'], record['outputs'])}
        for name, record in sorted(built.items())}}


def copy_file(source, target):
    # Do not use copy2/copystat: they copy host xattrs. All source attributes have
    # been inspected and bound before composition; unknown ones fail closed.
    if set(os.listxattr(source, follow_symlinks=False)) - {'security.selinux'}:
        raise ImageBuildError('unhandled source extended attributes')
    shutil.copyfile(source, target)
    shutil.copymode(source, target)


def compose(attempt, built, order, expected, *, directories=None):
    from .metadata import relative
    directories = dict(directories or {})
    for name, mode in directories.items():
        relative(name)
        if type(mode) is not int or not 0 <= mode <= 0o7777:
            raise ImageBuildError('invalid composition directory mode')
    root = attempt/'composed'
    receipt = attempt/'composed.composition.json'
    if snapshot(built) != expected:
        raise ImageBuildError('source host-label evidence changed')
    binding = {'policy': POLICY, 'source_labels': identity(expected),
               'order': order, 'packages': {n: built[n]['identity'] for n in order}}
    if directories:
        binding['directories'] = directories
    if receipt.exists():
        import json
        saved = json.loads(receipt.read_text())
        if saved['inputs'] != binding or saved['outputs'] != inventory(root):
            raise ImageBuildError('recorded label-free composition changed')
    else:
        if root.exists(): discard_staging(root)
        root.mkdir()
        for name in order:
            merge(built[name]['root'], root, compose_info=True, copy_file=copy_file)
        for name, mode in directories.items():
            path = root/name
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ImageBuildError('composition directory crosses symlink')
            if path.exists():
                if not path.is_dir() or path.stat().st_mode & 0o7777 != mode:
                    raise ImageBuildError('composition directory conflicts with package output')
            else:
                path.mkdir(parents=True)
                path.chmod(mode)
        if snapshot(built) != expected:
            raise ImageBuildError('source host-label evidence changed during composition')
        sync_tree(root)
        write_json(receipt, {'inputs': binding, 'outputs': inventory(root)})
    from .host_export import records
    records(root)  # The existing strict serializer contract is unchanged.
    return root
