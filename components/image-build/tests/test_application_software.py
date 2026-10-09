import json
import os

import pytest

from zog.image_build.application_software import (
    ApplicationSoftwareStore,
    MOUNT_CONTRACT,
    compatibility_gaps,
)
from zog.image_build.errors import ImageBuildError


def descriptor(*, architecture="x86_64", version="3.12.7", libraries=()):
    return {
        "schema": 1,
        "mount_contract": MOUNT_CONTRACT,
        "architecture": architecture,
        "python": {
            "implementation": "cpython",
            "version": version,
            "soabi": "cpython-312-x86_64-linux-gnu",
        },
        "libraries": list(libraries),
    }


def begin(store, operation="station-a", **changes):
    values = {
        "application": "station-access",
        "revision": "git:" + "a" * 40,
        "sources": [
            {
                "name": "station-access",
                "url": "https://example.invalid/station-access.tar.xz",
                "sha256": "1" * 64,
            }
        ],
        "compatibility_requirements": descriptor(libraries=("libssl.so.3",)),
        "notices": ["notices/COPYRIGHT"],
        "provenance": {"source_revision": "a" * 40},
    }
    values.update(changes)
    return store.begin(operation, **values)


def populate(root):
    (root / "backend").mkdir()
    (root / "backend" / "manage.py").write_text("print('station')\n")
    (root / "notices").mkdir()
    (root / "notices" / "COPYRIGHT").write_text("fixture notice\n")


def test_publish_resolve_and_controller_binding(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    populate(operation.root)

    published = store.finalize(operation.operation)
    assert published.artifact.startswith("sha256:")
    assert published.manifest["application"] == "station-access"
    assert published.manifest["mount_contract"] == MOUNT_CONTRACT
    assert published.root.joinpath("backend", "manage.py").is_file()

    resolved = store.resolve(published.artifact)
    assert resolved.artifact == published.artifact
    assert resolved.manifest == published.manifest

    binding = store.binding(published.artifact)
    assert binding["artifact"] == published.artifact
    assert binding["application"] == "station-access"
    assert binding["root"] == str(published.root.resolve())
    assert binding["mount_contract"] == MOUNT_CONTRACT


def test_completed_operation_is_idempotent(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    populate(operation.root)
    first = store.finalize(operation.operation)

    resumed = begin(store)
    assert resumed.artifact == first.artifact
    second = store.finalize(operation.operation)
    assert second.artifact == first.artifact
    assert second.reused


def test_changed_operation_intent_is_rejected(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    begin(store)
    with pytest.raises(ImageBuildError, match="operation changed"):
        begin(store, revision="git:" + "b" * 40)


def test_lost_result_recovers_same_published_artifact(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    populate(operation.root)
    first = store.finalize(operation.operation)

    result = (
        store.root / "operations" / operation.operation / "result.json"
    )
    result.unlink()
    second = store.finalize(operation.operation)
    assert second.artifact == first.artifact
    assert second.reused


def test_frozen_staging_mutation_is_rejected(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    populate(operation.root)
    path = store.root / "operations" / operation.operation
    intent = json.loads((path / "intent.json").read_text())
    store._freeze(path, intent)
    (operation.root / "backend" / "manage.py").write_text("changed\n")
    with pytest.raises(ImageBuildError, match="changed after freeze|differs from frozen"):
        store.finalize(operation.operation)


def test_tampered_published_artifact_is_detected(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    populate(operation.root)
    published = store.finalize(operation.operation)
    (published.root / "backend" / "manage.py").write_text("tampered\n")
    with pytest.raises(ImageBuildError, match="installed files changed"):
        store.resolve(published.artifact)


def test_notice_must_be_retained_regular_file(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store)
    (operation.root / "backend").mkdir()
    (operation.root / "backend" / "manage.py").write_text("ok\n")
    with pytest.raises(ImageBuildError, match="notice"):
        store.finalize(operation.operation)


def test_symlink_must_not_escape_artifact(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store, notices=())
    (operation.root / "backend").mkdir()
    os.symlink("../../outside", operation.root / "backend" / "escape")
    with pytest.raises(ImageBuildError, match="symlink escapes"):
        store.finalize(operation.operation)


def test_source_credentials_and_provenance_secrets_are_rejected(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    with pytest.raises(ImageBuildError, match="credentials"):
        begin(
            store,
            sources=[
                {
                    "url": "https://user:pass@example.invalid/source.tar.xz",
                    "sha256": "1" * 64,
                }
            ],
        )
    with pytest.raises(ImageBuildError, match="credentials"):
        begin(store, operation="station-b", provenance={"api_token": "secret"})


def test_compatibility_is_conservative(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    operation = begin(store, notices=())
    (operation.root / "app").write_text("fixture\n")
    artifact = store.finalize(operation.operation)

    compatible = descriptor(libraries=("libssl.so.3", "libc.so.6"))
    assert compatibility_gaps(artifact.manifest["compatibility"], compatible) == ()
    store.require_compatible(artifact.artifact, compatible)

    wrong_python = descriptor(version="3.13.0", libraries=("libssl.so.3",))
    assert "python" in compatibility_gaps(
        artifact.manifest["compatibility"], wrong_python
    )
    with pytest.raises(ImageBuildError, match="incompatible"):
        store.require_compatible(artifact.artifact, wrong_python)

    wrong_arch = descriptor(
        architecture="aarch64", libraries=("libssl.so.3",)
    )
    with pytest.raises(ImageBuildError, match="architecture"):
        store.require_compatible(artifact.artifact, wrong_arch)


def test_same_content_and_metadata_deduplicate_across_operations(tmp_path):
    store = ApplicationSoftwareStore(tmp_path / "state")
    first_operation = begin(store, "station-a")
    populate(first_operation.root)
    first = store.finalize(first_operation.operation)

    second_operation = begin(store, "station-b")
    populate(second_operation.root)
    second = store.finalize(second_operation.operation)
    assert second.artifact == first.artifact
    assert second.reused
