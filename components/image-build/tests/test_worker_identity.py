import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zog.image_build import native_tools


class StopAfterIntent(RuntimeError):
    pass


def _native_worker_fixture(tmp_path, monkeypatch):
    catalogue = tmp_path / "catalogue" / "package"
    catalogue.mkdir(parents=True)
    base_components = tmp_path / "components.json"
    base_components.write_text("{}")
    check = tmp_path / "check.sh"
    check.write_text("true\n")
    selection = tmp_path / "generation"
    selection.mkdir()
    base = SimpleNamespace(
        generation="a" * 64,
        manifest={
            "python_runtime_verified": True,
            "public_trust_store_verified": True,
            "packages": {},
        },
    )

    def stage(plan_file, catalogue_path, destination):
        destination.mkdir(parents=True, exist_ok=True)
        return {"targets": []}

    class FakeProvenance:
        @staticmethod
        def capture_pin(*args, **kwargs):
            return {"digest": "sha256:" + "1" * 64}

        def __init__(
            self, state, *, host_id, project_id, pin, retry_of=None
        ):
            self.host_id = host_id
            self.project_id = project_id
            self.pin = pin
            self.retry_of = retry_of

        def configuration(self):
            return {
                "schema": 2,
                "host_id": self.host_id,
                "project_id": self.project_id,
                "pin": self.pin,
                "retry_of": self.retry_of or {},
                "generation_contract": "rootfs-v1",
            }

    class FakeBuilder:
        def __init__(self, *, state_dir, provenance, **kwargs):
            self.state = Path(state_dir)
            self.provenance = provenance

        def _policy(self):
            return {"provenance": self.provenance.configuration()}

    monkeypatch.setattr(native_tools, "read_selection", lambda path: base)
    monkeypatch.setattr(native_tools, "stage_recipes", stage)
    monkeypatch.setattr(native_tools, "load_packages", lambda path: {})
    monkeypatch.setattr(native_tools, "Provenance", FakeProvenance)
    monkeypatch.setattr(native_tools, "ImageBuild", FakeBuilder)
    monkeypatch.setattr(native_tools, "inventory", lambda path: [])
    monkeypatch.setattr(
        native_tools, "configured_runner", lambda *args: object()
    )
    monkeypatch.setattr(
        native_tools,
        "wait_for",
        lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(StopAfterIntent()),
    )
    return dict(
        project=tmp_path / "project",
        catalogue=catalogue,
        controller=tmp_path / "controller.json",
        selection=selection,
        work=tmp_path / "work",
        source_revision="b" * 40,
        base_components=base_components,
        plan_file=tmp_path / "plan.py",
        check_file=check,
    )


def test_native_tools_caller_identity_reaches_frozen_provenance(
    tmp_path, monkeypatch
):
    args = _native_worker_fixture(tmp_path, monkeypatch)
    with pytest.raises(StopAfterIntent):
        native_tools.run(
            **args,
            host_id="host-explicit",
            project_id="project-explicit",
        )
    intent = json.loads((args["work"] / "intent.json").read_text())
    assert intent["provenance"]["host_id"] == "host-explicit"
    assert intent["provenance"]["project_id"] == "project-explicit"
    assert (
        intent["policy"]["provenance"]
        == intent["provenance"]
    )


def test_native_tools_changed_identity_refuses_frozen_attempt(
    tmp_path, monkeypatch
):
    args = _native_worker_fixture(tmp_path, monkeypatch)
    with pytest.raises(StopAfterIntent):
        native_tools.run(
            **args, host_id="host-a", project_id="project-a"
        )
    with pytest.raises(
        ValueError, match="Frozen native tool attempt changed"
    ):
        native_tools.run(
            **args, host_id="host-b", project_id="project-a"
        )
    with pytest.raises(
        ValueError, match="Frozen native tool attempt changed"
    ):
        native_tools.run(
            **args, host_id="host-a", project_id="project-b"
        )


def test_native_tools_cli_requires_owner_identity(monkeypatch):
    argv = [
        "native-tools",
        "--project",
        "/tmp/project",
        "--catalogue",
        "/tmp/catalogue",
        "--controller",
        "/tmp/controller",
        "--selection",
        "/tmp/selection",
        "--work",
        "/tmp/work",
        "--source-revision",
        "a" * 40,
        "--base-components",
        "/tmp/components",
        "--plan-file",
        "/tmp/plan",
        "--check-file",
        "/tmp/check",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as caught:
        native_tools.main()
    assert caught.value.code == 2


def test_reusable_workers_contain_no_deployment_owner_literals():
    import zog.image_build.host_trust as host_trust
    import zog.image_build.python_enrollment as python_enrollment

    for module in (native_tools, host_trust, python_enrollment):
        source = Path(module.__file__).read_text()
        assert not __import__("re").search(r"i-[0-9a-f]{17}", source)
        assert "zog-compiler-view" not in source
