"""Caller-ordered history and relationship traversal over canonical snapshots."""
from .api import checked
from .model import TraceError, limit_value, paginate, response
from .snapshot_observations import (
    COVERAGE_FAMILIES, RECORD_ID, RELATIONS, _completeness_fields, _read_snapshot, _rows,
)

MAX_SEQUENCE = 100
FORWARD_SELECTORS = frozenset({"package", "artifact-path", "artifact-digest", "package-output"})
REVERSE_SELECTORS = frozenset({"package", "package-output", "soname", "path"})
RELATION_COVERAGE = {
    "needs-library": ("elf-interfaces",),
    "provides-soname": ("elf-interfaces",),
    "elf-interpreter": ("elf-interfaces",),
    "script-interpreter": ("script-interpreters",),
    "declares-build-dependency": ("declared-package-dependencies",),
    "declares-test-dependency": ("declared-package-dependencies",),
    "declares-runtime-dependency": ("declared-package-dependencies",),
    "used-build-output": ("used-build-output",),
}
ALL_RELATION_COVERAGE = (
    "declared-package-dependencies",
    "elf-interfaces",
    "script-interpreters",
    "used-build-output",
)


def _sequence(snapshots):
    if (not isinstance(snapshots, (list, tuple)) or
            not 1 <= len(snapshots) <= MAX_SEQUENCE):
        raise TraceError(
            "invalid-query",
            "Provide between 1 and 100 caller-ordered snapshot record identities.",
        )
    values = list(snapshots)
    for value in values:
        if not isinstance(value, str) or RECORD_ID.fullmatch(value) is None:
            raise TraceError("invalid-query", "Snapshot sequence contains an invalid canonical record identity.")
    if len(values) != len(set(values)):
        raise TraceError("invalid-query", "Snapshot sequence must not contain duplicates.")
    return values


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise TraceError("invalid-query", name + " must be a nonempty string of at most 8192 characters.")
    return value


def _digest(value, name):
    if not isinstance(value, str) or RECORD_ID.fullmatch(value) is None:
        raise TraceError("invalid-query", name + " must be a lowercase sha256 digest.")
    return value


def _point_descriptors(snapshots):
    return [
        {"id": f"{index:04d}:{snapshot}", "position": index + 1, "snapshot": snapshot}
        for index, snapshot in enumerate(snapshots)
    ]


def _coverage(snapshot, bundle, families):
    rows = []
    for family in families:
        rows.extend(_rows(None, snapshot, bundle, "coverage", family=family))
    rows.sort(key=lambda row: (row.get("family", ""), row["record"]))
    return rows


def _verification_point(trace, descriptor, check_id, definition_digest):
    snapshot, bundle, report, metrics, generation = _read_snapshot(
        trace, descriptor["snapshot"])
    definitions = [
        row for row in _rows(trace, snapshot, bundle, "verification-checks")
        if row.get("availability") == "available" and row["check_id"] == check_id and
        (definition_digest is None or row["definition_digest"] == definition_digest)
    ]
    executions = [
        row for row in _rows(trace, snapshot, bundle, "verification-executions")
        if row.get("availability") == "available" and row["check_id"] == check_id and
        (definition_digest is None or row["definition_digest"] == definition_digest)
    ]
    coverage = _coverage(snapshot, bundle, ("verification-commands",))
    return {
        "id": descriptor["id"],
        "position": descriptor["position"],
        "snapshot": descriptor["snapshot"],
        "generation": generation,
        "generation_record": snapshot["data"]["generation"],
        "generation_id": snapshot["data"]["generation_id"],
        "root_inventory_digest": snapshot["data"]["root_inventory_digest"],
        "record_set_digest": snapshot["data"]["record_set_digest"],
        "definitions": definitions,
        "definition_count": len(definitions),
        "executions": executions,
        "execution_count": len(executions),
        "coverage": coverage,
        "coverage_availability": "recorded" if coverage else "not-recorded-in-snapshot",
        **_completeness_fields(report),
        "inspection": metrics,
    }


def _selector(direction, kind, value):
    if direction not in ("forward", "reverse"):
        raise TraceError("invalid-query", "direction must be forward or reverse.")
    allowed = FORWARD_SELECTORS if direction == "forward" else REVERSE_SELECTORS
    if kind not in allowed:
        raise TraceError(
            "invalid-query",
            f"{kind!r} is not a supported {direction} relationship selector.",
        )
    if kind in ("artifact-digest", "package-output"):
        _digest(value, "selector value")
    else:
        _text(value, "selector value")
    if kind in ("artifact-path", "path") and not value.startswith("/"):
        raise TraceError("invalid-query", "Path relationship selectors must be absolute.")
    return direction, kind, value


