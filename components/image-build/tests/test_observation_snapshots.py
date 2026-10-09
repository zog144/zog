import json
from pathlib import Path
from unittest.mock import patch

import pytest
pytest.importorskip("zog.build_record")

from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import write_json
from zog.image_build import verification_observations as vo


def unpublished_generation(tmp_path):
    from test_installed_verification import scenario, capture
    from zog.image_build import generation_provenance as gp

    s = scenario(tmp_path)
    report = capture(s)
    pointer = gp.finish(
        s.p, s.attempt, s.binding, s.root, verification=[report]
    )
    with patch("zog.image_build.observation_snapshots.publish", return_value=None):
        selection = s.builder._publish(
            s.root,
            s.owner,
            "image",
            dict(
                packages=s.built,
                build_record=pointer,
                verification_execution=s.execution,
            ),
        )
    return s, selection


def add_failed_observation(s, name="later-failure"):
    prepared = json.loads((s.check / "prepared.json").read_text())
    folder = s.check.parent / name
    folder.mkdir()
    # A later execution has its own invocation identity; reusing the original
    # PASS invocation with a FAIL outcome is conflicting evidence, not a retry.
    raw = dict(s.execution, exit_code=2, invocation_id=name + "-invocation")
    raw["request"] = dict(
        raw["request"], root=str((folder / "root").resolve())
    )
    write_json(folder / "command-0.execution.json", raw)
    return vo.capture(s.builder, folder, prepared, 0)


def test_normal_publication_selects_canonical_snapshot(tmp_path):
    from test_integration_observations import generation

    s, selection = generation(tmp_path)
    receipt = s.builder.selected_observation_snapshot(selection.generation)
    assert receipt["generation"] == selection.generation
    assert (
        receipt["generation_record"]
        == selection.manifest["build_record"]["record"]
    )
    assert (
        s.p.store.get(receipt["snapshot"])["kind"]
        == "generation-observation-snapshot"
    )
    rows = s.builder.observation_snapshots(selection.generation)
    assert rows == [dict(receipt, selected=True)]


def test_store_response_loss_replays_frozen_snapshot_before_new_observations(
    tmp_path, monkeypatch
):
    s, selection = unpublished_generation(tmp_path)
    original = s.p.store.put
    lost = []

    def lose(record):
        identity = original(record)
        if (
            record["kind"] == "generation-observation-snapshot"
            and not lost
        ):
            lost.append(identity)
            raise OSError("lost canonical snapshot response")
        return identity

    monkeypatch.setattr(s.p.store, "put", lose)
    with pytest.raises(OSError, match="lost canonical snapshot response"):
        s.builder.publish_observation_snapshot(selection)
    assert lost
    pending = (
        s.p.root
        / "observation-snapshots"
        / selection.generation
        / "pending.json"
    )
    frozen = json.loads(pending.read_text())
    assert frozen["snapshot"] == lost[0]

    monkeypatch.setattr(s.p.store, "put", original)
    add_failed_observation(s)
    recovered = s.builder.publish_observation_snapshot(selection)
    assert recovered["snapshot"] == lost[0]
    assert not pending.exists()

    newer = s.builder.publish_observation_snapshot(selection)
    assert newer["snapshot"] != recovered["snapshot"]
    assert (
        s.p.store.get(recovered["snapshot"])["kind"]
        == "generation-observation-snapshot"
    )
    rows = s.builder.observation_snapshots(selection.generation)
    assert {row["snapshot"] for row in rows} == {
        recovered["snapshot"],
        newer["snapshot"],
    }
    assert [
        row["snapshot"] for row in rows if row["selected"]
    ] == [newer["snapshot"]]


def test_selected_pointer_response_loss_replays_same_snapshot(
    tmp_path, monkeypatch
):
    s, selection = unpublished_generation(tmp_path)
    import zog.image_build.observation_snapshots as snapshots

    original = snapshots.write_json
    tripped = []

    def lose(path, value):
        original(path, value)
        path = Path(path)
        if path.name == "selected.json" and not tripped:
            tripped.append(value["snapshot"])
            raise OSError("lost selected pointer response")

    monkeypatch.setattr(snapshots, "write_json", lose)
    with pytest.raises(OSError, match="lost selected pointer response"):
        s.builder.publish_observation_snapshot(selection)

    monkeypatch.setattr(snapshots, "write_json", original)
    recovered = s.builder.publish_observation_snapshot(selection)
    assert recovered["snapshot"] == tripped[0]


