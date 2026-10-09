"""Read-only queries over build-record generation observation snapshots."""
import json
import re

from .api import checked
from .generations import Reader
from .model import TraceError, limit_value, paginate, response

OBSERVATION_COLLECTIONS = (
    "verification-checks",
    "verification-executions",
    "relationships",
    "source-provenance",
    "coverage",
)
SNAPSHOT_COLLECTIONS = OBSERVATION_COLLECTIONS + ("declared-gaps",)
GAP_CATEGORIES = (
    "upstream-identity",
    "external-environment-runtime",
    "inventory-only-output",
    "other",
)
GROUP = {
    "verification-checks": "verification_checks",
    "verification-executions": "verification_executions",
    "relationships": "relationships",
    "source-provenance": "source_provenance",
    "coverage": "coverage",
}
EXPECTED_KIND = {
    "verification-checks": "verification-check",
    "verification-executions": "verification-execution",
    "relationships": "relationship-observation",
    "source-provenance": "source-provenance",
    "coverage": "observation-coverage",
    "declared-gaps": "canonical-record-with-declared-gaps",
}
RELATIONS = frozenset({
    "needs-library", "provides-soname", "elf-interpreter", "script-interpreter",
    "declares-build-dependency", "declares-test-dependency",
    "declares-runtime-dependency", "used-build-output",
})
COVERAGE_FAMILIES = frozenset({
    "verification-commands", "elf-interfaces", "script-interpreters",
    "declared-package-dependencies", "used-build-output", "source-provenance",
})
COVERAGE_OUTCOMES = frozenset({
    "complete", "partial", "unavailable", "not-performed", "not-applicable",
})
RECORD_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _record_id(value):
    if not isinstance(value, str) or RECORD_ID.fullmatch(value) is None:
        raise TraceError("invalid-query", "Expected a canonical sha256 record identity.")
    return value


def _owner_generation(trace, value):
    try:
        owner = json.loads(value)
    except (TypeError, ValueError):
        raise TraceError("invalid-record", "Snapshot generation identity is malformed.") from None
    if (not isinstance(owner, list) or len(owner) != 3 or
            owner[:2] != [trace.host_id, trace.record_project_id] or
            not isinstance(owner[2], str) or not owner[2]):
        raise TraceError("not-found", "Observation snapshot is outside the authorized scope.")
    return owner[2]


def _execution_scope(trace, data):
    try:
        owner = json.loads(data["attempt_id"])
    except (TypeError, ValueError):
        raise TraceError("invalid-record", "Verification attempt identity is malformed.") from None
    if (not isinstance(owner, list) or len(owner) != 3 or
            owner[:2] != [trace.host_id, trace.record_project_id] or
            not isinstance(owner[2], str) or not owner[2]):
        raise TraceError("not-found", "Verification execution is outside the authorized scope.")
    build_id = "attempt:" + owner[2]
    if not trace._permitted(build_id):
        raise TraceError("not-found", "Verification execution is outside the authorized scope.")
    for evidence in data.get("evidence", []):
        if evidence.get("kind") == "build-trace":
            if (evidence.get("host_id") != trace.host_id or
                    not isinstance(evidence.get("build_id"), str) or
                    not trace._permitted(evidence["build_id"])):
                raise TraceError("not-found", "Verification evidence is outside the authorized scope.")
    return build_id


def _read_snapshot(trace, identity):
    identity = _record_id(identity)
    reader = Reader(trace)
    try:
        required = ("record_id", "snapshot_record_set_digest")
        if any(not callable(getattr(reader.lib, name, None)) for name in required):
            raise TraceError(
                "dependency-unavailable",
                "Install build-record 0.7.0 or newer for observation snapshot inspection.",
            )
        bundle, report = reader.graph(identity)
        record = bundle["records"].get(identity)
        if record is None:
            raise TraceError("not-found", "Observation snapshot record is unavailable.")
        if record["kind"] != "generation-observation-snapshot":
            raise TraceError("invalid-query", "Selected canonical record is not an observation snapshot.")
        generation = _owner_generation(trace, record["data"]["generation_id"])
        for execution_id in record["data"]["observations"]["verification_executions"]:
            execution = bundle["records"].get(execution_id)
            if execution is not None:
                _execution_scope(trace, execution["data"])
        metrics = reader.finish()
        return record, bundle, report, metrics, generation
    except Exception:
        try:
            reader.finish()
        except Exception:
            pass
        raise


