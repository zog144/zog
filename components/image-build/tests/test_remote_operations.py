import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest

from zog.image_build import ImageBuild
from zog.image_build.errors import ImageBuildError
from zog.image_build.remote_operations import (
    MAX_INVENTORY_ITEMS,
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    RemoteOperations,
)
from zog.image_build.runner import BoxControlRunner, BuildExecutionResult


def recipe(root, name, *, build=(), runtime=(), command="compile"):
    path = root / name
    path.mkdir(parents=True)
    payload = path / "payload.txt"
    payload.write_text(name)
    sources = [{
        "url": payload.resolve().as_uri(),
        "sha256": hashlib.sha256(name.encode()).hexdigest(),
        "destination": "payload.txt",
        "archive": False,
    }]
    (path / "sources.py").write_text(repr(sources))
    (path / "dependencies.py").write_text(repr({"build": list(build), "runtime": list(runtime)}))
    (path / "build.py").write_text(repr({
        "build": [[command, name]],
        "install": [["install", name]],
    }))
    (path / "produce-manifest.py").write_text(repr(["usr/share/" + name]))
    pin = root / "commit-pin.py"
    value = ast.literal_eval(pin.read_text()) if pin.exists() else {
        "schema": 1, "date": "2026-10-01", "packages": {}
    }
    value["packages"][name] = {"sources": sources}
    pin.write_text(repr(value))


