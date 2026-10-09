"""Reclaim disposable workspaces; never remove outputs, generations or job evidence.

Callers hold the image-build lock. Durable intent precedes removal, so interrupted
cleanup can be repeated. A package result remains the resume checkpoint.
"""
import argparse
import json
import os
import re
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import inventory, discard_staging, write_json


def released(directory):
    registration = directory / 'controller-resources.json'
    receipt = directory / 'controller-released.json'
    if registration.exists():
        if not receipt.exists():
            raise ImageBuildError(f'controller resources still protected: {directory}')
        if json.loads(registration.read_text())['resource_id'] != json.loads(receipt.read_text())['resource_id']:
            raise ImageBuildError('release receipt identity mismatch')
    elif list(directory.glob('*.controller.json')):
        raise ImageBuildError('controller checkpoints without resource registration')


def checked_tree(path):
    if path.is_symlink():
        raise ImageBuildError(f'cleanup target is a symlink: {path}')
    if not path.exists():
        return
    # ismount alone misses bind mounts on the same filesystem.
    mountinfo = Path('/proc/self/mountinfo')
    if not mountinfo.exists():
        raise ImageBuildError('mount inventory unavailable; refusing cleanup')
    for line in mountinfo.read_text().splitlines():
        mount = Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), line.split()[4]))
        if mount == path or path in mount.parents:
            raise ImageBuildError(f'cleanup target contains a mount: {mount}')
    device = path.parent.stat().st_dev
    for root, directories, _ in os.walk(path, followlinks=False):
        candidate = Path(root)
        if candidate.stat().st_dev != device or os.path.ismount(candidate):
            raise ImageBuildError(f'cleanup target contains a mount: {candidate}')
        directories[:] = [name for name in directories if not (candidate / name).is_symlink()]


def discard_work(directory, names, binding, *, apply):
    directory = Path(directory)
    if directory.is_symlink() or directory.resolve() != directory.absolute():
        raise ImageBuildError('cleanup owner traverses a symlink')
    if any(name not in {'root', 'source', 'composed'} for name in names):
        raise ImageBuildError('unsupported cleanup target')
    released(directory)
    paths = [directory / name for name in names]
    for path in paths:
        checked_tree(path)
    receipt = directory / 'workspace-cleanup.json'
    intent = {'schema': 1, 'binding': binding, 'names': list(names)}
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if any(saved.get(key) != value for key, value in intent.items()):
            raise ImageBuildError('cleanup binding changed')
    existing = [str(path) for path in paths if path.exists()]
    if apply:
        write_json(receipt, dict(intent, phase='removing'))
        for path in paths:
            if path.exists():
                discard_staging(path)
        write_json(receipt, dict(intent, phase='complete'))
    return existing


def package_workspace(directory, *, apply=True):
    directory = Path(directory)
    result = json.loads((directory / 'result.json').read_text())
    if inventory(directory / 'output') != result['outputs']:
        raise ImageBuildError('package outputs changed; refusing cleanup')
    from .test_fixtures import cleanup as cleanup_test_fixtures
    removed=cleanup_test_fixtures(directory,apply=apply)
    return removed+discard_work(directory, ('root', 'source'), result, apply=apply)


def completed_workspaces(builder, *, apply=False):
    """Conservative sweep: only attempts owned by completed pipelines.

    Unfinished, failed, released and unowned attempts are retained. All package
    outputs stay in place for dependency reuse and integrity verification.
    """
    from .engine import read_selection
    report = {'apply': apply, 'paths': [], 'retained': []}
    with builder.locked():
        base = builder.state / 'image-build'
        for path in sorted((base / 'pipelines').glob('*/pipeline.json')):
            record = json.loads(path.read_text())
            if record['status'] != 'complete':
                report['retained'].append(str(path.parent))
                continue
            read_selection(base / 'generations' / record['generation'])
            for name in record['attempts'].values():
                if Path(name).name != name or name in {'.', '..'}:
                    raise ImageBuildError('invalid attempt name')
                attempt = base / 'attempts' / name
                if json.loads((attempt / 'status.json').read_text())['status'] != 'complete':
                    raise ImageBuildError('completed pipeline has an incomplete attempt')
                for package in sorted((attempt / 'packages').iterdir()):
                    if not (package / 'result.json').exists():
                        report['retained'].append(str(package))
                        continue
                    report['paths'] += package_workspace(package, apply=apply)
                # Composition is recoverable from retained outputs; only terminal
                # pipelines bypass composition verification on resume.
                report['paths'] += discard_work(attempt, ('composed',),
                    {'pipeline_id': record['pipeline_id'], 'generation': record['generation']}, apply=apply)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='default is read-only inventory')
    args = parser.parse_args()
    from .engine import ImageBuild
    builder = ImageBuild(package_dir=Path('.'), state_dir=args.state_dir)
    print(json.dumps(completed_workspaces(builder, apply=args.apply), indent=2))


if __name__ == '__main__':
    main()