def _base_row(identity, record):
    if record is None:
        return {
            "id": identity,
            "record": identity,
            "availability": "record-unavailable",
            "authority": "build-record",
        }
    return {
        "id": identity,
        "record": identity,
        "availability": "available",
        "authority": "build-record",
        "canonical_kind": record["kind"],
        "persistence": "stored",
        "gaps": record["gaps"],
    }


def _source_row(identity, record, records):
    row = _base_row(identity, record)
    if record is None:
        return row
    data = record["data"]
    archive = records.get(data["archive"])
    associations = []
    for association_id in data["associations"]:
        association = records.get(association_id)
        item = {"record": association_id, "availability": "record-unavailable"}
        if association is not None:
            item = {
                "record": association_id,
                "availability": "available",
                "relationship": association["data"]["relationship"],
                "archive": association["data"]["archive"],
                "reference": association["data"]["reference"],
            }
            reference = records.get(association["data"]["reference"])
            if reference is not None:
                item["reference_kind"] = reference["data"]["kind"]
                item["reference_value"] = reference["data"]["value"]
                item["repository_record"] = reference["data"]["repository"]
                repository = records.get(reference["data"]["repository"])
                if repository is not None:
                    item["repository"] = repository["data"]["location"]
                    item["repository_normalization"] = repository["data"]["normalization"]
        associations.append(item)
    row.update(
        producer=data["producer"],
        producer_observation=data["producer_observation"],
        package=data["package"],
        project=data["project"],
        output=data["output"],
        build_inputs=data["build_inputs"],
        source_selection=data["source_selection"],
        archive_record=data["archive"],
        archive=(archive["data"] if archive is not None else None),
        associations=associations,
    )
    return row


def _project_row(trace, collection, identity, records):
    record = records.get(identity)
    if collection == "source-provenance":
        return _source_row(identity, record, records)
    row = _base_row(identity, record)
    if record is None:
        return row
    data = record["data"]
    if collection == "verification-checks":
        row.update(producer=data["producer"], check_id=data["check_id"],
                   definition_digest=data["definition_digest"],
                   granularity=data["granularity"])
    elif collection == "verification-executions":
        row.update(
            producer=data["producer"],
            producer_observation=data["producer_observation"],
            check_id=data["check_id"],
            definition_digest=data["definition_digest"],
            subject=data["subject"],
            attempt_id=data["attempt_id"],
            build_id=_execution_scope(trace, data),
            sequence=data["sequence"],
            outcome=data["outcome"],
            execution=data["execution"],
            environment_digest=data["environment_digest"],
            evidence=data["evidence"],
            granularity=data["granularity"],
            timing=data["timing"],
        )
    elif collection == "relationships":
        row.update(
            producer=data["producer"],
            producer_observation=data["producer_observation"],
            subject=data["subject"],
            relation=data["relation"],
            target=data["target"],
            evidence=data["evidence"],
        )
    elif collection == "coverage":
        row.update(
            producer=data["producer"],
            subject=data["subject"],
            family=data["family"],
            collector=data["collector"],
            scope=data["scope"],
            outcome=data["outcome"],
            observation_count=data["observation_count"],
            details=data["details"],
        )
    return row


def _relationship_package(row, package):
    if row.get("availability") != "available":
        return False
    subject = row["subject"]
    if subject["kind"] == "package":
        return subject["package"] == package
    return package in subject.get("packages", [])


def _rows(trace, snapshot, bundle, collection, *, relation=None, package=None,
          family=None, outcome=None):
    identities = snapshot["data"]["observations"][GROUP[collection]]
    result = [_project_row(trace, collection, identity, bundle["records"])
              for identity in identities]
    if relation is not None:
        result = [row for row in result
                  if row.get("availability") == "available" and row["relation"] == relation]
    if package is not None:
        if collection == "relationships":
            result = [row for row in result if _relationship_package(row, package)]
        elif collection == "source-provenance":
            result = [row for row in result
                      if row.get("availability") == "available" and row["package"] == package]
    if family is not None:
        result = [row for row in result
                  if row.get("availability") == "available" and row["family"] == family]
    if outcome is not None:
        result = [row for row in result
                  if row.get("availability") == "available" and row["outcome"] == outcome]
    return result