class RecipeRunner:
    def run(self, root, source, output, arguments, environment, log):
        Path(log).write_text(repr(arguments))
        if arguments[0] == "install":
            target = Path(output) / "usr/share" / arguments[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(arguments[1])


def setup_repo(tmp_path):
    repository = tmp_path / "repository"
    packages = repository / "project" / "package"
    packages.mkdir(parents=True)
    recipe(packages, "compiler-first")
    recipe(packages, "compiler-second")
    recipe(packages, "library")
    recipe(packages, "consumer", runtime=("library",))
    builder = ImageBuild(package_dir=packages, state_dir=tmp_path / "state", runner=RecipeRunner())
    host = tmp_path / "host"
    host.mkdir()
    (host / "seed").write_text("seed")
    seed = builder.import_bootstrap(host, {"fixture": True})
    toolchain = builder.bootstrap(seed, [["compiler-first"], ["compiler-second"]])
    return repository, packages, builder, toolchain


def request(operation_id, operation, arguments, revision="a" * 40, predecessor=None):
    value = {
        "schema": REQUEST_SCHEMA,
        "operation_id": operation_id,
        "operation": operation,
        "source": {"repository": "zog144/image-build", "revision": revision},
        "arguments": arguments,
    }
    if predecessor is not None:
        value["predecessor"] = predecessor
    return value


def adapter(repository, builder, revision="a" * 40):
    return RemoteOperations(
        builder,
        repository_root=repository,
        source_repository="zog144/image-build",
        source_revision=revision,
    )


def test_recipe_inspection_and_dependency_resolution(tmp_path):
    repository, _, builder, _ = setup_repo(tmp_path)
    remote = adapter(repository, builder)

    validated = remote.execute(request("validate", "recipe.validate", {"package": "consumer"}))
    assert validated["schema"] == RESULT_SCHEMA
    assert validated["status"] == "completed"

    inspected = remote.execute(request("inspect", "package.inspect", {"package": "consumer"}))
    assert inspected["recipe_identity"]
    assert inspected["artifacts"]["runtime_dependencies"] == ["library"]

    dependencies = remote.execute(request(
        "dependencies", "dependencies.resolve", {"targets": ["consumer"]}
    ))
    assert dependencies["artifacts"]["dependency_order"][-2:] == ["library", "consumer"]


def test_invalid_recipe_and_missing_package_are_bounded_failures(tmp_path):
    repository, packages, builder, _ = setup_repo(tmp_path)
    remote = adapter(repository, builder)
    missing = remote.execute(request("missing", "package.inspect", {"package": "absent"}))
    assert missing["status"] == "failed"
    assert missing["terminal_outcome"] == "request-error"

    (packages / "consumer" / "build.py").write_text("{'build': [['cc']]}")
    invalid = remote.execute(request("invalid", "recipe.validate", {"package": "consumer"}))
    assert invalid["status"] == "failed"
    assert invalid["failure"]["type"] == "ImageBuildError"


def test_duplicate_operation_rejects_changed_input(tmp_path):
    repository, _, builder, _ = setup_repo(tmp_path)
    remote = adapter(repository, builder)
    first = request("same-id", "package.inspect", {"package": "consumer"})
    assert remote.execute(first)["status"] == "completed"
    changed = request("same-id", "package.inspect", {"package": "library"})
    with pytest.raises(ImageBuildError, match="different input"):
        remote.execute(changed)


def test_remote_submit_persists_pipeline_identity_before_pending_return(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)

    def pending(request):
        raise KeyboardInterrupt("caller disconnected")

    # Simulate a durable controller handoff that has not completed.
    builder.runner = BoxControlRunner(execute=pending)
    remote = adapter(repository, builder)
    result = remote.execute(request(
        "build-consumer",
        "pipeline.submit",
        {"mode": "image", "selection": toolchain.generation, "targets": ["consumer"]},
    ))
    assert result["status"] == "pending"
    binding = json.loads(
        (builder.state / "image-build/remote-operations/build-consumer/binding.json").read_text()
    )
    pipeline = builder.inspect_pipeline(binding["pipeline_id"])
    assert pipeline["owner"]["operation_id"] == "build-consumer"
    assert pipeline["owner"]["source_revision"] == "a" * 40

    # Repeating the exact client request discovers the same pipeline.
    again = remote.execute(request(
        "build-consumer",
        "pipeline.submit",
        {"mode": "image", "selection": toolchain.generation, "targets": ["consumer"]},
    ))
    assert again["pipeline_id"] == result["pipeline_id"]


def test_terminal_failed_build_requires_explicit_new_retry_and_can_use_new_revision(tmp_path):
    repository, packages, builder, toolchain = setup_repo(tmp_path)

    def fail_compile(build_request):
        return BuildExecutionResult(
            "runtime", "invocation", 7 if build_request.command[0] == "compile" else 0,
            True, "journal:fixture",
        )

    builder.runner = BoxControlRunner(execute=fail_compile)
    first_remote = adapter(repository, builder, "a" * 40)
    failed = first_remote.execute(request(
        "attempt-a",
        "pipeline.submit",
        {"mode": "image", "selection": toolchain.generation, "targets": ["library"]},
        revision="a" * 40,
    ))
    assert failed["status"] == "failed"
    assert "pipeline.retry" in failed["allowed_next_operations"]

    # A corrected commit may carry changed recipe bytes, but the old pipeline stays frozen.
    recipe_path = packages / "library" / "build.py"
    recipe_path.write_text(repr({
        "build": [["compile-fixed", "library"]],
        "install": [["install", "library"]],
    }))

    def succeed(build_request):
        if build_request.command[0] == "install":
            target = build_request.output / "usr/share/library"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("library")
        return BuildExecutionResult("runtime", "invocation", 0, True, "journal:fixture")

    builder.runner = BoxControlRunner(execute=succeed)
    second_remote = adapter(repository, builder, "b" * 40)
    retried = second_remote.execute(request(
        "attempt-b",
        "pipeline.retry",
        {"mode": "image", "selection": toolchain.generation, "targets": ["library"]},
        revision="b" * 40,
        predecessor="attempt-a",
    ))
    assert retried["status"] == "completed"
    assert retried["predecessor"] == "attempt-a"
    assert retried["pipeline_id"] != failed["pipeline_id"]
    assert builder.inspect_pipeline(failed["pipeline_id"])["status"] == "released"


def test_resume_refuses_a_different_deployed_revision(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    builder.runner = BoxControlRunner(execute=lambda request: (_ for _ in ()).throw(KeyboardInterrupt()))
    first = adapter(repository, builder, "a" * 40)
    submitted = first.execute(request(
        "owned",
        "pipeline.submit",
        {"mode": "image", "selection": toolchain.generation, "targets": ["library"]},
    ))
    second = adapter(repository, builder, "b" * 40)
    result = second.execute(request(
        "resume-wrong",
        "pipeline.resume",
        {"pipeline_id": submitted["pipeline_id"]},
        revision="b" * 40,
    ))
    assert result["status"] == "failed"
    assert "originally bound" in result["failure"]["reason"]


def test_diagnostic_definition_rejects_shell_and_network_escape(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    root = repository / "project" / "diagnostic" / "bad"
    root.mkdir(parents=True)
    (root / "diagnostic.sh").write_text("#!/bin/sh\ntrue\n")
    (root / "diagnostic.json").write_text(json.dumps({
        "schema": 1,
        "script": "diagnostic.sh",
        "interpreter": "/bin/sh",
        "timeout_seconds": 10,
        "memory_maximum_bytes": 1000000,
        "thread_count_maximum": 4,
        "cpu_weight": 10,
        "output_limit_bytes": 1024,
        "outputs": [],
    }))
    remote = adapter(repository, builder)
    result = remote.execute(request(
        "diagnostic-bad",
        "diagnostic.submit",
        {"diagnostic": "bad", "generation": toolchain.generation, "argv": []},
    ))
    assert result["status"] == "failed"
    assert "Python source" in result["failure"]["reason"]


def test_source_binding_must_match_deployed_revision(tmp_path):
    repository, _, builder, _ = setup_repo(tmp_path)
    remote = adapter(repository, builder, "a" * 40)
    with pytest.raises(ImageBuildError, match="differs from deployed"):
        remote.execute(request(
            "wrong-source",
            "package.inspect",
            {"package": "library"},
            revision="b" * 40,
        ))


def test_machine_result_schema_has_stable_core_fields(tmp_path):
    repository, _, builder, _ = setup_repo(tmp_path)
    result = adapter(repository, builder).execute(
        request("schema", "package.inspect", {"package": "library"})
    )
    assert set(result) == {
        "schema", "operation_id", "operation_type", "source_repository",
        "source_revision", "recipe_identity", "pipeline_id", "attempt_ids",
        "selected_generation", "package", "stage", "phase", "status",
        "terminal_outcome", "failure", "controller_jobs", "log_locators",
        "artifacts", "provenance", "uncertainty", "missing_evidence",
        "allowed_next_operations", "predecessor",
    }


def test_cancel_releases_owned_prepared_pipeline_without_retry(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    remote = adapter(repository, builder)
    record = builder.prepare_pipeline(
        "image",
        toolchain,
        owner={
            "contract": REQUEST_SCHEMA,
            "operation_id": "prepared-owner",
            "source_repository": "zog144/image-build",
            "source_revision": "a" * 40,
        },
        targets=["library"],
    )
    cancelled = remote.execute(request(
        "cancel-prepared",
        "pipeline.cancel",
        {"pipeline_id": record["pipeline_id"]},
    ))
    assert cancelled["status"] == "released"
    assert cancelled["terminal_outcome"] == "released"
    assert cancelled["allowed_next_operations"] == ["pipeline.inspect"]
    assert builder.inspect_pipeline(record["pipeline_id"])["status"] == "released"


def test_cancel_refuses_pipeline_owned_by_other_source_revision(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    record = builder.prepare_pipeline(
        "image",
        toolchain,
        owner={
            "contract": REQUEST_SCHEMA,
            "operation_id": "foreign-owner",
            "source_repository": "zog144/image-build",
            "source_revision": "b" * 40,
        },
        targets=["library"],
    )
    result = adapter(repository, builder, "a" * 40).execute(request(
        "cancel-foreign",
        "pipeline.cancel",
        {"pipeline_id": record["pipeline_id"]},
    ))
    assert result["status"] == "failed"
    assert "originally bound" in result["failure"]["reason"]
    assert builder.inspect_pipeline(record["pipeline_id"])["status"] == "prepared"


def test_state_local_pipeline_serialization_allows_independent_lanes(tmp_path):
    repository_a, _, builder_a, toolchain_a = setup_repo(tmp_path / "lane-a")
    repository_b, _, builder_b, toolchain_b = setup_repo(tmp_path / "lane-b")
    first = builder_a.prepare_pipeline(
        "image",
        toolchain_a,
        owner={
            "contract": REQUEST_SCHEMA,
            "operation_id": "lane-a",
            "source_repository": "zog144/image-build",
            "source_revision": "a" * 40,
        },
        targets=["library"],
    )
    with pytest.raises(ImageBuildError, match="unfinished pipeline"):
        builder_a.prepare_pipeline(
            "image",
            toolchain_a,
            owner={
                "contract": REQUEST_SCHEMA,
                "operation_id": "lane-a-second",
                "source_repository": "zog144/image-build",
                "source_revision": "a" * 40,
            },
            targets=["consumer"],
        )
    second = builder_b.prepare_pipeline(
        "image",
        toolchain_b,
        owner={
            "contract": REQUEST_SCHEMA,
            "operation_id": "lane-b",
            "source_repository": "zog144/image-build",
            "source_revision": "a" * 40,
        },
        targets=["library"],
    )
    assert first["pipeline_id"] != second["pipeline_id"]
    assert builder_a.state != builder_b.state
    assert repository_a != repository_b


def test_concurrent_duplicate_submit_reuses_one_durable_pipeline(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    remote = adapter(repository, builder)
    payload = request(
        "concurrent-submit",
        "pipeline.submit",
        {"mode": "image", "selection": toolchain.generation, "targets": ["library"]},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(remote.execute, [payload, payload]))
    assert {item["pipeline_id"] for item in results} == {results[0]["pipeline_id"]}
    owned = []
    for path in (builder.state / "image-build/pipelines").glob("*/pipeline.json"):
        record = json.loads(path.read_text())
        if (record.get("owner") or {}).get("operation_id") == "concurrent-submit":
            owned.append(record)
    assert len(owned) == 1


def test_unresolved_controller_cleanup_is_not_retryable_failure(tmp_path):
    repository, _, builder, toolchain = setup_repo(tmp_path)
    remote = adapter(repository, builder)
    record = builder.prepare_pipeline(
        "image",
        toolchain,
        owner={
            "contract": REQUEST_SCHEMA,
            "operation_id": "cleanup-owner",
            "source_repository": "zog144/image-build",
            "source_revision": "a" * 40,
        },
        targets=["library"],
    )
    attempt = builder.state / "image-build/attempts/cleanup-pending-fixture"
    attempt.mkdir(parents=True)
    (attempt / "failure.observation.json").write_text(json.dumps({
        "job_id": "fixture-job",
        "state": "completed",
        "outcome": "nonzero-exit",
        "exit_code": 7,
        "journal_reference": "journal:fixture-job",
        "process_cleanup_complete": False,
    }))
    record["attempts"] = {"image": attempt.name}
    record["status"] = "pending"
    record["error"] = "controller cleanup remains unresolved"
    pipeline_path = (
        builder.state
        / "image-build/pipelines"
        / record["pipeline_id"]
        / "pipeline.json"
    )
    pipeline_path.write_text(json.dumps(record))
    result = remote.execute(request(
        "inspect-cleanup-pending",
        "pipeline.inspect",
        {"pipeline_id": record["pipeline_id"]},
    ))
    assert result["status"] == "pending"
    assert "pipeline.retry" not in result["allowed_next_operations"]
    assert "pipeline.cancel" in result["allowed_next_operations"]


def test_generation_inspection_bounds_inventory_without_losing_digest(tmp_path):
    repository, _, builder, _ = setup_repo(tmp_path)
    root = tmp_path / "large-generation-root"
    root.mkdir()
    for index in range(MAX_INVENTORY_ITEMS + 17):
        (root / f"file-{index:03d}").write_text(str(index))
    selection = builder.import_bootstrap(root, {"fixture": "large"})
    result = adapter(repository, builder).execute(request(
        "inspect-large-generation",
        "generation.inspect",
        {"generation": selection.generation},
    ))
    artifacts = result["artifacts"]
    assert len(artifacts["inventory"]) == MAX_INVENTORY_ITEMS
    assert artifacts["inventory_count"] == MAX_INVENTORY_ITEMS + 17
    assert artifacts["inventory_truncated"] is True
    assert artifacts["inventory_digest"].startswith("sha256:")
    assert artifacts["generation_manifest"].endswith("/manifest.json")
