"""Station-owned test doubles for installed box-control public integration APIs.

These simulate image selection and systemd/socket IO only. The installed controller
still performs real durable requests, workspace membership and lifecycle decisions.
No upstream test files or source checkout paths are imported.
"""
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from zog.box_control.api import BoxControl
from zog.box_control.project import Project
from zog.box_control.runtime.systemd import SystemdUnitObservation
from zog.box_control.workspaces import WorkspaceError


class FixtureImageProvider:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir()
        # Match box-control's production preflight contract: workspace/X11 mount
        # targets must already exist in the selected immutable generation.
        (directory / "run" / "zog-workspace").mkdir(parents=True)
        (directory / "tmp" / ".X11-unix").mkdir(parents=True)

    def ensure(self, project):
        return SimpleNamespace(generation="station-test-generation", root=self.directory,
            manifest={"fingerprint": "station-test-generation", "packages": [], "distribution_packages": []},
            previous_manifest=None, reused=True)


class FixtureSystemdTransport:
    def __init__(self):
        self.units = {}
        self.started = []

    def version(self):
        return 257

    def operation_budget(self, timeout_seconds):
        return nullcontext()

    def start_slice(self, **kwargs):
        pass

    def release(self, **kwargs):
        pass

    def reset_failed(self, **kwargs):
        pass

    def start_service(self, *, project_root, generation, definition):
        self.started.append(definition.unit_name)
        self.units[definition.unit_name] = SystemdUnitObservation(
            unit_name=definition.unit_name, exists=True, transient=True,
            invocation_id=f"station-test-invocation-{len(self.started)}",
            active_state="active", sub_state="running", result="success",
            main_pid=1000 + len(self.started), control_group=f"/{definition.unit_name}",
            properties=definition.expected_properties())

    def observe(self, *, project_root, unit_name):
        return self.units.get(unit_name, SystemdUnitObservation(unit_name=unit_name, exists=False))

    def kill(self, *, project_root, unit_name, signal_number):
        if unit_name in self.units:
            self.units[unit_name] = replace(self.units[unit_name], active_state="inactive",
                                           sub_state="dead", main_pid=None)

    def stop(self, *, project_root, unit_name):
        self.units.pop(unit_name, None)

    def workspace_call(self, operation, *, project_root, binding, **kwargs):
        if operation == "prepare":
            base = project_root / "state" / "workspace-resources" / binding["incarnation"]
            for name in ("x11", "access"):
                (base / name).mkdir(parents=True)
            return dict(display=f":{binding['number']}", namespace_path="/proc/1/ns/net",
                        namespace_device=1, namespace_inode=2, x11_directory=str(base / "x11"),
                        access_directory=str(base / "access"),
                        vnc_endpoint={"kind": "unix", "path": "/run/zog/test/vnc.sock", "browser_direct": False})
        if operation != "verify":
            raise AssertionError(f"Unexpected workspace IO: {operation}")
        if binding["boot_id"] != "station-test-boot":
            raise WorkspaceError("stale-boot", "Fixture desktop belongs to another boot")
        if binding["role"] == "client":
            runtime = self.control.application_runtime(binding["desktop_runtime_id"])
            if not runtime or not all(self.observe(project_root=project_root, unit_name=p.unit_name).active for p in runtime.programs):
                raise WorkspaceError("desktop-not-ready", "Fixture desktop is not active")
        return {"ready": True}


def create_controller(directory):
    project = Project(directory / "project")
    for name, role in (("desktop", "desktop"), ("terminal", "client")):
        declaration = project.application_dir / name / "application.py"
        declaration.parent.mkdir(parents=True)
        declaration.write_text(
            f'application(name={name!r}, workspace_role={role!r}, multiple_instances=True, '
            'start_policy="externally-controlled", programs=(program(name="main", command=("/usr/bin/test",)),))')
    # State stays in the disposable fixture directory, never in a host controller project.
    project.require_state_allowed = lambda: None
    transport = FixtureSystemdTransport()
    controller = BoxControl(project, image_provider=FixtureImageProvider(directory / "root"),
        systemd_transport=transport, boot_id_provider=lambda: "station-test-boot")
    transport.control = controller
    # Reserve the initial number, mirroring the portal's default workspace migration.
    controller.register_workspace(str(uuid4()), 1)
    return controller, transport
