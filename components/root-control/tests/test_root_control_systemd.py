import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from zog.box_control.model import ApplicationSpec, ProgramSpec
from zog.box_control.project import Project
from zog.box_control.runtime.systemd import service_definition
from zog.root_control.systemd import BusctlSystemdBackend, SystemdBackendError


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, args, **kwargs):
        self.commands.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _definition(tmp_path):
    project = Project(tmp_path / "demo")
    generation = "generation-1"
    root = project.rootfs_dir / "generations" / generation / "root"
    root.mkdir(parents=True)
    for target in ("var/lib/browser", "run/zog-workspace", "tmp/.X11-unix"):
        (root / target).mkdir(parents=True)
    (root / ".box-control-rootfs.json").write_text(
        json.dumps({"fingerprint": generation}), encoding="utf-8"
    )
    application = ApplicationSpec(
        name="desktop",
        programs=(ProgramSpec(name="browser", command=("/usr/bin/browser",), mounts=(("data", "/var/lib/browser"),)),),
    )
    definition = service_definition(
        project, application, "A7K3Q2", application.programs[0], generation_root=root
    )
    definition.bind_paths[0][0].mkdir(parents=True)
    return project, generation, definition


def test_root_control_uses_typed_start_job_and_retains_unit(tmp_path):
    project, generation, definition = _definition(tmp_path)
    calls = []
    jobs = SimpleNamespace(call=lambda *args, **kwargs: calls.append((args, kwargs)))
    backend = BusctlSystemdBackend(runner=RecordingRunner(), jobs=jobs)
    backend.start_service(project_root=project.path, generation=generation,
                          definition=definition.to_transport_dict())
    (method, signature, body), options = calls[0]
    assert method == "StartTransientUnit"
    assert signature == "ssa(sv)a(sa(sv))"
    assert options == {"job": True}
    properties = dict(body[2])
    assert properties["ExecStart"].value == [["/usr/bin/browser", ["/usr/bin/browser"], False]]
    assert properties["ExitType"].value == "cgroup"
    assert properties["AddRef"].value is True
    assert properties["BindPaths"].value == [[str(definition.bind_paths[0][0]), "/var/lib/browser", False, 0]]
    assert properties["TimeoutStopUSec"].value == 10_000_000


def test_workspace_client_sends_read_only_mounts_in_start_job(tmp_path, monkeypatch):
    from zog.root_control.workspace import WorkspaceBackend

    project, generation, definition = _definition(tmp_path)
    binding = {
        "role": "client",
        "namespace_path": "/proc/1/ns/net",
        "access_directory": str(tmp_path / "workspace" / "access"),
        "x11_directory": str(tmp_path / "workspace" / "x11"),
    }
    raw = definition.to_transport_dict()
    raw["workspace_binding"] = binding
    raw.pop("mount_inventory", None)
    verified = []
    monkeypatch.setattr(WorkspaceBackend, "verify",
                        lambda self, **kwargs: verified.append(kwargs))
    calls = []
    jobs = SimpleNamespace(call=lambda *args, **kwargs: calls.append((args, kwargs)))
    backend = BusctlSystemdBackend(runner=RecordingRunner(), jobs=jobs)

    backend.start_service(project_root=project.path, generation=generation, definition=raw)

    assert verified == [{"project_root": project.path, "binding": binding}]
    (method, signature, body), options = calls[0]
    assert method == "StartTransientUnit"
    assert signature == "ssa(sv)a(sa(sv))"
    assert options == {"job": True}
    properties = dict(body[2])
    mounts = properties["BindReadOnlyPaths"]
    assert mounts.signature == "a(ssbt)"
    assert mounts.value == [
        [binding["access_directory"], "/run/zog-workspace", False, 0],
        [binding["x11_directory"], "/tmp/.X11-unix", False, 0],
    ]
    assert properties["NetworkNamespacePath"].value == "/proc/1/ns/net"
    # Workspace sources must not leak into writable mounts.
    assert properties["BindPaths"].value == [
        [str(definition.bind_paths[0][0]), "/var/lib/browser", False, 0]
    ]


def test_root_control_rejects_writable_bind_outside_project_state(tmp_path):
    project, generation, definition = _definition(tmp_path)
    raw = definition.to_transport_dict()
    raw["bind_paths"] = [[str(tmp_path / "foreign"), "/var/lib/browser"]]
    backend = BusctlSystemdBackend(runner=RecordingRunner())
    with pytest.raises(SystemdBackendError, match="outside state/mounts"):
        backend.start_service(
            project_root=project.path, generation=generation, definition=raw
        )