def _filters(collection, relation, package, family, outcome, gap_category):
    if relation is not None and (collection != "relationships" or relation not in RELATIONS):
        raise TraceError("invalid-query", "relation is only valid for a known relationship value.")
    if package is not None:
        if (collection not in ("relationships", "source-provenance") or
                not isinstance(package, str) or not package.strip()):
            raise TraceError("invalid-query", "package is only valid for relationship or source-provenance collections.")
    if family is not None and (collection != "coverage" or family not in COVERAGE_FAMILIES):
        raise TraceError("invalid-query", "family is only valid for a known coverage family.")
    if outcome is not None and (collection != "coverage" or outcome not in COVERAGE_OUTCOMES):
        raise TraceError("invalid-query", "outcome is only valid for a known coverage outcome.")
    if gap_category is not None and (
            collection != "declared-gaps" or gap_category not in GAP_CATEGORIES):
        raise TraceError(
            "invalid-query",
            "gap_category is only valid for a known declared-gap category.")


def _gap_category(reason):
    value = reason.lower()
    if "upstream revision" in value or "upstream source reference" in value:
        return "upstream-identity"
    if "package output is represented by a verified inventory artifact" in value:
        return "inventory-only-output"
    if ("controller/runtime implementation" in value or
            "environment outside the canonical allowlist" in value):
        return "external-environment-runtime"
    return "other"


def _gap_rows(report, bundle, *, category=None):
    rows = []
    for item in report["gaps"]:
        record = bundle["records"].get(item["record"])
        reasons = [
            {"category": _gap_category(reason), "reason": reason}
            for reason in item["reasons"]
        ]
        categories = sorted({entry["category"] for entry in reasons})
        if category is not None and category not in categories:
            continue
        rows.append({
            "id": item["record"],
            "record": item["record"],
            "canonical_kind": record["kind"] if record is not None else None,
            "categories": categories,
            "reasons": reasons,
            "reason_count": len(reasons),
            "authority": "build-record",
            "persistence": "stored",
        })
    return rows


def _gap_summary(report):
    buckets = {
        category: {"records": set(), "reason_count": 0}
        for category in GAP_CATEGORIES
    }
    total_reasons = 0
    for item in report["gaps"]:
        for reason in item["reasons"]:
            category = _gap_category(reason)
            buckets[category]["records"].add(item["record"])
            buckets[category]["reason_count"] += 1
            total_reasons += 1
    summary = [
        {
            "category": category,
            "record_count": len(buckets[category]["records"]),
            "reason_count": buckets[category]["reason_count"],
        }
        for category in GAP_CATEGORIES
        if buckets[category]["reason_count"]
    ]
    return summary, total_reasons


def _completeness_fields(report):
    summary, reason_count = _gap_summary(report)
    return {
        "reference_closure_complete": not report["missing_records"],
        "missing_record_count": len(report["missing_records"]),
        "declared_gap_free": not report["gaps"],
        "declared_gap_count": len(report["gaps"]),
        "declared_gap_reason_count": reason_count,
        "declared_gap_summary": summary,
    }


def _coverage_summary(snapshot, bundle):
    rows = _rows(None, snapshot, bundle, "coverage")
    return sorted([
        {
            "family": row["family"],
            "record": row["record"],
            "outcome": row["outcome"],
            "observation_count": row["observation_count"],
        }
        for row in rows if row["availability"] == "available"
    ], key=lambda item: (item["family"], item["record"]))


def _snapshot_summary(snapshot, bundle, report):
    declared = snapshot["data"]["observations"]
    result = {
        collection: {
            "declared_count": len(declared[GROUP[collection]]),
            "available_count": sum(
                identity in bundle["records"] for identity in declared[GROUP[collection]]
            ),
            "canonical_kind": EXPECTED_KIND[collection],
        }
        for collection in OBSERVATION_COLLECTIONS
    }
    result["declared-gaps"] = {
        "declared_count": len(report["gaps"]),
        "available_count": len(report["gaps"]),
        "canonical_kind": EXPECTED_KIND["declared-gaps"],
    }
    return result


def _coverage_changes(left_snapshot, left_bundle, right_snapshot, right_bundle):
    def grouped(snapshot, bundle):
        result = {}
        for row in _rows(None, snapshot, bundle, "coverage"):
            if row["availability"] == "available":
                result.setdefault(row["family"], []).append(row)
        return result
    left = grouped(left_snapshot, left_bundle)
    right = grouped(right_snapshot, right_bundle)
    changes = []
    for family in sorted(set(left) | set(right)):
        before = left.get(family, [])
        after = right.get(family, [])
        before_ids = sorted(row["record"] for row in before)
        after_ids = sorted(row["record"] for row in after)
        if before_ids == after_ids:
            continue
        item = {
            "family": family,
            "before_records": before_ids,
            "after_records": after_ids,
        }
        if len(before) == 1 and len(after) == 1:
            item.update(
                pairing="unique-family",
                before_outcome=before[0]["outcome"],
                after_outcome=after[0]["outcome"],
                before_observation_count=before[0]["observation_count"],
                after_observation_count=after[0]["observation_count"],
            )
        else:
            item["pairing"] = "ambiguous-or-missing"
        changes.append(item)
    return changes


