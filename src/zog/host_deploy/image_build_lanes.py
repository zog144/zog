"""Durable image-build lane ownership for one shared development host.

A lane is one independent box-control Project plus one image-build state universe.
Lanes share the EC2 host and root-control socket, never mutable build state.
"""
import json
from pathlib import Path, PurePosixPath
import re
import shlex

from .provision import configuration
from .runner import Host
from .workspace import locked, save

SCHEMA = 1
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_REVISION = re.compile(r"[0-9a-f]{40,64}")
DEFAULT_ROOT = Path("/var/lib/zog/image-build-lanes")


def _positive(value, name, maximum=2**63 - 1):
    if type(value) is not int or not 0 < value <= maximum:
        raise ValueError("invalid lane " + name)
    return value


def validate(spec):
    required = {
        "schema",
        "lane",
        "mode",
        "source_repository",
        "source_revision",
        "pin_identity",
        "provenance_host_id",
        "provenance_project_id",
        "project_root",
        "resource_policy",
        "controller",
    }
    if not isinstance(spec, dict) or set(spec) != required or spec.get("schema") != SCHEMA:
        raise ValueError("unsupported image-build lane specification")
    lane = spec["lane"]
    if not isinstance(lane, str) or not _NAME.fullmatch(lane):
        raise ValueError("invalid image-build lane name")
    if spec["mode"] not in {"managed", "reservation"}:
        raise ValueError("image-build lane mode must be managed or reservation")
    if (
        not isinstance(spec["source_repository"], str)
        or not spec["source_repository"]
        or len(spec["source_repository"]) > 512
    ):
        raise ValueError("invalid lane source repository")
    if not isinstance(spec["source_revision"], str) or not _REVISION.fullmatch(
        spec["source_revision"]
    ):
        raise ValueError("lane source revision must be an immutable commit identity")
    pin_identity = spec["pin_identity"]
    if (
        not isinstance(pin_identity, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", pin_identity)
    ):
        raise ValueError("lane pin_identity must be the exact commit-pin.py SHA-256")
    for key in ("provenance_host_id", "provenance_project_id"):
        if (
            not isinstance(spec[key], str)
            or not spec[key]
            or len(spec[key]) > 512
            or any(ord(c) < 32 for c in spec[key])
        ):
            raise ValueError("invalid lane " + key)
    project_root = Path(spec["project_root"])
    if not project_root.is_absolute():
        raise ValueError("lane project_root must be absolute")
    if spec["mode"] == "managed" and project_root.name != lane:
        raise ValueError("managed lane project_root must end with the lane name")
    policy = spec["resource_policy"]
    if not isinstance(policy, dict) or set(policy) != {
        "memory_maximum_bytes",
        "thread_count_maximum",
        "cpu_weight",
        "disk_reservation_bytes",
    }:
        raise ValueError("invalid lane resource policy")
    _positive(policy["memory_maximum_bytes"], "memory_maximum_bytes")
    _positive(policy["thread_count_maximum"], "thread_count_maximum", 2**31 - 1)
    _positive(policy["cpu_weight"], "cpu_weight", 10000)
    _positive(policy["disk_reservation_bytes"], "disk_reservation_bytes")
    controller = spec["controller"]
    required_controller = {
        "socket_path",
        "execution_user_id",
        "execution_group_id",
        "startup_timeout_seconds",
        "execution_timeout_seconds",
        "termination_grace_seconds",
        "wait_timeout_seconds",
        "transport_timeout_seconds",
    }
    if not isinstance(controller, dict) or set(controller) != required_controller:
        raise ValueError("invalid lane controller policy")
    socket_path = Path(controller["socket_path"])
    if not socket_path.is_absolute():
        raise ValueError("lane root-control socket must be absolute")
    for key in ("execution_user_id", "execution_group_id"):
        _positive(controller[key], key, 2**31 - 1)
    for key in (
        "startup_timeout_seconds",
        "execution_timeout_seconds",
        "termination_grace_seconds",
        "transport_timeout_seconds",
    ):
        _positive(controller[key], key, 604800)
    if (
        type(controller["wait_timeout_seconds"]) is not int
        or not 0 <= controller["wait_timeout_seconds"] <= 604800
    ):
        raise ValueError("invalid lane wait_timeout_seconds")
    return json.loads(json.dumps(spec))


def specification(
    lane,
    *,
    mode="managed",
    source_repository,
    source_revision,
    pin_identity,
    provenance_host_id,
    provenance_project_id,
    memory_maximum_bytes,
    thread_count_maximum,
    cpu_weight,
    disk_reservation_bytes,
    execution_user_id,
    execution_group_id,
    project_root=None,
    socket_path="/run/zog/root-control.sock",
    startup_timeout_seconds=30,
    execution_timeout_seconds=3600,
    termination_grace_seconds=10,
    wait_timeout_seconds=0,
    transport_timeout_seconds=45,
):
    project_root = Path(project_root) if project_root else DEFAULT_ROOT / lane
    return validate(
        {
            "schema": SCHEMA,
            "lane": lane,
            "mode": mode,
            "source_repository": source_repository,
            "source_revision": source_revision,
            "pin_identity": pin_identity,
            "provenance_host_id": provenance_host_id,
            "provenance_project_id": provenance_project_id,
            "project_root": str(project_root),
            "resource_policy": {
                "memory_maximum_bytes": memory_maximum_bytes,
                "thread_count_maximum": thread_count_maximum,
                "cpu_weight": cpu_weight,
                "disk_reservation_bytes": disk_reservation_bytes,
            },
            "controller": {
                "socket_path": socket_path,
                "execution_user_id": execution_user_id,
                "execution_group_id": execution_group_id,
                "startup_timeout_seconds": startup_timeout_seconds,
                "execution_timeout_seconds": execution_timeout_seconds,
                "termination_grace_seconds": termination_grace_seconds,
                "wait_timeout_seconds": wait_timeout_seconds,
                "transport_timeout_seconds": transport_timeout_seconds,
            },
        }
    )


def _path(root, lane):
    if not isinstance(lane, str) or not _NAME.fullmatch(lane):
        raise ValueError("invalid image-build lane name")
    return Path(root) / "image-build-lanes" / (lane + ".json")


def prepare(directory, spec):
    spec = validate(spec)
    with locked(directory) as root:
        path = _path(root, spec["lane"])
        others = []
        lane_dir = path.parent
        if lane_dir.exists():
            for candidate in lane_dir.glob("*.json"):
                if candidate == path:
                    continue
                try:
                    others.append(json.loads(candidate.read_text()))
                except (OSError, ValueError, TypeError):
                    raise RuntimeError("invalid retained image-build lane record")
        project_root = Path(spec["project_root"]).resolve()
        basename = project_root.name
        for item in others:
            if item.get("state") == "retired":
                continue
            other = item["specification"]
            other_root = Path(other["project_root"]).resolve()
            if other_root == project_root:
                raise ValueError("image-build project root is already owned by another lane")
            if (
                spec["mode"] == "managed"
                and other.get("mode", "managed") == "managed"
                and other_root.name == basename
            ):
                raise ValueError("managed image-build project basename must be host-unique")
        if path.exists():
            record = json.loads(path.read_text())
            if record.get("schema") != SCHEMA or record["specification"] != spec:
                raise ValueError("existing image-build lane is bound to different inputs")
            return record
        record = {
            "schema": SCHEMA,
            "lane": spec["lane"],
            "specification": spec,
            "state": "prepared",
        }
        save(path, record)
        return record


def inspect(directory, lane):
    with locked(directory) as root:
        record = json.loads(_path(root, lane).read_text())
        if record.get("schema") != SCHEMA:
            raise ValueError("invalid image-build lane record")
        validate(record["specification"])
        return record


def _controller(spec):
    policy = spec["resource_policy"]
    controller = spec["controller"]
    return {
        "project_root": spec["project_root"],
        "socket_path": controller["socket_path"],
        "execution_user_id": controller["execution_user_id"],
        "execution_group_id": controller["execution_group_id"],
        "startup_timeout_seconds": controller["startup_timeout_seconds"],
        "execution_timeout_seconds": controller["execution_timeout_seconds"],
        "termination_grace_seconds": controller["termination_grace_seconds"],
        "wait_timeout_seconds": controller["wait_timeout_seconds"],
        "transport_timeout_seconds": controller["transport_timeout_seconds"],
        "resource_limits": {
            "thread-count-maximum": policy["thread_count_maximum"],
            "memory-maximum-bytes": policy["memory_maximum_bytes"],
            "cpu-weight": policy["cpu_weight"],
        },
    }


def _active_records(root):
    directory = Path(root) / "image-build-lanes"
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text())
        if record.get("state") == "active":
            validate(record["specification"])
            result.append(record)
    return result


