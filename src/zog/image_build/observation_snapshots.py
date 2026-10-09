"""Owner publication and discovery for canonical generation observation snapshots."""
import argparse
import json
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import ensure_directory, sync_directory, write_json


SCHEMA = 1


def _library():
    try:
        import zog.build_record as build_record
    except ImportError:
        raise ImageBuildError(
            "observation snapshot publication requires build-record 0.7.2 or newer"
        ) from None
    version = getattr(build_record, "__version__", "0")
    try:
        parsed = tuple(int(part) for part in version.split(".")[:3])
    except ValueError:
        parsed = ()
    if parsed < (0, 7, 2) or not callable(
        getattr(build_record, "ingest_image_build_snapshot", None)
    ):
        raise ImageBuildError(
            "observation snapshot publication requires build-record 0.7.2 or newer"
        )
    return build_record


def _generation(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ImageBuildError("invalid owner generation identity")
    return value


def _read(path, label):
    path = Path(path)
    if path.is_symlink():
        raise ImageBuildError(label + " must not be a symlink")
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as error:
        raise ImageBuildError("invalid " + label) from error
    if not isinstance(value, dict):
        raise ImageBuildError("invalid " + label)
    return value


def _owner_directory(p, generation):
    return p.root / "observation-snapshots" / _generation(generation)


def _expected_generation_id(p, generation):
    return json.dumps([p.host_id, p.project_id, generation], separators=(",", ":"))


def _receipt_from_record(p, generation, snapshot, record):
    data = record["data"]
    return {
        "schema": SCHEMA,
        "host_id": p.host_id,
        "project_id": p.project_id,
        "generation": generation,
        "generation_record": data["generation"],
        "snapshot": snapshot,
        "root_inventory_digest": data["root_inventory_digest"],
        "record_set_digest": data["record_set_digest"],
    }


def _verify_receipt(p, value, *, generation=None, selection=None):
    expected_keys = {
        "schema",
        "host_id",
        "project_id",
        "generation",
        "generation_record",
        "snapshot",
        "root_inventory_digest",
        "record_set_digest",
    }
    if set(value) != expected_keys or value.get("schema") != SCHEMA:
        raise ImageBuildError("unsupported observation snapshot owner pointer")
    owner_generation = _generation(value.get("generation"))
    if generation is not None and owner_generation != _generation(generation):
        raise ImageBuildError("observation snapshot generation differs")
    if value.get("host_id") != p.host_id or value.get("project_id") != p.project_id:
        raise ImageBuildError("observation snapshot owner scope differs")
    snapshot = value.get("snapshot")
    if (
        not isinstance(snapshot, str)
        or len(snapshot) != 71
        or not snapshot.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in snapshot[7:])
    ):
        raise ImageBuildError("invalid observation snapshot identity")
    try:
        record = p.store.get(snapshot)
        if record.get("kind") != "generation-observation-snapshot":
            raise ImageBuildError(
                "owner-selected record is not an observation snapshot"
            )
        data = record["data"]
        if (
            data["generation"] != value["generation_record"]
            or data["generation_id"] != _expected_generation_id(p, owner_generation)
            or data["root_inventory_digest"] != value["root_inventory_digest"]
            or data["record_set_digest"] != value["record_set_digest"]
        ):
            raise ImageBuildError(
                "observation snapshot owner pointer differs from canonical record"
            )
        if selection is not None:
            pointer = selection.manifest.get("build_record")
            if (
                selection.generation != owner_generation
                or not isinstance(pointer, dict)
                or pointer.get("record") != value["generation_record"]
            ):
                raise ImageBuildError(
                    "observation snapshot selection binding differs"
                )
        # Store.bundle performs canonical graph inspection and rejects missing references.
        p.store.bundle([snapshot])
    except ImageBuildError:
        raise
    except Exception as error:
        raise ImageBuildError(
            "canonical observation snapshot is unavailable or invalid"
        ) from error
    return value


def selected(p, generation, *, selection=None):
    """Return the exact owner-selected snapshot receipt for one generation."""
    directory = _owner_directory(p, generation)
    path = directory / "selected.json"
    if not path.exists():
        return None
    value = _verify_receipt(
        p,
        _read(path, "observation snapshot selection"),
        generation=generation,
        selection=selection,
    )
    publication = directory / "publications" / (value["snapshot"][7:] + ".json")
    if not publication.exists() or _read(
        publication, "observation snapshot publication receipt"
    ) != value:
        raise ImageBuildError(
            "selected observation snapshot publication receipt is unavailable or differs"
        )
    return value


