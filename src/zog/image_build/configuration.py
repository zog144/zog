"""Explicit deployment configuration for box-control finite build jobs."""
import json
import math
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import inventory
from .metadata import identity


def input_manifest(request):
    parent = request.root.parent
    prepared = parent / ('probe-prepared.json' if request.root.name == 'probe-root' else 'prepared.json')
    if not prepared.exists():
        raise ImageBuildError('engine preparation manifest is required')
    record = json.loads(prepared.read_text())
    if record['root'] != inventory(request.root):
        raise ImageBuildError('prepared root differs from recorded inputs')
    return identity(record)


def configured_runner(path, state_dir):
    from zog.box_control import BoxControl, Project
    from zog.box_control.runtime.root_control import RootControlSystemdTransport
    from .box_control_adapter import BoxControlExecutionAdapter
    from .runner import BoxControlRunner
    raw = json.loads(Path(path).read_text())
    required = {'project_root', 'socket_path', 'execution_user_id', 'execution_group_id',
                'startup_timeout_seconds', 'execution_timeout_seconds', 'termination_grace_seconds',
                'wait_timeout_seconds', 'transport_timeout_seconds', 'resource_limits'}
    if set(raw) - {'device_profile'} != required:
        raise ImageBuildError('controller configuration has missing or unsupported fields')
    for key in ('execution_user_id', 'execution_group_id'):
        if type(raw[key]) is not int or not 0 < raw[key] < 2**31:
            raise ImageBuildError('explicit nonzero execution UID/GID required')
    for key in ('startup_timeout_seconds', 'execution_timeout_seconds', 'termination_grace_seconds',
                'wait_timeout_seconds', 'transport_timeout_seconds'):
        value = raw[key]
        minimum = 0 if key == 'wait_timeout_seconds' else 0.000001
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= 604800:
            raise ImageBuildError(f'invalid {key}')
    limits = raw['resource_limits']
    if not isinstance(limits, dict) or set(limits) - {'stack-maximum-bytes', 'cpu-weight'} != {'thread-count-maximum', 'memory-maximum-bytes'} or any(type(v) is not int or not 0 < v < 2**63 for v in limits.values()):
        raise ImageBuildError('explicit positive thread and memory limits required')
    if 'cpu-weight' in limits and not 1 <= limits['cpu-weight'] <= 10000:
        raise ImageBuildError('cpu-weight must be 1..10000')
    for key in ('project_root', 'socket_path'):
        if not isinstance(raw[key], str) or not Path(raw[key]).is_absolute():
            raise ImageBuildError(f'{key} must be absolute')
    project = Project(Path(raw['project_root']))
    if Path(state_dir).resolve() != project.state_dir:
        raise ImageBuildError('state-dir must be the controller project state directory (not state/image-build)')
    transport = RootControlSystemdTransport(Path(raw['socket_path']), timeout_seconds=raw['transport_timeout_seconds'])
    adapter = BoxControlExecutionAdapter(BoxControl(project, systemd_transport=transport),
        **{k: raw[k] for k in ('execution_user_id', 'execution_group_id', 'startup_timeout_seconds',
                              'termination_grace_seconds', 'wait_timeout_seconds', 'resource_limits')},
        input_manifest_id=input_manifest, **({'device_profile':raw['device_profile']} if 'device_profile' in raw else {}))
    return BoxControlRunner(execute=adapter, timeout=raw['execution_timeout_seconds'])