def test_automatic_reuse_does_not_advance_selected_snapshot(tmp_path):
    from test_integration_observations import generation

    s, selection = generation(tmp_path)
    first = s.builder.selected_observation_snapshot(selection.generation)
    add_failed_observation(s)

    automatic = s.builder._publish_observation_snapshot(selection)
    assert automatic["snapshot"] == first["snapshot"]

    refreshed = s.builder.publish_observation_snapshot(selection)
    assert refreshed["snapshot"] != first["snapshot"]


def test_tampered_owner_selection_is_not_repaired_by_discovery(tmp_path):
    from test_integration_observations import generation

    s, selection = generation(tmp_path)
    directory = (
        s.p.root / "observation-snapshots" / selection.generation
    )
    value = json.loads((directory / "selected.json").read_text())
    value["snapshot"] = "sha256:" + "0" * 64
    write_json(directory / "selected.json", value)

    with pytest.raises(ImageBuildError):
        s.builder.selected_observation_snapshot(selection.generation)
    with pytest.raises(ImageBuildError):
        s.builder.observation_snapshots(selection.generation)


def test_publication_discovery_never_infers_unpublished_store_record(
    tmp_path
):
    s, selection = unpublished_generation(tmp_path)
    from zog.image_build.integration_observations import export_generation
    import zog.build_record as build_record
    from zog.image_build.generation_provenance import verify

    envelope = export_generation(s.p, selection)
    records = build_record.ingest_image_build_snapshot(
        envelope, verify(s.p, selection)
    )
    for record in records:
        s.p.store.put(record)
    snapshot = build_record.record_id(records[-1])

    assert (
        s.p.store.get(snapshot)["kind"]
        == "generation-observation-snapshot"
    )
    assert (
        s.builder.selected_observation_snapshot(selection.generation)
        is None
    )
    assert s.builder.observation_snapshots(selection.generation) == []


def test_engine_reuse_preserves_owner_selected_snapshot(tmp_path):
    from test_integration_observations import generation

    s, selection = generation(tmp_path)
    first = s.builder.selected_observation_snapshot(selection.generation)
    add_failed_observation(s, "reuse-later-failure")
    details = {
        key: value
        for key, value in selection.manifest.items()
        if key not in {"schema", "generation", "kind", "inputs", "outputs"}
    }
    reused = s.builder._publish(
        selection.root,
        selection.manifest["inputs"],
        selection.manifest["kind"],
        details,
    )
    assert reused.generation == selection.generation
    assert reused.reused
    current = s.builder.selected_observation_snapshot(selection.generation)
    assert current["snapshot"] == first["snapshot"]


def test_prerequisite_store_response_loss_replays_frozen_snapshot(
    tmp_path, monkeypatch
):
    s, selection = unpublished_generation(tmp_path)
    original = s.p.store.put
    lost = []

    def lose_first(record):
        identity = original(record)
        if not lost:
            lost.append(identity)
            raise OSError("lost prerequisite store response")
        return identity

    monkeypatch.setattr(s.p.store, "put", lose_first)
    with pytest.raises(OSError, match="lost prerequisite store response"):
        s.builder.publish_observation_snapshot(selection)
    pending = (
        s.p.root
        / "observation-snapshots"
        / selection.generation
        / "pending.json"
    )
    frozen = json.loads(pending.read_text())
    monkeypatch.setattr(s.p.store, "put", original)
    add_failed_observation(s, "after-prerequisite-loss")
    recovered = s.builder.publish_observation_snapshot(selection)
    assert recovered["snapshot"] == frozen["snapshot"]