def _records(p, selection, envelope):
    library = _library()
    from .generation_provenance import verify

    bundle = verify(p, selection)
    try:
        records = library.ingest_image_build_snapshot(envelope, bundle)
    except Exception as error:
        raise ImageBuildError(
            "cannot canonicalize image-build observation snapshot"
        ) from error
    if not records or records[-1].get("kind") != "generation-observation-snapshot":
        raise ImageBuildError(
            "build-record did not return a terminal observation snapshot"
        )
    ids = [library.record_id(record) for record in records]
    if len(ids) != len(set(ids)):
        raise ImageBuildError("duplicate canonical observation snapshot records")
    return records, ids


def _prepare(p, selection, directory, *, readelf):
    from .integration_observations import export_generation

    envelope = export_generation(p, selection, readelf=readelf)
    records, ids = _records(p, selection, envelope)
    snapshot = ids[-1]
    record = records[-1]
    current = selected(p, selection.generation, selection=selection)
    intent = {
        "schema": SCHEMA,
        "host_id": p.host_id,
        "project_id": p.project_id,
        "generation": selection.generation,
        "generation_record": selection.manifest["build_record"]["record"],
        "previous_snapshot": current["snapshot"] if current else None,
        "snapshot": snapshot,
        "root_inventory_digest": record["data"]["root_inventory_digest"],
        "record_set_digest": record["data"]["record_set_digest"],
        "record_ids": ids,
        "envelope": envelope,
    }
    write_json(directory / "pending.json", intent)
    return intent, records


def _resume_intent(p, selection, intent):
    expected = {
        "schema",
        "host_id",
        "project_id",
        "generation",
        "generation_record",
        "previous_snapshot",
        "snapshot",
        "root_inventory_digest",
        "record_set_digest",
        "record_ids",
        "envelope",
    }
    if set(intent) != expected or intent.get("schema") != SCHEMA:
        raise ImageBuildError(
            "unsupported observation snapshot publication intent"
        )
    if (
        intent.get("host_id") != p.host_id
        or intent.get("project_id") != p.project_id
        or intent.get("generation") != selection.generation
        or intent.get("generation_record")
        != selection.manifest.get("build_record", {}).get("record")
    ):
        raise ImageBuildError(
            "observation snapshot publication intent scope differs"
        )
    previous = intent.get("previous_snapshot")
    if previous is not None:
        if (
            not isinstance(previous, str)
            or len(previous) != 71
            or not previous.startswith("sha256:")
            or any(c not in "0123456789abcdef" for c in previous[7:])
        ):
            raise ImageBuildError(
                "invalid previous observation snapshot identity"
            )
    records, ids = _records(p, selection, intent["envelope"])
    if ids != intent.get("record_ids") or ids[-1] != intent.get("snapshot"):
        raise ImageBuildError(
            "frozen observation snapshot publication identity changed"
        )
    record = records[-1]
    if (
        record["data"]["root_inventory_digest"]
        != intent.get("root_inventory_digest")
        or record["data"]["record_set_digest"] != intent.get("record_set_digest")
    ):
        raise ImageBuildError(
            "frozen observation snapshot publication record changed"
        )
    return records


def _write_immutable(path, value, label):
    path = Path(path)
    if path.exists() and _read(path, label) != value:
        raise ImageBuildError("immutable " + label + " differs")
    write_json(path, value)