def _capacity(host, project_root):
    # Measure the filesystem that will contain the lane without requiring its
    # parent directory to exist yet.
    code = (
        "import json,os;"
        "from pathlib import Path;"
        "m=int(open('/proc/meminfo').read().split('MemTotal:')[1].split()[0])*1024;"
        f"p=Path({str(project_root.parent)!r});"
        "p=next((x for x in (p,*p.parents) if x.exists()),Path('/'));"
        "v=os.statvfs(p);"
        "print(json.dumps({'memory_bytes':m,'disk_free_bytes':v.f_bavail*v.f_frsize}))"
    )
    return json.loads(host.command("python3 -c " + shlex.quote(code)))


def activate(directory, lane):
    with locked(directory) as root:
        workspace, host_config = configuration(root)
        path = _path(root, lane)
        record = json.loads(path.read_text())
        spec = validate(record["specification"])
        host = Host(host_config)
        capacity = _capacity(host, Path(spec["project_root"]))
        active = [
            item
            for item in _active_records(root)
            if item["lane"] != lane
        ]
        reserved_memory = sum(
            item["specification"]["resource_policy"]["memory_maximum_bytes"]
            for item in active
        )
        reserved_disk = sum(
            item["specification"]["resource_policy"]["disk_reservation_bytes"]
            for item in active
        )
        policy = spec["resource_policy"]
        if reserved_memory + policy["memory_maximum_bytes"] > capacity["memory_bytes"]:
            raise RuntimeError("image-build lane memory reservations exceed host capacity")
        if reserved_disk + policy["disk_reservation_bytes"] > capacity["disk_free_bytes"]:
            raise RuntimeError("image-build lane disk reservations exceed free capacity")
        project = Path(spec["project_root"])
        if spec["mode"] == "managed":
            command = "set -eu\n" + "\n".join(
                "install -d -m 0755 " + shlex.quote(str(project / name))
                for name in ("", "package", "application", "catalogue", "state", "source")
            )
            host.command(command)
            controller = _controller(spec)
            host.upload(
                (json.dumps(controller, sort_keys=True, indent=2) + "\n").encode(),
                str(project / "controller.json"),
            )
            record.update(
                controller_config=str(project / "controller.json"),
                source_root=str(project / "source"),
                package_dir=str(project / "source" / "project" / "package"),
                state_dir=str(project / "state"),
            )
        record.update(state="active", capacity=capacity)
        save(path, record)
        return record