def _forward_match(row, kind, value):
    subject = row["subject"]
    if kind == "package":
        return (subject["kind"] == "package" and subject["package"] == value) or (
            subject["kind"] == "artifact" and value in subject.get("packages", []))
    if kind == "package-output":
        return subject["kind"] == "package" and subject["output_record"] == value
    if kind == "artifact-path":
        return subject["kind"] == "artifact" and subject["path"] == value
    return subject["kind"] == "artifact" and subject["digest"] == value


def _reverse_match(row, kind, value):
    target = row["target"]
    if kind == "package":
        return ((target["kind"] == "package" and target["value"] == value) or
                (target["kind"] == "package-output" and target["package"] == value))
    if kind == "package-output":
        return target["kind"] == "package-output" and target["value"] == value
    if kind == "soname":
        return target["kind"] == "soname" and target["value"] == value
    return target["kind"] == "path" and target["value"] == value


def _relationship_point(trace, descriptor, direction, selector_kind, selector_value,
                        relation):
    snapshot, bundle, report, metrics, generation = _read_snapshot(
        trace, descriptor["snapshot"])
    candidates = _rows(trace, snapshot, bundle, "relationships")
    if relation is not None:
        candidates = [
            row for row in candidates
            if row.get("availability") == "available" and row["relation"] == relation
        ]
    matcher = _forward_match if direction == "forward" else _reverse_match
    matches = [
        row for row in candidates
        if row.get("availability") == "available" and
        matcher(row, selector_kind, selector_value)
    ]
    families = RELATION_COVERAGE[relation] if relation is not None else ALL_RELATION_COVERAGE
    coverage = _coverage(snapshot, bundle, families)
    return {
        "id": descriptor["id"],
        "position": descriptor["position"],
        "snapshot": descriptor["snapshot"],
        "generation": generation,
        "generation_record": snapshot["data"]["generation"],
        "generation_id": snapshot["data"]["generation_id"],
        "root_inventory_digest": snapshot["data"]["root_inventory_digest"],
        "record_set_digest": snapshot["data"]["record_set_digest"],
        "relationships": matches,
        "relationship_count": len(matches),
        "coverage": coverage,
        "coverage_availability": "recorded" if coverage else "not-recorded-in-snapshot",
        **_completeness_fields(report),
        "inspection": metrics,
    }


class HistoryMixin:
    """History/traversal views whose ordering is supplied entirely by the caller."""

    @checked
    def verification_history(self, snapshots, check_id, *, definition_digest=None,
                             cursor=None, limit=20):
        snapshots = _sequence(snapshots)
        _text(check_id, "check_id")
        if definition_digest is not None:
            _digest(definition_digest, "definition_digest")
        limit_value(limit)
        page = paginate(
            _point_descriptors(snapshots),
            scope=[
                self.scope, str(self.record_store), self.record_project_id,
                "verification-history", snapshots, check_id, definition_digest,
            ],
            cursor=cursor,
            limit=limit,
        )
        points = [
            _verification_point(self, item, check_id, definition_digest)
            for item in page["items"]
        ]
        return response(
            "verification-history",
            check_id=check_id,
            definition_digest=definition_digest,
            snapshot_count=len(snapshots),
            order="caller-supplied",
            chronology="not-inferred",
            points=points,
            has_more=page["has_more"],
            next_cursor=page["next_cursor"],
            authority="build-record",
            interpretation=(
                "All matching definitions and executions in each selected snapshot are retained. "
                "Caller order is presentation order only; no baseline, representative execution, "
                "regression, chronology or causation is inferred."
            ),
        )

    @checked
    def relationship_traversal(self, snapshots, direction, selector_kind, selector_value,
                               *, relation=None, cursor=None, limit=20):
        snapshots = _sequence(snapshots)
        direction, selector_kind, selector_value = _selector(
            direction, selector_kind, selector_value)
        if relation is not None and relation not in RELATIONS:
            raise TraceError("invalid-query", "Unsupported relationship type.")
        limit_value(limit)
        page = paginate(
            _point_descriptors(snapshots),
            scope=[
                self.scope, str(self.record_store), self.record_project_id,
                "relationship-traversal", snapshots, direction, selector_kind,
                selector_value, relation,
            ],
            cursor=cursor,
            limit=limit,
        )
        points = [
            _relationship_point(
                self, item, direction, selector_kind, selector_value, relation)
            for item in page["items"]
        ]
        return response(
            "relationship-traversal",
            direction=direction,
            selector={"kind": selector_kind, "value": selector_value},
            relation=relation,
            snapshot_count=len(snapshots),
            order="caller-supplied",
            chronology="not-inferred",
            match_semantics="literal-canonical-fields-only",
            points=points,
            has_more=page["has_more"],
            next_cursor=page["next_cursor"],
            authority="build-record",
            interpretation=(
                "Forward/reverse matching uses only literal canonical relationship fields. "
                "Reverse SONAME/path/package matches are not dependency-provider resolution, "
                "reachability, blast radius or causation."
            ),
        )
