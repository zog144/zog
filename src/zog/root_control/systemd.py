from __future__ import annotations

import json
import os
import pwd
import grp
import re
import subprocess
import time
from functools import wraps

from dbus_next import Variant
from .jobs import SystemdJobConnection, JobError
from pathlib import Path

_SYSTEMD_DEST = "org.freedesktop.systemd1"
_SYSTEMD_MANAGER_PATH = "/org/freedesktop/systemd1"
_SYSTEMD_MANAGER_IFACE = "org.freedesktop.systemd1.Manager"
_UNIT_IFACE = "org.freedesktop.systemd1.Unit"
_SERVICE_IFACE = "org.freedesktop.systemd1.Service"
_SLICE_IFACE = "org.freedesktop.systemd1.Slice"
_MANIFEST_NAME = ".box-control-rootfs.json"
_COMPONENT = re.compile(r"^[A-Za-z0-9-]+$")


class SystemdBackendError(RuntimeError):
    pass


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def bounded_observation(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        previous = self.deadline
        self.deadline = time.monotonic() + self.observation_timeout_seconds
        try:
            return method(self, *args, **kwargs)
        finally:
            self.deadline = previous
    return wrapped


class BusctlSystemdBackend:
    """Privileged mechanism adapter using systemd's manager D-Bus API directly."""

    def __init__(self, *, runner=subprocess.run, jobs=None,
                 command_timeout_seconds=5.0, observation_timeout_seconds=15.0):
        self.runner = runner
        self._jobs = jobs
        self.command_timeout_seconds = command_timeout_seconds
        self.observation_timeout_seconds = observation_timeout_seconds
        self.deadline = None

    @property
    def jobs(self):
        if self._jobs is None:
            self._jobs = SystemdJobConnection()
        return self._jobs

    def _run(self, args: list[str], *, allow_missing_unit: bool = False) -> str | None:
        timeout = self.command_timeout_seconds
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            raise SystemdBackendError("systemd observation deadline exceeded")
        try:
            completed = self.runner(
                args, check=False, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise SystemdBackendError(f"systemd command failed or timed out: {exc}") from exc
        if completed.returncode:
            error = (completed.stderr or completed.stdout or "busctl failed").strip()
            if allow_missing_unit and (
                "NoSuchUnit" in error
                or "Unit " in error and "not loaded" in error
                or "Unknown object" in error
            ):
                return None
            raise SystemdBackendError(error)
        return completed.stdout.strip()

    def _manager_call(self, method: str, signature: str, *arguments: object, allow_missing_unit: bool = False) -> str:
        command = [
            "busctl", "--system", "call", _SYSTEMD_DEST, _SYSTEMD_MANAGER_PATH,
            _SYSTEMD_MANAGER_IFACE, method, signature,
        ]
        command.extend(str(value) for value in arguments)
        return self._run(command, allow_missing_unit=allow_missing_unit) or ""

    @staticmethod
    def _json_data(text: str):
        try:
            raw = json.loads(text)
            signature = str(raw.get("type", ""))
            data = raw["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SystemdBackendError(f"cannot parse busctl JSON: {text!r}") from exc
        # busctl represents method/property values as a JSON array on some
        # releases even when the D-Bus signature has one scalar output. Keep
        # actual D-Bus arrays intact, but unwrap one scalar result.
        if signature and not signature.startswith("a") and isinstance(data, list) and len(data) == 1:
            return data[0]
        return data

    def version(self) -> int:
        output = self._run(
            ["busctl", "--system", "--json=short", "get-property", _SYSTEMD_DEST,
             _SYSTEMD_MANAGER_PATH, _SYSTEMD_MANAGER_IFACE, "Version"]
        )
        value = self._json_data(output or "")
        match = re.search(r"(\d+)", str(value))
        if not match:
            raise SystemdBackendError(f"cannot parse systemd version: {value!r}")
        return int(match.group(1))

    @staticmethod
    def _project(project_root: str | Path) -> tuple[Path, str, str]:
        root = Path(project_root).resolve()
        identity = root.name
        if not _COMPONENT.fullmatch(identity):
            raise SystemdBackendError(f"invalid project identity: {identity!r}")
        return root, identity, f"zog-{identity}-"

    @classmethod
    def _validate_unit(cls, project_root: str | Path, unit_name: str) -> Path:
        root, _identity, prefix = cls._project(project_root)
        if not unit_name.startswith(prefix) or not unit_name.endswith((".service", ".slice")):
            raise SystemdBackendError(
                f"unit does not belong to project {root.name!r}: {unit_name!r}"
            )
        return root

    @classmethod
    def _validate_service_definition(cls, project_root, generation, definition):
        root = cls._validate_unit(project_root, str(definition["unit_name"]))
        cls._validate_unit(project_root, str(definition["slice_name"]))
        generation = str(generation)
        if not generation or Path(generation).name != generation or generation in {'.', '..'}:
            raise SystemdBackendError('invalid generation identity')
        legacy_root = root / "state" / "rootfs" / "generations" / generation / "root"
        published_root = root / "state" / "image-build" / "generations" / generation / "root"
        requested_root = Path(definition["root_directory"]).resolve()
        if requested_root == published_root.resolve():
            from zog.box_control.images import published_selection, ImageProviderError
            try:
                published_selection(root, generation)
            except ImageProviderError as exc:
                raise SystemdBackendError(str(exc)) from exc
        elif requested_root == legacy_root.resolve():
            expected_root = legacy_root.resolve()
            manifest = expected_root / _MANIFEST_NAME
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:
                raise SystemdBackendError(f"cannot validate generation manifest {manifest}: {exc}") from exc
            if str(raw.get("fingerprint")) != str(generation):
                raise SystemdBackendError("generation manifest identity does not match requested generation")
        else:
            raise SystemdBackendError('generation root is outside the selected project generation')

        state_mounts = root / "state" / "mounts"
        for source, target in definition.get("bind_paths", ()):
            source_path = Path(source)
            binding = definition.get('workspace_binding') or {}
            workspace_sources = {binding.get('x11_directory'), binding.get('access_directory')}
            if not _under(source_path, state_mounts) and str(source_path) not in workspace_sources:
                raise SystemdBackendError(f"writable bind source is outside state/mounts: {source}")
            if not str(target).startswith("/") or ".." in Path(str(target)).parts:
                raise SystemdBackendError(f"invalid writable bind target: {target!r}")
        from zog.box_control.mounts import validate, inventory
        binding = definition.get('workspace_binding') or {}
        workspace_sources = {binding.get('x11_directory'), binding.get('access_directory')}
        if binding:
            from zog.box_control.mounts import validate_workspace_targets
            validate_workspace_targets(requested_root)
        ordinary = [(source, target) for source, target in definition.get('bind_paths', ())
                    if str(source) not in workspace_sources]
        validate(requested_root, ordinary, definition.get('command', ()), require_targets=True)
        recorded = definition.get('mount_inventory')
        if recorded is not None and recorded != inventory(Path(definition['root_directory']), definition.get('bind_paths', ()),
                persistent_storage_id=definition.get('persistent_storage_id'), workspace_binding=binding):
            raise SystemdBackendError('mount inventory disagrees with service definition')
        if definition.get("protect_system") != "strict":
            raise SystemdBackendError("ProtectSystem must remain strict")
        if not bool(definition.get("private_tmp")):
            raise SystemdBackendError("PrivateTmp must remain enabled")
        if not bool(definition.get("mount_api_vfs")):
            raise SystemdBackendError("MountAPIVFS must remain enabled")
        if definition.get("standard_output") != "journal" or definition.get("standard_error") != "journal":
            raise SystemdBackendError("program stdout/stderr must use journald")
        if int(definition.get("tasks_max", -1)) != 2**64 - 1:
            raise SystemdBackendError("TasksMax must remain infinity in the initial runtime model")
        timeout = definition.get("execution_timeout_seconds")
        if timeout is not None and (type(timeout) is not int or not 1 <= timeout <= 86400):
            raise SystemdBackendError("invalid execution timeout")
        command = definition.get("command") or ()
        if not command or not str(command[0]).startswith("/"):
            raise SystemdBackendError("ExecStart executable must be an absolute generation path")
        if definition.get("type") != "exec" or definition.get("exit_type") != "cgroup":
            raise SystemdBackendError("unsupported service lifecycle type")
        if definition.get("restart") != "no" or definition.get("kill_mode") != "control-group":
            raise SystemdBackendError("unsupported systemd restart/kill policy")
        if bool(definition.get("remain_after_exit")):
            raise SystemdBackendError("RemainAfterExit must be disabled")
        return root

    @staticmethod
    def _property(name: str, signature: str, *values: object):
        # Convert the bounded set of property shapes to typed D-Bus values.
        if signature == "s":
            value = str(values[0])
        elif signature == "t":
            value = int(values[0])
        elif signature == "b":
            value = values[0] in (True, "true")
        elif signature == "as":
            value = list(values[1:])
        elif signature == "a(sasb)":
            count = int(values[2])
            value = [[values[1], list(values[3:3 + count]), values[-1] == "true"]]
        elif signature == "a(ssbt)":
            value = [[values[i], values[i+1], values[i+2] == "true", int(values[i+3])]
                     for i in range(1, len(values), 4)]
        else:
            raise SystemdBackendError(f"unsupported property signature: {signature}")
        return [name, Variant(signature, value)]

    def _job(self, method, signature, body):
        try:
            return self.jobs.call(method, signature, body, job=True)
        except JobError as exc:
            raise SystemdBackendError(str(exc)) from exc

    def release(self, *, project_root, unit_name):
        self._validate_unit(project_root, unit_name)
        try:
            self.jobs.release(unit_name)
        except JobError as exc:
            raise SystemdBackendError(str(exc)) from exc

    def start_slice(self, *, project_root, slice_name: str, description: str) -> None:
        self._validate_unit(project_root, slice_name)
        props = [
            self._property("Description", "s", description),
            self._property("TasksMax", "t", 2**64 - 1),
        ]
        props.append(self._property("AddRef", "b", "true"))
        self._job("StartTransientUnit", "ssa(sv)a(sa(sv))", [slice_name, "fail", props, []])

    def sync_application_storage(self, *, project_root, application, storage_id):
        """Flush completed prepared data before the controller publishes readiness."""
        import stat
        from zog.box_control.application_storage import ApplicationStorage
        from zog.box_control.project import Project
        from zog.box_control.durability import synchronize_directory
        from zog.box_control.errors import PersistenceError
        project = Project(Path(project_root).resolve())
        record = ApplicationStorage(project).load(application)
        if (not record or record['storage_id'] != storage_id
            or record['state'] not in {'preparing', 'uncertain'} or record['cleanup_pending']
            or len(record['steps']) != len(record['definition']['preparation'])
            or any(step['outcome'] != 'success' or not step['cleanup_complete'] for step in record['steps'])):
            raise SystemdBackendError('preparation has not completed safely')
        base = project.mounts_dir / 'persistent' / storage_id
        if base.is_symlink() or base.resolve() != base.absolute() or not base.is_dir():
            raise SystemdBackendError('persistent storage is missing or redirected')
        for name in record['mounts']:
            path = base / name
            if not path.is_dir() or path.is_symlink() or path.resolve() != path.absolute():
                raise SystemdBackendError('prepared mount is missing or redirected')
        def fail_walk(error):
            raise error
        try:
            for directory, dirs, files, descriptor in os.fwalk(base, topdown=False, follow_symlinks=False, onerror=fail_walk):
                for name in files:
                    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                os.fsync(descriptor)
            synchronize_directory(base.parent)
        except OSError as exc:
            raise PersistenceError(f'cannot synchronize prepared environment: {exc}') from exc

    def delete_application_storage(self, *, project_root, application, storage_id):
        import shutil
        from zog.box_control.application_storage import ApplicationStorage
        from zog.box_control.project import Project
        from zog.box_control.runtime.reference import RuntimeReferenceStore
        from zog.box_control.durability import synchronize_directory
        project = Project(Path(project_root).resolve())
        record = ApplicationStorage(project).load(application)
        if not record or record['storage_id'] != storage_id or record['state'] != 'deleting' or record['cleanup_pending']:
            raise SystemdBackendError('no matching durable storage deletion intent')
        references = RuntimeReferenceStore(project.runtime_reference_file).load()
        for ref in references.values():
            if ref.application == application:
                if ref.cleanup_pending:
                    raise SystemdBackendError('runtime cleanup protects persistent storage')
                for program in ref.programs:
                    observed = self.observe(project_root=project.path, unit_name=program.unit_name)
                    if observed.get('exists'):
                        raise SystemdBackendError('runtime unit still loaded; storage deletion blocked')
        base = project.mounts_dir / 'persistent' / storage_id
        if base.is_symlink() or base.resolve() != base.absolute():
            raise SystemdBackendError('persistent storage path is redirected')
        if base.exists():
            if not shutil.rmtree.avoids_symlink_attacks:
                raise SystemdBackendError('safe recursive deletion is unsupported')
            shutil.rmtree(base)
        if base.parent.exists():
            synchronize_directory(base.parent)

    @staticmethod
    def _persistent_directories(project_root, definition):
        storage_id = definition.get('persistent_storage_id')
        if storage_id is None:
            return
        if not isinstance(storage_id, str) or not re.fullmatch('[a-f0-9]{32}', storage_id):
            raise SystemdBackendError('invalid persistent storage identity')
        from zog.box_control.durability import ensure_directory, synchronize_directory
        user = str(definition['user'])
        account = pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)
        group = definition.get('group')
        gid = account.pw_gid if group is None else (int(group) if str(group).isdecimal() else grp.getgrnam(group).gr_gid)
        if account.pw_uid == 0 or gid == 0:
            raise SystemdBackendError('persistent preparation must be unprivileged')
        base = Path(project_root).resolve() / 'state' / 'mounts' / 'persistent' / storage_id
        if base.resolve() != base:
            raise SystemdBackendError('persistent storage path is redirected')
        ensure_directory(base)
        for source, _target in definition.get('bind_paths', ()):
            binding = definition.get('workspace_binding') or {}
            if source in (binding.get('x11_directory'), binding.get('access_directory')):
                continue
            path = Path(source)
            if path.parent != base or path.resolve() != path or path.is_symlink():
                raise SystemdBackendError('persistent mount must be a direct owned directory')
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                info = path.stat()
                if not path.is_dir() or (info.st_uid, info.st_gid) != (account.pw_uid, gid):
                    raise SystemdBackendError('existing persistent directory ownership disagrees; explicit repair required')
            else:
                os.chown(path, account.pw_uid, gid)
            synchronize_directory(path)
            synchronize_directory(base)

    def start_service(self, *, project_root, generation: str, definition: dict) -> None:
        self._validate_service_definition(project_root, generation, definition)
        binding = definition.get('workspace_binding')
        if binding:
            from .workspace import WorkspaceBackend
            WorkspaceBackend(self).verify(project_root=project_root, binding=binding)
        self._persistent_directories(project_root, definition)
        command = [str(item) for item in definition["command"]]
        environment = [f"{key}={value}" for key, value in definition.get("environment", ())]
        binds = definition.get("bind_paths", ())
        props: list[list[str]] = [
            self._property("Description", "s", definition.get("description") or definition["unit_name"]),
            self._property("Slice", "s", definition["slice_name"]),
            self._property("Type", "s", definition["type"]),
            self._property("ExitType", "s", definition["exit_type"]),
            self._property("KillMode", "s", definition["kill_mode"]),
            self._property("Restart", "s", definition["restart"]),
            self._property("RemainAfterExit", "b", str(bool(definition["remain_after_exit"])).lower()),
            self._property("RootDirectory", "s", definition["root_directory"]),
            self._property("ExecStart", "a(sasb)", 1, command[0], len(command), *command, "false"),
            self._property("Environment", "as", len(environment), *environment),
            self._property("WorkingDirectory", "s", definition["working_directory"]),
            self._property("ProtectSystem", "s", definition["protect_system"]),
            self._property("PrivateTmp", "b", str(bool(definition["private_tmp"])).lower()),
            self._property("MountAPIVFS", "b", str(bool(definition["mount_api_vfs"])).lower()),
            self._property("StandardOutput", "s", definition["standard_output"]),
            self._property("StandardError", "s", definition["standard_error"]),
            self._property("User", "s", definition["user"]),
            self._property("TasksMax", "t", int(definition["tasks_max"])),
        ]
        if binding:
            props.append(self._property('NetworkNamespacePath', 's', binding['namespace_path']))
            if binding['role'] == 'client':
                props.append(self._property(
                    'BindReadOnlyPaths', 'a(ssbt)', 2,
                    binding['access_directory'], '/run/zog-workspace', 'false', 0,
                    binding['x11_directory'], '/tmp/.X11-unix', 'false', 0,
                ))
        if definition.get("execution_timeout_seconds") is not None:
            props.append(self._property("RuntimeMaxUSec", "t", definition["execution_timeout_seconds"] * 1_000_000))
        if definition.get("group"):
            props.append(self._property("Group", "s", definition["group"]))
        if binds:
            bind_values: list[object] = [len(binds)]
            for source, target in binds:
                bind_values.extend((source, target, "false", 0))
            props.append(self._property("BindPaths", "a(ssbt)", *bind_values))
        props.append(self._property("AddRef", "b", "true"))
        # Bound systemd's own stop escalation as well as our wait for its job.
        props.append(self._property("TimeoutStopUSec", "t", int(definition["timeout_stop_microseconds"])))
        self._job("StartTransientUnit", "ssa(sv)a(sa(sv))",
                  [definition["unit_name"], "fail", props, []])

    def _get_unit_path(self, unit_name: str) -> str | None:
        output = self._run(
            ["busctl", "--system", "--json=short", "call", _SYSTEMD_DEST,
             _SYSTEMD_MANAGER_PATH, _SYSTEMD_MANAGER_IFACE, "GetUnit", "s", unit_name],
            allow_missing_unit=True,
        )
        if output is None:
            return None
        return str(self._json_data(output))

    def _get_property(self, object_path: str, interface: str, name: str, *, optional=False):
        try:
            output = self._run(
                ["busctl", "--system", "--json=short", "get-property", _SYSTEMD_DEST,
                 object_path, interface, name]
            )
        except SystemdBackendError as exc:
            # Optional means that an older supported systemd release may not
            # expose this particular property. It must not turn unrelated bus,
            # permission, or transport failures into a fabricated None value.
            text = str(exc)
            if optional and any(
                marker in text
                for marker in ("UnknownProperty", "UnknownInterface", "No such property")
            ):
                return None
            raise
        return self._json_data(output or "")

    @staticmethod
    def _invocation_id(value) -> str | None:
        if value in (None, "", []):
            return None
        if isinstance(value, list) and all(isinstance(item, int) for item in value):
            if not any(value):
                return None
            return "".join(f"{item:02x}" for item in value)
        return str(value).replace(" ", "")

    @staticmethod
    def _normalize_exec_start(value):
        if not value:
            return []
        entry = value[0] if isinstance(value, list) and value else value
        if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[1], list):
            return [str(item) for item in entry[1]]
        return value

    @staticmethod
    def _normalize_bind_paths(value):
        result = []
        for entry in value or ():
            if isinstance(entry, list) and len(entry) >= 2:
                result.append([str(entry[0]), str(entry[1])])
        return result

    @bounded_observation
    def observe(self, *, project_root, unit_name: str) -> dict:
        self._validate_unit(project_root, unit_name)
        object_path = self._get_unit_path(unit_name)
        if object_path is None:
            return {"exists": False, "unit_name": unit_name}
        unit = lambda name, optional=False: self._get_property(object_path, _UNIT_IFACE, name, optional=optional)
        service = lambda name, optional=False: self._get_property(object_path, _SERVICE_IFACE, name, optional=optional)
        transient = unit("Transient", optional=True)
        fragment = unit("FragmentPath", optional=True) or ""
        drop_ins = unit("DropInPaths", optional=True) or []
        invocation = self._invocation_id(unit("InvocationID", optional=True))
        active = str(unit("ActiveState"))
        sub = str(unit("SubState"))
        is_service = unit_name.endswith(".service")
        is_slice = unit_name.endswith(".slice")
        typed = service if is_service else (
            (lambda name, optional=False: self._get_property(
                object_path, _SLICE_IFACE, name, optional=optional
            )) if is_slice else None
        )
        control_group = typed("ControlGroup", optional=True) if typed else None
        slice_name = typed("Slice", optional=True) if typed else None
        tasks_max = typed("TasksMax", optional=True) if typed else None
        result = service("Result", optional=True) if is_service else None
        main_pid = service("MainPID", optional=True) if is_service else None

        properties = []
        if is_service:
            mapping = {
                "Type": service("Type"),
                "ExitType": service("ExitType"),
                "KillMode": service("KillMode"),
                "Restart": service("Restart"),
                "RemainAfterExit": service("RemainAfterExit"),
                "Slice": slice_name,
                "RootDirectory": service("RootDirectory"),
                "ExecStart": self._normalize_exec_start(service("ExecStart")),
                "Environment": sorted(str(item) for item in (service("Environment") or [])),
                "WorkingDirectory": service("WorkingDirectory"),
                "BindPaths": self._normalize_bind_paths(service("BindPaths", optional=True) or []),
                "ProtectSystem": service("ProtectSystem"),
                "PrivateTmp": service("PrivateTmp"),
                "MountAPIVFS": service("MountAPIVFS"),
                "StandardOutput": service("StandardOutput"),
                "StandardError": service("StandardError"),
                "User": service("User"),
                "TasksMax": tasks_max,
                "TimeoutStopUSec": service("TimeoutStopUSec"),
            }
            namespace_path = service('NetworkNamespacePath', optional=True)
            if namespace_path:
                mapping['NetworkNamespacePath'] = namespace_path
                mapping['BindReadOnlyPaths'] = self._normalize_bind_paths(service('BindReadOnlyPaths', optional=True) or [])
            maximum = service("RuntimeMaxUSec", optional=True)
            if maximum is not None:
                mapping["RuntimeMaxUSec"] = maximum
            group = service("Group", optional=True)
            if group:
                mapping["Group"] = group
            properties = list(mapping.items())

        return {
            "exists": True,
            "unit_name": unit_name,
            "transient": bool(transient) if transient is not None else not bool(fragment),
            "fragment_path": str(fragment),
            "drop_in_paths": [str(item) for item in drop_ins],
            "invocation_id": invocation,
            "active_state": active,
            "sub_state": sub,
            "result": result,
            "main_pid": int(main_pid) if main_pid else None,
            "control_group": str(control_group) if control_group else None,
            "properties": [[name, value] for name, value in properties],
        }

    def kill(self, *, project_root, unit_name: str, signal_number: int) -> None:
        self._validate_unit(project_root, unit_name)
        self._manager_call("KillUnit", "ssi", unit_name, "all", int(signal_number))

    def stop(self, *, project_root, unit_name: str) -> None:
        self._validate_unit(project_root, unit_name)
        try:
            self._job("StopUnit", "ss", [unit_name, "replace"])
        except SystemdBackendError as exc:
            if "org.freedesktop.systemd1.NoSuchUnit" not in str(exc):
                raise

    def reset_failed(self, *, project_root, unit_name: str) -> None:
        self._validate_unit(project_root, unit_name)
        self._manager_call("ResetFailedUnit", "s", unit_name, allow_missing_unit=True)