def retire(directory, lane):
    """Stop admitting new work. Remote build state is deliberately retained."""
    with locked(directory) as root:
        path = _path(root, lane)
        record = json.loads(path.read_text())
        validate(record["specification"])
        record["state"] = "retired"
        save(path, record)
        return record


def remote_operation_argv(record, request_path):
    """Return argv for an already deployed exact source checkout."""
    if record.get("state") != "active":
        raise RuntimeError("image-build lane is not active")
    spec = validate(record["specification"])
    if spec["mode"] != "managed":
        raise RuntimeError("reservation-only lane does not execute remote operations")
    request_path = Path(request_path)
    if not request_path.is_absolute():
        raise ValueError("remote request path must be absolute")
    return [
        "env",
        "PYTHONPATH=" + str(Path(record["source_root"]) / "src"),
        "python3",
        "-m",
        "zog.image_build.remote_operations",
        "--repository-root",
        record["source_root"],
        "--source-repository",
        spec["source_repository"],
        "--source-revision",
        spec["source_revision"],
        "--package-dir",
        record["package_dir"],
        "--state-dir",
        record["state_dir"],
        "--controller-config",
        record["controller_config"],
        "--provenance-host-id",
        spec["provenance_host_id"],
        "--provenance-project-id",
        spec["provenance_project_id"],
        "--expected-pin-digest",
        spec["pin_identity"],
        str(request_path),
    ]
