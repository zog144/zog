"""Two-world factual comparison over build-trace's public observation contract."""
from collections import defaultdict
from copy import deepcopy


SCHEMA_VERSION = 2
BUILD_TRACE_SCHEMA_VERSION = 1
OBSERVATION_COLLECTIONS = (
    "verification-checks",
    "verification-executions",
    "relationships",
    "source-provenance",
    "coverage",
)
SNAPSHOT_COLLECTIONS = OBSERVATION_COLLECTIONS + ("declared-gaps",)
COMPLETENESS_FIELDS = (
    "reference_closure_complete",
    "missing_record_count",
    "declared_gap_free",
    "declared_gap_count",
    "declared_gap_reason_count",
    "declared_gap_summary",
)


class ObservationError(RuntimeError):
    """Raised when a public build-trace response cannot support a comparison."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _expect_mapping(value, name):
    if not isinstance(value, dict):
        raise ObservationError("invalid-observation", f"{name} must be a JSON object.")
    return value


def _expect_kind(value, kind):
    _expect_mapping(value, "build-trace response")
    if value.get("schema_version") != BUILD_TRACE_SCHEMA_VERSION or value.get("kind") != kind:
        raise ObservationError(
            "unsupported-build-trace-contract",
            f"Expected build-trace schema {BUILD_TRACE_SCHEMA_VERSION} {kind!r} response.",
        )
    return value


def _require_build_trace_012_completeness(value, *, prefix=""):
    missing = [prefix + field for field in COMPLETENESS_FIELDS if prefix + field not in value]
    if missing:
        raise ObservationError(
            "unsupported-build-trace-contract",
            "build-trace 0.12 completeness fields are required: " + ", ".join(missing),
        )
    bool_fields = (prefix + "reference_closure_complete", prefix + "declared_gap_free")
    int_fields = (
        prefix + "missing_record_count",
        prefix + "declared_gap_count",
        prefix + "declared_gap_reason_count",
    )
    if any(not isinstance(value[field], bool) for field in bool_fields):
        raise ObservationError("invalid-observation", "build-trace completeness booleans are malformed.")
    if any(not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0
           for field in int_fields):
        raise ObservationError("invalid-observation", "build-trace completeness counts are malformed.")
    if not isinstance(value[prefix + "declared_gap_summary"], list):
        raise ObservationError("invalid-observation", "build-trace declared-gap summary is malformed.")


def _completeness(value, *, prefix=""):
    _require_build_trace_012_completeness(value, prefix=prefix)
    return {
        "reference_closure_complete": value[prefix + "reference_closure_complete"],
        "missing_record_count": value[prefix + "missing_record_count"],
        "declared_gap_free": value[prefix + "declared_gap_free"],
        "declared_gap_count": value[prefix + "declared_gap_count"],
        "declared_gap_reason_count": value[prefix + "declared_gap_reason_count"],
        "declared_gap_summary": deepcopy(value[prefix + "declared_gap_summary"]),
    }


def _page_items(container, key):
    page = _expect_mapping(container.get(key), key)
    items = page.get("items")
    if not isinstance(items, list):
        raise ObservationError("invalid-observation", f"{key}.items must be a JSON array.")
    return items, bool(page.get("has_more")), page.get("next_cursor")


def _stable_key(value):
    """Return a recursively comparable JSON-ish representation."""
    if isinstance(value, dict):
        return tuple((key, _stable_key(value[key])) for key in sorted(value))
    if isinstance(value, list):
        return tuple(_stable_key(item) for item in value)
    return value


def _coverage_by_family(world):
    result = defaultdict(list)
    for item in world.get("coverage", []):
        if isinstance(item, dict) and isinstance(item.get("family"), str):
            result[item["family"]].append(item)
    return dict(result)


def _comparison_evidence(summary):
    baseline = _completeness(summary, prefix="before_")
    candidate = _completeness(summary, prefix="after_")
    before_coverage = summary.get("before_coverage")
    after_coverage = summary.get("after_coverage")
    if not isinstance(before_coverage, list) or not isinstance(after_coverage, list):
        raise ObservationError(
            "unsupported-build-trace-contract",
            "build-trace 0.12 comparison coverage fields are required.",
        )
    baseline["coverage"] = deepcopy(before_coverage)
    candidate["coverage"] = deepcopy(after_coverage)
    return {
        "baseline": baseline,
        "candidate": candidate,
        "both_reference_closures_complete": (
            baseline["reference_closure_complete"] and candidate["reference_closure_complete"]
        ),
    }


class IntegrationObserver:
    """Select two immutable observation snapshots and compare their recorded facts.

    ``trace`` is intentionally duck-typed against the public ``zog.build_trace.BuildTrace``
    surface. integrate-observe never imports build-record or image-build schemas.
    """

    def __init__(self, trace, *, page_limit=100):
        if not isinstance(page_limit, int) or not 1 <= page_limit <= 100:
            raise ValueError("page_limit must be between 1 and 100")
        self.trace = trace
        self.page_limit = page_limit

    def world(self, snapshot):
        raw = _expect_kind(self.trace.observation_snapshot(snapshot), "observation-snapshot")
        if raw.get("availability") != "available":
            raise ObservationError("snapshot-unavailable", "Observation snapshot is not available.")
        completeness = _completeness(raw)
        missing_records = raw.get("missing_records", [])
        if not isinstance(missing_records, list):
            raise ObservationError("invalid-observation", "missing_records must be a JSON array.")
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "world",
            "snapshot": raw["snapshot"],
            "generation": raw["generation"],
            "generation_record": raw["generation_record"],
            "generation_id": raw["generation_id"],
            "root_inventory_digest": raw["root_inventory_digest"],
            "record_set_digest": raw["record_set_digest"],
            "collections": deepcopy(raw["collections"]),
            "coverage": deepcopy(raw.get("coverage", [])),
            **completeness,
            "missing_records": deepcopy(missing_records),
            "missing_records_truncated": bool(raw.get("missing_records_truncated", False)),
            "authority": raw.get("authority", "build-record"),
            "selection": "caller-selected-snapshot",
            "interpretation": {
                "release_identity_assigned": False,
                "chronology_inferred": False,
                "policy_evaluated": False,
                "declared_gaps_treated_as_missing_records": False,
                "coverage_treated_as_reference_integrity": False,
            },
        }

    def _snapshot_rows(self, snapshot, collection):
        rows = []
        cursor = None
        seen = set()
        while True:
            raw = _expect_kind(
                self.trace.observation_snapshot(
                    snapshot,
                    collection=collection,
                    cursor=cursor,
                    limit=self.page_limit,
                ),
                "observation-snapshot-collection",
            )
            items, has_more, next_cursor = _page_items(raw, "items")
            rows.extend(deepcopy(items))
            if not has_more:
                return rows
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                raise ObservationError("invalid-pagination", "build-trace returned an unusable cursor.")
            seen.add(next_cursor)
            cursor = next_cursor

    def _comparison_changes(self, before, after, collection):
        rows = []
        cursor = None
        seen = set()
        while True:
            raw = _expect_kind(
                self.trace.compare_observation_snapshots(
                    before,
                    after,
                    collection=collection,
                    cursor=cursor,
                    limit=self.page_limit,
                ),
                "observation-snapshot-comparison-collection",
            )
            items, has_more, next_cursor = _page_items(raw, "changes")
            rows.extend(deepcopy(items))
            if not has_more:
                return rows
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                raise ObservationError("invalid-pagination", "build-trace returned an unusable cursor.")
            seen.add(next_cursor)
            cursor = next_cursor

    @staticmethod
    def _source_changes(before_rows, after_rows):
        def grouped(rows):
            result = defaultdict(list)
            for row in rows:
                if row.get("availability") == "available" and isinstance(row.get("package"), str):
                    result[row["package"]].append(row)
            return result

        before = grouped(before_rows)
        after = grouped(after_rows)
        changes = []
        for package in sorted(set(before) | set(after)):
            left = before.get(package, [])
            right = after.get(package, [])
            if len(left) == 1 and len(right) == 1:
                if left[0].get("record") == right[0].get("record"):
                    continue
                changes.append({
                    "package": package,
                    "change": "changed",
                    "pairing": "unique-package-observation",
                    "before": deepcopy(left[0]),
                    "after": deepcopy(right[0]),
                })
            elif len(left) == 1 and not right:
                changes.append({
                    "package": package,
                    "change": "removed",
                    "pairing": "unique-package-observation",
                    "before": deepcopy(left[0]),
                    "after": None,
                })
            elif not left and len(right) == 1:
                changes.append({
                    "package": package,
                    "change": "added",
                    "pairing": "unique-package-observation",
                    "before": None,
                    "after": deepcopy(right[0]),
                })
            elif [_stable_key(row) for row in left] != [_stable_key(row) for row in right]:
                changes.append({
                    "package": package,
                    "change": "ambiguous",
                    "pairing": "multiple-or-missing-observations",
                    "before_records": sorted(row.get("record") for row in left if row.get("record")),
                    "after_records": sorted(row.get("record") for row in right if row.get("record")),
                })
        return changes

    @staticmethod
    def _verification_outcome_changes(before_rows, after_rows):
        def grouped(rows):
            result = defaultdict(list)
            for row in rows:
                if row.get("availability") != "available":
                    continue
                check_id = row.get("check_id")
                definition = row.get("definition_digest")
                if isinstance(check_id, str) and isinstance(definition, str):
                    result[(check_id, definition)].append(row)
            return result

        before = grouped(before_rows)
        after = grouped(after_rows)
        changes = []
        for key in sorted(set(before) | set(after)):
            left = before.get(key, [])
            right = after.get(key, [])
            left_outcomes = sorted(row.get("outcome") for row in left)
            right_outcomes = sorted(row.get("outcome") for row in right)
            left_records = sorted(row.get("record") for row in left if row.get("record"))
            right_records = sorted(row.get("record") for row in right if row.get("record"))
            if left_outcomes == right_outcomes and left_records == right_records:
                continue
            changes.append({
                "check_id": key[0],
                "definition_digest": key[1],
                "before_outcomes": left_outcomes,
                "after_outcomes": right_outcomes,
                "before_records": left_records,
                "after_records": right_records,
                "classification": "execution-set-changed",
                "representative_execution_selected": False,
                "regression_classified": False,
            })
        return changes

    def compare(self, baseline_snapshot, candidate_snapshot):
        if baseline_snapshot == candidate_snapshot:
            raise ObservationError("same-snapshot", "Baseline and candidate snapshots must differ.")

        baseline = self.world(baseline_snapshot)
        candidate = self.world(candidate_snapshot)
        summary = _expect_kind(
            self.trace.compare_observation_snapshots(baseline_snapshot, candidate_snapshot),
            "observation-snapshot-comparison",
        )
        evidence_completeness = _comparison_evidence(summary)

        raw_changes = {
            collection: self._comparison_changes(
                baseline_snapshot, candidate_snapshot, collection)
            for collection in SNAPSHOT_COLLECTIONS
        }
        baseline_sources = self._snapshot_rows(baseline_snapshot, "source-provenance")
        candidate_sources = self._snapshot_rows(candidate_snapshot, "source-provenance")
        baseline_executions = self._snapshot_rows(baseline_snapshot, "verification-executions")
        candidate_executions = self._snapshot_rows(candidate_snapshot, "verification-executions")

        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "world-comparison",
            "baseline": baseline,
            "candidate": candidate,
            "selection": {
                "baseline": "caller-selected",
                "candidate": "caller-selected",
                "order": "caller-supplied",
                "chronology": "not-inferred",
            },
            "identity_comparison": {
                "same_generation_record": bool(summary["same_generation_record"]),
                "same_generation_id": bool(summary["same_generation_id"]),
                "same_root_inventory": bool(summary["same_root_inventory"]),
                "same_record_set": bool(summary["same_record_set"]),
            },
            "collection_summary": deepcopy(summary["collections"]),
            "verification_check_changes": deepcopy(summary.get("verification_check_changes", [])),
            "coverage_changes": deepcopy(summary.get("coverage_changes", [])),
            "canonical_changes": raw_changes,
            "declared_gap_changes": deepcopy(raw_changes["declared-gaps"]),
            "source_changes": self._source_changes(baseline_sources, candidate_sources),
            "verification_execution_changes": self._verification_outcome_changes(
                baseline_executions, candidate_executions),
            "coverage_by_world": {
                "baseline": _coverage_by_family(baseline),
                "candidate": _coverage_by_family(candidate),
            },
            "evidence_completeness": evidence_completeness,
            "evidence": {
                "authority": "build-record-via-build-trace",
                "baseline_snapshot": baseline_snapshot,
                "candidate_snapshot": candidate_snapshot,
                "both_reference_closures_complete": evidence_completeness[
                    "both_reference_closures_complete"
                ],
            },
            "interpretation": {
                "release_identity_assigned": False,
                "chronology_inferred": False,
                "representative_execution_selected": False,
                "provider_resolution_performed": False,
                "regression_classified": False,
                "causation_inferred": False,
                "blast_radius_computed": False,
                "severity_assigned": False,
                "policy_evaluated": False,
                "declared_gap_reduction_classified_as_improvement": False,
                "coverage_change_classified_as_improvement_or_regression": False,
            },
        }
