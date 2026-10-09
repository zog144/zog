import json
from pathlib import Path

import pytest

from zog.host_deploy import image_build_lanes as lanes
from zog.host_deploy.workspace import initialize


def spec(name="rebuild-oct1", root=None, memory=2_000_000_000, disk=10_000_000_000):
    return lanes.specification(
        name,
        source_repository="zog144/image-build",
        source_revision="a" * 40,
        pin_identity="sha256:" + "b" * 64,
        provenance_host_id="host-fixture",
        provenance_project_id="zog-compiler-view",
        memory_maximum_bytes=memory,
        thread_count_maximum=64,
        cpu_weight=50,
        disk_reservation_bytes=disk,
        execution_user_id=1001,
        execution_group_id=1001,
        project_root=root,
    )


def workspace(tmp_path):
    root = tmp_path / "workspace"
    initialize(root, "image-build-host", "zog-development", "us-east-1")
    return root


def test_prepare_is_idempotent_and_binds_exact_source(tmp_path):
    root = workspace(tmp_path)
    first = lanes.prepare(root, spec())
    second = lanes.prepare(root, spec())
    assert first == second
    assert first["specification"]["source_revision"] == "a" * 40
    changed = spec()
    changed["source_revision"] = "c" * 40
    with pytest.raises(ValueError, match="different inputs"):
        lanes.prepare(root, changed)


def test_project_basename_is_lane_identity(tmp_path):
    root = workspace(tmp_path)
    record = lanes.prepare(root, spec("first", "/var/lib/zog/lanes/first"))
    assert Path(record["specification"]["project_root"]).name == "first"


def test_lane_root_must_end_in_lane_name():
    with pytest.raises(ValueError, match="end with"):
        spec("rebuild-oct1", "/var/lib/zog/wrong-name")


def test_resource_policy_and_cpu_weight_are_bounded():
    with pytest.raises(ValueError, match="cpu_weight"):
        lanes.specification(
            "bad",
            source_repository="zog144/image-build",
            source_revision="a" * 40,
            pin_identity="sha256:" + "b" * 64,
            provenance_host_id="host",
            provenance_project_id="project",
            memory_maximum_bytes=1,
            thread_count_maximum=1,
            cpu_weight=10001,
            disk_reservation_bytes=1,
            execution_user_id=1001,
            execution_group_id=1001,
        )


def test_remote_operation_argv_is_lane_bound(tmp_path):
    root = workspace(tmp_path)
    record = lanes.prepare(root, spec())
    record.update(
        state="active",
        source_root="/var/lib/zog/image-build-lanes/rebuild-oct1/source",
        package_dir="/var/lib/zog/image-build-lanes/rebuild-oct1/source/project/package",
        state_dir="/var/lib/zog/image-build-lanes/rebuild-oct1/state",
        controller_config="/var/lib/zog/image-build-lanes/rebuild-oct1/controller.json",
    )
    argv = lanes.remote_operation_argv(record, "/run/zog/request.json")
    assert argv[:4] == ["env", "PYTHONPATH=/var/lib/zog/image-build-lanes/rebuild-oct1/source/src", "python3", "-m"]
    assert argv[4] == "zog.image_build.remote_operations"
    assert "a" * 40 in argv
    assert "--provenance-host-id" in argv and "host-fixture" in argv
    assert "--provenance-project-id" in argv and "zog-compiler-view" in argv
    assert "--expected-pin-digest" in argv and "sha256:" + "b" * 64 in argv
    assert argv[-1] == "/run/zog/request.json"


def test_retire_keeps_record_and_disables_remote_commands(tmp_path):
    root = workspace(tmp_path)
    lanes.prepare(root, spec())
    retired = lanes.retire(root, "rebuild-oct1")
    assert retired["state"] == "retired"
    with pytest.raises(RuntimeError, match="not active"):
        lanes.remote_operation_argv(retired, "/run/request.json")