def test_publication_receipt_response_loss_replays_frozen_snapshot(
    tmp_path, monkeypatch
):
    s, selection = unpublished_generation(tmp_path)
    import zog.image_build.observation_snapshots as snapshots

    original = snapshots._write_immutable
    lost = []

    def lose_receipt(path, value, label):
        original(path, value, label)
        if label == "observation snapshot publication receipt" and not lost:
            lost.append(value["snapshot"])
            raise OSError("lost publication receipt response")

    monkeypatch.setattr(snapshots, "_write_immutable", lose_receipt)
    with pytest.raises(OSError, match="lost publication receipt response"):
        s.builder.publish_observation_snapshot(selection)
    pending = (
        s.p.root
        / "observation-snapshots"
        / selection.generation
        / "pending.json"
    )
    assert json.loads(pending.read_text())["snapshot"] == lost[0]

    monkeypatch.setattr(snapshots, "_write_immutable", original)
    add_failed_observation(s, "after-publication-receipt-loss")
    recovered = s.builder.publish_observation_snapshot(selection)
    assert recovered["snapshot"] == lost[0]


def test_generation_inspect_returns_exact_owner_selected_snapshot(tmp_path):
    from test_integration_observations import generation
    from zog.image_build.remote_operations import (
        REQUEST_SCHEMA,
        RemoteOperations,
    )

    s, selection = generation(tmp_path)
    receipt = s.builder.selected_observation_snapshot(selection.generation)
    remote = RemoteOperations(
        s.builder,
        repository_root=tmp_path,
        source_repository="zog144/image-build",
        source_revision="a" * 40,
    )
    result = remote.execute(
        {
            "schema": REQUEST_SCHEMA,
            "operation_id": "snapshot-inspect",
            "operation": "generation.inspect",
            "source": {
                "repository": "zog144/image-build",
                "revision": "a" * 40,
            },
            "arguments": {"generation": selection.generation},
        }
    )
    assert result["status"] == "completed"
    assert result["provenance"]["observation_snapshot"] == receipt
    assert result["provenance"]["build_trace"] == {
        "snapshot": receipt["snapshot"]
    }


def test_generation_inspect_reports_missing_owner_selection(tmp_path):
    from zog.image_build.remote_operations import (
        REQUEST_SCHEMA,
        RemoteOperations,
    )

    s, selection = unpublished_generation(tmp_path)
    remote = RemoteOperations(
        s.builder,
        repository_root=tmp_path,
        source_repository="zog144/image-build",
        source_revision="a" * 40,
    )
    result = remote.execute(
        {
            "schema": REQUEST_SCHEMA,
            "operation_id": "snapshot-missing",
            "operation": "generation.inspect",
            "source": {
                "repository": "zog144/image-build",
                "revision": "a" * 40,
            },
            "arguments": {"generation": selection.generation},
        }
    )
    assert result["status"] == "completed"
    assert "observation_snapshot" not in result["provenance"]
    assert {
        "kind": "observation-snapshot",
        "locator": selection.generation,
    } in result["missing_evidence"]


def test_retained_generation_snapshot_publication_does_not_rebuild_or_mutate(
    tmp_path,
):
    from zog.image_build.filesystem import inventory

    s, selection = unpublished_generation(tmp_path)
    manifest = selection.root.parent / "manifest.json"
    before_manifest = manifest.read_bytes()
    before_inventory = inventory(selection.root)
    receipt = s.builder.publish_observation_snapshot(selection)
    assert receipt["generation"] == selection.generation
    assert manifest.read_bytes() == before_manifest
    assert inventory(selection.root) == before_inventory


def test_owner_snapshot_public_shapes_are_stable(tmp_path):
    from test_integration_observations import generation

    s, selection = generation(tmp_path)
    receipt = s.builder.selected_observation_snapshot(selection.generation)
    assert set(receipt) == {
        "schema",
        "host_id",
        "project_id",
        "generation",
        "generation_record",
        "snapshot",
        "root_inventory_digest",
        "record_set_digest",
    }
    rows = s.builder.observation_snapshots(selection.generation)
    assert len(rows) == 1
    assert set(rows[0]) == set(receipt) | {"selected"}