def test_observe_reads_cgroup_properties_from_service_interface(tmp_path):
    project = Project(tmp_path / "demo")
    backend = BusctlSystemdBackend(runner=RecordingRunner())
    backend._get_unit_path = lambda unit_name: "/org/freedesktop/systemd1/unit/test"
    calls = []

    values = {
        "Transient": True,
        "FragmentPath": "",
        "DropInPaths": [],
        "InvocationID": [0] * 15 + [1],
        "ActiveState": "active",
        "SubState": "running",
        "ControlGroup": "/zog-demo-A.service",
        "Slice": "zog-demo-A.slice",
        "TasksMax": 2**64 - 1,
        "TimeoutStopUSec": 10_000_000,
        "RuntimeMaxUSec": 2**64 - 1,
        "NetworkNamespacePath": "",
        "Result": "success",
        "MainPID": 1234,
        "Type": "exec",
        "ExitType": "cgroup",
        "KillMode": "control-group",
        "Restart": "no",
        "RemainAfterExit": False,
        "RootDirectory": "/root",
        "ExecStart": [["/usr/bin/example", ["/usr/bin/example"], False]],
        "Environment": [],
        "WorkingDirectory": "/",
        "BindPaths": [],
        "ProtectSystem": "strict",
        "PrivateTmp": True,
        "MountAPIVFS": True,
        "StandardOutput": "journal",
        "StandardError": "journal",
        "User": "regular",
        "Group": "",
    }

    def get_property(object_path, interface, name, *, optional=False):
        calls.append((interface, name))
        return values[name]

    backend._get_property = get_property
    observed = backend.observe(
        project_root=project.path, unit_name="zog-demo-A-example.service"
    )
    service_interface = "org.freedesktop.systemd1.Service"
    assert (service_interface, "Slice") in calls
    assert (service_interface, "ControlGroup") in calls
    assert (service_interface, "TasksMax") in calls
    assert observed["control_group"] == "/zog-demo-A.service"


def test_backend_subprocess_timeout_is_explicit_and_reported():
    import subprocess

    def blocked(arguments, **options):
        assert options["timeout"] == .01
        raise subprocess.TimeoutExpired(arguments, options["timeout"])

    backend = BusctlSystemdBackend(runner=blocked, command_timeout_seconds=.01)
    with pytest.raises(SystemdBackendError, match="timed out"):
        backend.version()


def test_protocol_deadline_cannot_be_extended_by_partial_messages():
    import struct
    from zog.root_control.protocol import decode

    class SlowPeer:
        timeouts = []
        def settimeout(self, timeout):
            self.timeouts.append(timeout)
        def recv(self, size):
            return struct.pack("!I", 2) if size == 4 else b"{}"

    import time
    peer = SlowPeer()
    assert decode(peer, deadline=time.monotonic() + 1) == {}
    assert 0 < peer.timeouts[1] <= peer.timeouts[0] <= 1
    with pytest.raises(TimeoutError):
        decode(peer, deadline=time.monotonic() - 1)


def test_zero_invocation_is_not_launch_evidence():
    assert BusctlSystemdBackend._invocation_id([0] * 16) is None


def test_nested_lifecycle_deadline_is_not_extended_and_expires_before_socket():
    import time
    from zog.box_control.runtime.root_control import RootControlSystemdTransport
    from zog.box_control.errors import RuntimeOperationError
    transport = RootControlSystemdTransport(Path("/not-used.sock"))
    with transport.operation_budget(1):
        outer = transport.operation_deadline
        with transport.operation_budget(100):
            assert transport.operation_deadline == outer
        transport.operation_deadline = time.monotonic() - 1
        with pytest.raises(RuntimeOperationError, match="lifecycle operation deadline"):
            transport.version()
    assert transport.operation_deadline is None


def test_finite_program_sets_runtime_limit(tmp_path):
    from dataclasses import replace
    project, generation, definition = _definition(tmp_path)
    definition = replace(definition, execution_timeout_seconds=12)
    calls = []
    backend = BusctlSystemdBackend(jobs=SimpleNamespace(call=lambda *a, **kw: calls.append(a)))
    backend.start_service(project_root=project.path, generation=generation, definition=definition.to_transport_dict())
    assert dict(calls[0][2][2])['RuntimeMaxUSec'].value == 12_000_000


def test_persistent_directory_ownership_never_repairs_existing_data(tmp_path, monkeypatch):
    import os
    import pwd
    import zog.root_control.systemd as module
    account = SimpleNamespace(pw_uid=1234, pw_gid=1234)
    monkeypatch.setattr(pwd, 'getpwnam', lambda _: account)
    calls = []
    monkeypatch.setattr(os, 'chown', lambda *a: calls.append(a))
    base = tmp_path / 'state' / 'mounts' / 'persistent' / ('a' * 32)
    definition = {'persistent_storage_id': 'a' * 32, 'user': 'regular', 'bind_paths': [[str(base / 'data'), '/data']]}
    BusctlSystemdBackend._persistent_directories(tmp_path, definition)
    assert len(calls) == 1
    # Chown was stubbed, so existing ownership now disagrees. Do not repair it.
    with pytest.raises(SystemdBackendError, match='ownership'):
        BusctlSystemdBackend._persistent_directories(tmp_path, definition)
    assert len(calls) == 1
    (base / 'data').rmdir()
    (base / 'data').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SystemdBackendError, match='direct owned'):
        BusctlSystemdBackend._persistent_directories(tmp_path, definition)


@pytest.mark.parametrize('message', [
    'Call failed: Unit zog-demo-buildabc.slice not loaded.',
    'org.freedesktop.systemd1.NoSuchUnit',
])
def test_reset_failed_tolerates_unit_collected_after_stop(tmp_path, message):
    runner = lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout='', stderr=message)
    backend = BusctlSystemdBackend(runner=runner)
    backend.reset_failed(project_root=tmp_path/'demo', unit_name='zog-demo-buildabc.slice')


def test_reset_failed_preserves_transport_failure(tmp_path):
    runner = lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout='', stderr='Access denied')
    backend = BusctlSystemdBackend(runner=runner)
    with pytest.raises(SystemdBackendError, match='Access denied'):
        backend.reset_failed(project_root=tmp_path/'demo', unit_name='zog-demo-buildabc.slice')