def test_validate_rejects_mutable_or_malformed_revision():
    value = spec()
    value["source_revision"] = "unstable"
    with pytest.raises(ValueError, match="immutable commit"):
        lanes.validate(value)


def test_activate_admission_and_controller_policy_without_aws(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    prepared = lanes.prepare(
        root,
        spec(
            "rebuild-oct1",
            "/var/lib/zog/image-build-lanes/rebuild-oct1",
            memory=2_000_000_000,
            disk=10_000_000_000,
        ),
    )
    host_config = {"instance_id": "i-test"}
    monkeypatch.setattr(lanes, "configuration", lambda directory: ({}, host_config))
    monkeypatch.setattr(
        lanes,
        "_capacity",
        lambda host, project_root: {
            "memory_bytes": 8_000_000_000,
            "disk_free_bytes": 100_000_000_000,
        },
    )

    uploads = {}
    commands = []
    class FakeHost:
        def __init__(self, config):
            assert config == host_config
        def command(self, command, **kwargs):
            commands.append(command)
            return ""
        def upload(self, data, path):
            uploads[path] = data

    monkeypatch.setattr(lanes, "Host", FakeHost)
    active = lanes.activate(root, "rebuild-oct1")
    assert active["state"] == "active"
    controller = json.loads(uploads[active["controller_config"]])
    assert controller["project_root"].endswith("/rebuild-oct1")
    assert controller["resource_limits"]["cpu-weight"] == 50
    assert controller["resource_limits"]["memory-maximum-bytes"] == 2_000_000_000
    assert controller["resource_limits"]["thread-count-maximum"] == 64
    assert any("install -d" in command for command in commands)


def test_activate_rejects_overcommitted_memory(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    lanes.prepare(root, spec(memory=7_000_000_000))
    monkeypatch.setattr(lanes, "configuration", lambda directory: ({}, {"instance_id": "i-test"}))
    monkeypatch.setattr(
        lanes,
        "_capacity",
        lambda host, project_root: {
            "memory_bytes": 4_000_000_000,
            "disk_free_bytes": 100_000_000_000,
        },
    )
    monkeypatch.setattr(lanes, "Host", lambda config: object())
    with pytest.raises(RuntimeError, match="memory reservations"):
        lanes.activate(root, "rebuild-oct1")


def test_reservation_lane_accounts_for_existing_work_without_remote_mutation(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    work = lanes.specification(
        "work-leading",
        mode="reservation",
        source_repository="zog144/image-build",
        source_revision="c" * 40,
        pin_identity="sha256:" + "d" * 64,
        provenance_host_id="host-fixture",
        provenance_project_id="zog-compiler-view",
        memory_maximum_bytes=3_000_000_000,
        thread_count_maximum=128,
        cpu_weight=200,
        disk_reservation_bytes=20_000_000_000,
        execution_user_id=1001,
        execution_group_id=1001,
        project_root="/var/lib/station-access/zog-compiler-view",
    )
    lanes.prepare(root, work)
    monkeypatch.setattr(lanes, "configuration", lambda directory: ({}, {"instance_id": "i-test"}))
    monkeypatch.setattr(
        lanes,
        "_capacity",
        lambda host, project_root: {
            "memory_bytes": 16_000_000_000,
            "disk_free_bytes": 200_000_000_000,
        },
    )
    class NoMutationHost:
        def __init__(self, config): pass
        def command(self, command, **kwargs):
            raise AssertionError("reservation activation must not mutate the existing project")
        def upload(self, data, path):
            raise AssertionError("reservation activation must not upload into the existing project")
    monkeypatch.setattr(lanes, "Host", NoMutationHost)
    active = lanes.activate(root, "work-leading")
    assert active["state"] == "active"
    assert "controller_config" not in active
    with pytest.raises(RuntimeError, match="reservation-only"):
        lanes.remote_operation_argv(active, "/run/request.json")