def _check_changes(left_snapshot, left_bundle, right_snapshot, right_bundle):
    def grouped(snapshot, bundle):
        result = {}
        for row in _rows(None, snapshot, bundle, "verification-checks"):
            if row["availability"] == "available":
                result.setdefault(row["check_id"], []).append(row)
        return result
    left = grouped(left_snapshot, left_bundle)
    right = grouped(right_snapshot, right_bundle)
    changes = []
    for check_id in sorted(set(left) | set(right)):
        before = left.get(check_id, [])
        after = right.get(check_id, [])
        before_ids = sorted(row["record"] for row in before)
        after_ids = sorted(row["record"] for row in after)
        if before_ids == after_ids:
            continue
        item = {
            "check_id": check_id,
            "before_records": before_ids,
            "after_records": after_ids,
        }
        if len(before) == 1 and len(after) == 1:
            item.update(
                pairing="unique-logical-check",
                before_definition_digest=before[0]["definition_digest"],
                after_definition_digest=after[0]["definition_digest"],
            )
        else:
            item["pairing"] = "ambiguous-or-missing"
        changes.append(item)
    return changes


class SnapshotObservationMixin:
    """Canonical generation-observation snapshot inspection and factual comparison."""

    @checked
    def observation_snapshot(self, snapshot, *, collection=None, relation=None,
                             package=None, family=None, outcome=None,
                             gap_category=None, cursor=None, limit=20):
        if collection is not None and collection not in SNAPSHOT_COLLECTIONS:
            raise TraceError("invalid-query", "Unsupported snapshot observation collection.")
        if collection is None and any(value is not None for value in
                                      (relation, package, family, outcome, gap_category, cursor)):
            raise TraceError("invalid-query", "Snapshot filters and cursors require a selected collection.")
        _filters(collection, relation, package, family, outcome, gap_category)
        if collection is not None:
            limit_value(limit)

        record, bundle, report, metrics, generation = _read_snapshot(self, snapshot)
        data = record["data"]
        if collection is None:
            return response(
                "observation-snapshot",
                snapshot=snapshot,
                availability="available",
                generation=generation,
                generation_record=data["generation"],
                generation_id=data["generation_id"],
                root_inventory_digest=data["root_inventory_digest"],
                record_set_digest=data["record_set_digest"],
                collections=_snapshot_summary(record, bundle, report),
                coverage=_coverage_summary(record, bundle),
                missing_records=report["missing_records"][:100],
                missing_records_truncated=len(report["missing_records"]) > 100,
                **_completeness_fields(report),
                authority="build-record",
                authenticity="not-verified",
                artifact_verification="not-checked",
                interpretation=(
                    "Reference closure, canonical declared gaps, and observation coverage are "
                    "independent factual dimensions. Declared gaps do not make reference closure "
                    "incomplete; coverage outcomes are not reference-integrity judgments."
                ),
                inspection=metrics,
            )

        rows = (_gap_rows(report, bundle, category=gap_category)
                if collection == "declared-gaps"
                else _rows(self, record, bundle, collection, relation=relation, package=package,
                           family=family, outcome=outcome))
        filters = dict(relation=relation, package=package, family=family, outcome=outcome,
                       gap_category=gap_category)
        page = paginate(
            rows,
            scope=[self.scope, str(self.record_store), self.record_project_id,
                   "observation-snapshot", snapshot, collection, filters],
            cursor=cursor,
            limit=limit,
        )
        return response(
            "observation-snapshot-collection",
            snapshot=snapshot,
            generation=generation,
            generation_record=data["generation"],
            record_set_digest=data["record_set_digest"],
            collection=collection,
            canonical_kind=EXPECTED_KIND[collection],
            filters=filters,
            items=page,
            **_completeness_fields(report),
            authority="build-record",
            persistence="stored",
            inspection=metrics,
        )

    @checked
    def compare_observation_snapshots(self, before, after, *, collection=None,
                                      cursor=None, limit=20):
        if collection is not None and collection not in SNAPSHOT_COLLECTIONS:
            raise TraceError("invalid-query", "Unsupported snapshot comparison collection.")
        if collection is None and cursor is not None:
            raise TraceError("invalid-query", "A comparison cursor requires a selected collection.")
        if collection is not None:
            limit_value(limit)

        left, left_bundle, left_report, left_metrics, left_generation = _read_snapshot(self, before)
        right, right_bundle, right_report, right_metrics, right_generation = _read_snapshot(self, after)
        left_data, right_data = left["data"], right["data"]
        summaries = {}
        for name in OBSERVATION_COLLECTIONS:
            left_ids = set(left_data["observations"][GROUP[name]])
            right_ids = set(right_data["observations"][GROUP[name]])
            summaries[name] = {
                "before_count": len(left_ids),
                "after_count": len(right_ids),
                "added_count": len(right_ids - left_ids),
                "removed_count": len(left_ids - right_ids),
                "unchanged_count": len(left_ids & right_ids),
            }
        left_gap_ids = {item["record"] for item in left_report["gaps"]}
        right_gap_ids = {item["record"] for item in right_report["gaps"]}
        summaries["declared-gaps"] = {
            "before_count": len(left_gap_ids),
            "after_count": len(right_gap_ids),
            "added_count": len(right_gap_ids - left_gap_ids),
            "removed_count": len(left_gap_ids - right_gap_ids),
            "unchanged_count": len(left_gap_ids & right_gap_ids),
        }

        if collection is None:
            return response(
                "observation-snapshot-comparison",
                before=before,
                after=after,
                before_generation=left_generation,
                after_generation=right_generation,
                same_generation_record=left_data["generation"] == right_data["generation"],
                same_generation_id=left_data["generation_id"] == right_data["generation_id"],
                same_root_inventory=(
                    left_data["root_inventory_digest"] == right_data["root_inventory_digest"]
                ),
                same_record_set=left_data["record_set_digest"] == right_data["record_set_digest"],
                collections=summaries,
                verification_check_changes=_check_changes(
                    left, left_bundle, right, right_bundle),
                coverage_changes=_coverage_changes(left, left_bundle, right, right_bundle),
                before_coverage=_coverage_summary(left, left_bundle),
                after_coverage=_coverage_summary(right, right_bundle),
                **{"before_" + key: value for key, value in _completeness_fields(left_report).items()},
                **{"after_" + key: value for key, value in _completeness_fields(right_report).items()},
                authority="build-record",
                interpretation=(
                    "Exact canonical set differences only. Added or removed facts are not "
                    "classified as regressions, causes, severity, chronology or blast radius."
                ),
                inspection=dict(before=left_metrics, after=right_metrics),
            )

        if collection == "declared-gaps":
            left_rows = {row["record"]: row for row in _gap_rows(left_report, left_bundle)}
            right_rows = {row["record"]: row for row in _gap_rows(right_report, right_bundle)}
            left_ids, right_ids = set(left_rows), set(right_rows)
        else:
            left_rows = right_rows = None
            left_ids = set(left_data["observations"][GROUP[collection]])
            right_ids = set(right_data["observations"][GROUP[collection]])
        changes = []
        for change, identities, bundle, gap_rows in (
            ("removed", left_ids - right_ids, left_bundle, left_rows),
            ("added", right_ids - left_ids, right_bundle, right_rows),
        ):
            for identity in identities:
                projected = (gap_rows[identity] if collection == "declared-gaps"
                             else _project_row(self, collection, identity, bundle["records"]))
                changes.append({
                    "id": change + ":" + identity,
                    "change": change,
                    "record": identity,
                    "observation": projected,
                })
        page = paginate(
            changes,
            scope=[self.scope, str(self.record_store), self.record_project_id,
                   "compare-observation-snapshots", before, after, collection],
            cursor=cursor,
            limit=limit,
        )
        return response(
            "observation-snapshot-comparison-collection",
            before=before,
            after=after,
            collection=collection,
            canonical_kind=EXPECTED_KIND[collection],
            summary=summaries[collection],
            changes=page,
            before_generation=left_generation,
            after_generation=right_generation,
            **{"before_" + key: value for key, value in _completeness_fields(left_report).items()},
            **{"after_" + key: value for key, value in _completeness_fields(right_report).items()},
            authority="build-record",
            interpretation="Canonical record-set differences only; no regression or causal judgment.",
            inspection=dict(before=left_metrics, after=right_metrics),
        )