def publish(p, selection, *, refresh=False, readelf="readelf"):
    """Publish/select one canonical snapshot, resuming an exact pending intent first."""
    if p.generation_contract is None:
        raise ImageBuildError(
            "observation snapshots require canonical generation provenance"
        )
    from .generation_provenance import verify

    verify(p, selection)
    directory = _owner_directory(p, selection.generation)
    ensure_directory(directory / "publications")
    pending = directory / "pending.json"

    if pending.exists():
        intent = _read(pending, "observation snapshot publication intent")
        records = _resume_intent(p, selection, intent)
    else:
        current = selected(p, selection.generation, selection=selection)
        if current is not None and not refresh:
            return current
        intent, records = _prepare(p, selection, directory, readelf=readelf)
        if current is not None and intent["snapshot"] == current["snapshot"]:
            pending.unlink(missing_ok=True)
            sync_directory(directory)
            return current

    for record, expected_id in zip(records, intent["record_ids"]):
        actual = p.store.put(record)
        if actual != expected_id:
            raise ImageBuildError(
                "canonical observation snapshot record identity changed"
            )

    snapshot = intent["snapshot"]
    canonical_record = p.store.get(snapshot)
    receipt = _receipt_from_record(
        p, selection.generation, snapshot, canonical_record
    )
    if (
        receipt["generation_record"] != intent["generation_record"]
        or receipt["root_inventory_digest"] != intent["root_inventory_digest"]
        or receipt["record_set_digest"] != intent["record_set_digest"]
    ):
        raise ImageBuildError(
            "published observation snapshot differs from frozen intent"
        )
    _verify_receipt(
        p,
        receipt,
        generation=selection.generation,
        selection=selection,
    )

    publication = (
        directory / "publications" / (snapshot[7:] + ".json")
    )
    _write_immutable(
        publication, receipt, "observation snapshot publication receipt"
    )

    selected_path = directory / "selected.json"
    if selected_path.exists():
        current = _verify_receipt(
            p,
            _read(selected_path, "observation snapshot selection"),
            generation=selection.generation,
            selection=selection,
        )
        allowed = {snapshot}
        if intent["previous_snapshot"] is not None:
            allowed.add(intent["previous_snapshot"])
        if current["snapshot"] not in allowed:
            raise ImageBuildError(
                "observation snapshot selection changed during publication recovery"
            )
    elif intent["previous_snapshot"] is not None:
        raise ImageBuildError(
            "previous observation snapshot selection disappeared during publication"
        )
    write_json(selected_path, receipt)

    # A lost selected-pointer response leaves pending.json in place, so retry
    # replays the same frozen snapshot. Cleanup follows the durable selection.
    pending.unlink(missing_ok=True)
    sync_directory(directory)
    return receipt


def publications(p, generation=None, *, limit=100):
    """Discover only snapshots explicitly published by this owner; never scan records/."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ImageBuildError(
            "observation snapshot discovery limit must be 1..1000"
        )
    root = p.root / "observation-snapshots"
    if generation is not None:
        directories = [_owner_directory(p, generation)]
    elif not root.exists():
        directories = []
    else:
        directories = [
            path
            for path in sorted(root.iterdir())
            if path.is_dir()
            and not path.is_symlink()
            and len(path.name) == 64
            and all(c in "0123456789abcdef" for c in path.name)
        ]

    result = []
    for directory in directories:
        if not directory.exists():
            continue
        current = selected(p, directory.name)
        publication_dir = directory / "publications"
        if not publication_dir.exists():
            continue
        for path in sorted(publication_dir.glob("*.json")):
            if len(result) >= limit:
                raise ImageBuildError(
                    "observation snapshot discovery limit exceeded"
                )
            value = _verify_receipt(
                p,
                _read(path, "observation snapshot publication receipt"),
                generation=directory.name,
            )
            if path.name != value["snapshot"][7:] + ".json":
                raise ImageBuildError(
                    "observation snapshot publication filename differs"
                )
            result.append(
                dict(
                    value,
                    selected=bool(
                        current
                        and current["snapshot"] == value["snapshot"]
                    ),
                )
            )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--provenance-config", required=True)
    sub = parser.add_subparsers(dest="operation", required=True)

    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("selection")
    publish_parser.add_argument("--readelf", default="readelf")

    selected_parser = sub.add_parser("selected")
    selected_parser.add_argument("generation")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("generation", nargs="?")
    list_parser.add_argument("--limit", type=int, default=100)

    args = parser.parse_args()
    from .provenance import Provenance

    config = json.loads(Path(args.provenance_config).read_text())
    p = Provenance.from_configuration(
        Path(args.state), config.get("provenance", config)
    )
    if args.operation == "publish":
        from .engine import read_selection

        value = publish(
            p,
            read_selection(args.selection),
            refresh=True,
            readelf=args.readelf,
        )
    elif args.operation == "selected":
        value = selected(p, args.generation)
    else:
        value = {
            "schema": SCHEMA,
            "snapshots": publications(
                p, args.generation, limit=args.limit
            ),
        }
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
