import unittest

from zog.integrate_observe import IntegrationObserver, ObservationError


A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
GEN_A = "sha256:" + "1" * 64
GEN_B = "sha256:" + "2" * 64
SRC_A = "sha256:" + "3" * 64
SRC_B = "sha256:" + "4" * 64
REL_PROVIDE_7 = "sha256:" + "5" * 64
REL_NEED_7 = "sha256:" + "6" * 64
REL_PROVIDE_8 = "sha256:" + "7" * 64
CHECK = "sha256:" + "8" * 64
EXEC_PASS = "sha256:" + "9" * 64
EXEC_FAIL = "sha256:" + "0" * 64
COVER_A = "sha256:" + "c" * 64
COVER_B = "sha256:" + "d" * 64
DEFINITION = "sha256:" + "e" * 64
GAP_A = "sha256:" + "a1" * 32
GAP_B = "sha256:" + "b1" * 32


def source(record, package, revision, archive):
    return {
        "id": record,
        "record": record,
        "availability": "available",
        "authority": "build-record",
        "canonical_kind": "source-provenance",
        "persistence": "stored",
        "gaps": [],
        "producer": "image-build",
        "producer_observation": "sha256:" + revision[0] * 64,
        "package": package,
        "project": package,
        "output": "sha256:" + "f" * 64,
        "build_inputs": "sha256:" + "1" * 64,
        "source_selection": "sha256:" + "2" * 64,
        "archive_record": "sha256:" + archive[7],
        "archive": {"digest": archive, "size": 100},
        "associations": [{
            "record": "sha256:" + "3" * 64,
            "availability": "available",
            "relationship": "declared-not-independently-reproduced",
            "reference_kind": "git",
            "reference_value": revision,
            "repository": "https://example.invalid/" + package,
        }],
    }


def relationship(record, package, relation, target_kind, target_value):
    return {
        "id": record,
        "record": record,
        "availability": "available",
        "authority": "build-record",
        "canonical_kind": "relationship-observation",
        "persistence": "stored",
        "gaps": [],
        "producer": "image-build",
        "producer_observation": record,
        "subject": {
            "kind": "artifact",
            "path": "/usr/bin/" + package,
            "digest": "sha256:" + "a" * 64,
            "packages": [package],
        },
        "relation": relation,
        "target": {"kind": target_kind, "value": target_value},
        "evidence": [],
    }


def execution(record, outcome):
    return {
        "id": record,
        "record": record,
        "availability": "available",
        "authority": "build-record",
        "canonical_kind": "verification-execution",
        "persistence": "stored",
        "gaps": [],
        "producer": "image-build",
        "producer_observation": record,
        "check_id": "consumer.integration",
        "definition_digest": DEFINITION,
        "subject": {"kind": "generation-candidate"},
        "attempt_id": "[\"host\",\"project\",\"attempt\"]",
        "build_id": "attempt:attempt",
        "sequence": 1,
        "outcome": outcome,
        "execution": {"kind": "command"},
        "environment_digest": "sha256:" + "f" * 64,
        "evidence": [],
        "granularity": "command",
        "timing": {"started_at": None, "ended_at": None},
    }


def gap(record, category, reason, kind="source-reference"):
    return {
        "id": record,
        "record": record,
        "canonical_kind": kind,
        "categories": [category],
        "reasons": [{"category": category, "reason": reason}],
        "reason_count": 1,
        "authority": "build-record",
        "persistence": "stored",
    }


class FakeTrace:
    def __init__(self):
        self.rows = {
            A: {
                "source-provenance": [source(SRC_A, "libfoo", "a1", "sha256:" + "a" * 64)],
                "relationships": [
                    relationship(REL_PROVIDE_7, "libfoo", "provides-soname", "soname", "libfoo.so.7"),
                    relationship(REL_NEED_7, "consumer", "needs-library", "soname", "libfoo.so.7"),
                ],
                "verification-checks": [{
                    "id": CHECK, "record": CHECK, "availability": "available",
                    "authority": "build-record", "canonical_kind": "verification-check",
                    "persistence": "stored", "gaps": [], "producer": "image-build",
                    "check_id": "consumer.integration", "definition_digest": DEFINITION,
                    "granularity": "command",
                }],
                "verification-executions": [execution(EXEC_PASS, "PASS")],
                "coverage": [{
                    "id": COVER_A, "record": COVER_A, "availability": "available",
                    "authority": "build-record", "canonical_kind": "observation-coverage",
                    "persistence": "stored", "gaps": [], "producer": "image-build",
                    "subject": {}, "family": "elf-interfaces", "collector": {}, "scope": {},
                    "outcome": "complete", "observation_count": 2, "details": {},
                }],
                "declared-gaps": [gap(
                    GAP_A, "upstream-identity", "upstream revision is unknown")],
            },
            B: {
                "source-provenance": [source(SRC_B, "libfoo", "b2", "sha256:" + "b" * 64)],
                "relationships": [
                    relationship(REL_PROVIDE_8, "libfoo", "provides-soname", "soname", "libfoo.so.8"),
                    relationship(REL_NEED_7, "consumer", "needs-library", "soname", "libfoo.so.7"),
                ],
                "verification-checks": [{
                    "id": CHECK, "record": CHECK, "availability": "available",
                    "authority": "build-record", "canonical_kind": "verification-check",
                    "persistence": "stored", "gaps": [], "producer": "image-build",
                    "check_id": "consumer.integration", "definition_digest": DEFINITION,
                    "granularity": "command",
                }],
                "verification-executions": [execution(EXEC_FAIL, "FAIL")],
                "coverage": [{
                    "id": COVER_B, "record": COVER_B, "availability": "available",
                    "authority": "build-record", "canonical_kind": "observation-coverage",
                    "persistence": "stored", "gaps": [], "producer": "image-build",
                    "subject": {}, "family": "elf-interfaces", "collector": {}, "scope": {},
                    "outcome": "complete", "observation_count": 2, "details": {},
                }],
                "declared-gaps": [gap(
                    GAP_B, "external-environment-runtime",
                    "controller/runtime implementation is outside canonical evidence")],
            },
        }

    def _summary(self, snapshot):
        gap = self.rows[snapshot]["declared-gaps"]
        category = gap[0]["categories"][0]
        return {
            "reference_closure_complete": True,
            "missing_record_count": 0,
            "declared_gap_free": False,
            "declared_gap_count": 1,
            "declared_gap_reason_count": 1,
            "declared_gap_summary": [{
                "category": category, "record_count": 1, "reason_count": 1,
            }],
        }

    def observation_snapshot(self, snapshot, *, collection=None, cursor=None, limit=20, **kwargs):
        if collection is None:
            generation = "ga" if snapshot == A else "gb"
            generation_record = GEN_A if snapshot == A else GEN_B
            coverage_record = COVER_A if snapshot == A else COVER_B
            return {
                "schema_version": 1,
                "kind": "observation-snapshot",
                "snapshot": snapshot,
                "availability": "available",
                "generation": generation,
                "generation_record": generation_record,
                "generation_id": f'["host","project","{generation}"]',
                "root_inventory_digest": "sha256:" + ("1" if snapshot == A else "2") * 64,
                "record_set_digest": "sha256:" + ("3" if snapshot == A else "4") * 64,
                "collections": {
                    name: {
                        "declared_count": len(self.rows[snapshot][name]),
                        "available_count": len(self.rows[snapshot][name]),
                        "canonical_kind": name,
                    }
                    for name in self.rows[snapshot]
                },
                "coverage": [{
                    "family": "elf-interfaces",
                    "record": coverage_record,
                    "outcome": "complete",
                    "observation_count": 2,
                }],
                "missing_records": [],
                "missing_records_truncated": False,
                **self._summary(snapshot),
                "authority": "build-record",
            }
        items = self.rows[snapshot][collection]
        return {
            "schema_version": 1,
            "kind": "observation-snapshot-collection",
            "snapshot": snapshot,
            "collection": collection,
            "items": {"items": items, "has_more": False, "next_cursor": None},
        }

    def compare_observation_snapshots(self, before, after, *, collection=None, cursor=None, limit=20):
        if collection is None:
            summaries = {}
            for name in self.rows[before]:
                left = {row["record"] for row in self.rows[before][name]}
                right = {row["record"] for row in self.rows[after][name]}
                summaries[name] = {
                    "before_count": len(left), "after_count": len(right),
                    "added_count": len(right - left), "removed_count": len(left - right),
                    "unchanged_count": len(left & right),
                }
            before_summary = self._summary(before)
            after_summary = self._summary(after)
            return {
                "schema_version": 1,
                "kind": "observation-snapshot-comparison",
                "before": before,
                "after": after,
                "before_generation": "ga",
                "after_generation": "gb",
                "same_generation_record": False,
                "same_generation_id": False,
                "same_root_inventory": False,
                "same_record_set": False,
                "collections": summaries,
                "verification_check_changes": [],
                "coverage_changes": [{
                    "family": "elf-interfaces",
                    "before_records": [COVER_A], "after_records": [COVER_B],
                    "pairing": "unique-family", "before_outcome": "complete",
                    "after_outcome": "complete", "before_observation_count": 2,
                    "after_observation_count": 2,
                }],
                "before_coverage": self.observation_snapshot(before)["coverage"],
                "after_coverage": self.observation_snapshot(after)["coverage"],
                **{"before_" + key: value for key, value in before_summary.items()},
                **{"after_" + key: value for key, value in after_summary.items()},
            }
        left = {row["record"]: row for row in self.rows[before][collection]}
        right = {row["record"]: row for row in self.rows[after][collection]}
        changes = []
        for record in sorted(left.keys() - right.keys()):
            changes.append({"id": "removed:" + record, "change": "removed",
                            "record": record, "observation": left[record]})
        for record in sorted(right.keys() - left.keys()):
            changes.append({"id": "added:" + record, "change": "added",
                            "record": record, "observation": right[record]})
        return {
            "schema_version": 1,
            "kind": "observation-snapshot-comparison-collection",
            "before": before,
            "after": after,
            "collection": collection,
            "changes": {"items": changes, "has_more": False, "next_cursor": None},
        }


class LegacyTrace(FakeTrace):
    def observation_snapshot(self, snapshot, **kwargs):
        result = super().observation_snapshot(snapshot, **kwargs)
        if kwargs.get("collection") is None:
            for key in (
                "reference_closure_complete", "declared_gap_free", "declared_gap_count",
                "declared_gap_reason_count", "declared_gap_summary",
            ):
                result.pop(key, None)
            result["metadata_closure_complete"] = False
        return result


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.observer = IntegrationObserver(FakeTrace())

    def test_world_separates_reference_closure_declared_gaps_and_coverage(self):
        world = self.observer.world(A)
        self.assertEqual(world["schema_version"], 2)
        self.assertEqual(world["kind"], "world")
        self.assertEqual(world["snapshot"], A)
        self.assertEqual(world["generation_record"], GEN_A)
        self.assertTrue(world["reference_closure_complete"])
        self.assertEqual(world["missing_record_count"], 0)
        self.assertFalse(world["declared_gap_free"])
        self.assertEqual(world["declared_gap_count"], 1)
        self.assertEqual(world["declared_gap_reason_count"], 1)
        self.assertEqual(world["declared_gap_summary"][0]["category"], "upstream-identity")
        self.assertEqual(world["coverage"][0]["outcome"], "complete")
        self.assertNotIn("metadata_closure_complete", world)
        self.assertFalse(world["interpretation"]["chronology_inferred"])
        self.assertFalse(world["interpretation"]["declared_gaps_treated_as_missing_records"])

    def test_two_world_vertical_slice_reports_independent_facts_and_gap_changes(self):
        result = self.observer.compare(A, B)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["kind"], "world-comparison")
        self.assertEqual(result["source_changes"][0]["package"], "libfoo")
        self.assertEqual(result["source_changes"][0]["change"], "changed")

        rel = result["canonical_changes"]["relationships"]
        removed = [x for x in rel if x["change"] == "removed"]
        added = [x for x in rel if x["change"] == "added"]
        self.assertEqual(removed[0]["observation"]["target"]["value"], "libfoo.so.7")
        self.assertEqual(added[0]["observation"]["target"]["value"], "libfoo.so.8")
        self.assertFalse(any(
            x["observation"]["relation"] == "needs-library" for x in rel
        ))

        gaps = result["declared_gap_changes"]
        self.assertEqual({x["change"] for x in gaps}, {"removed", "added"})
        self.assertIn("upstream revision is unknown", {
            reason["reason"]
            for item in gaps
            for reason in item["observation"]["reasons"]
        })
        self.assertTrue(result["evidence_completeness"]["both_reference_closures_complete"])
        self.assertFalse(result["evidence_completeness"]["baseline"]["declared_gap_free"])
        self.assertFalse(result["evidence_completeness"]["candidate"]["declared_gap_free"])

        verification = result["verification_execution_changes"]
        self.assertEqual(verification[0]["before_outcomes"], ["PASS"])
        self.assertEqual(verification[0]["after_outcomes"], ["FAIL"])
        self.assertFalse(verification[0]["regression_classified"])
        self.assertFalse(result["interpretation"]["causation_inferred"])
        self.assertFalse(result["interpretation"]["blast_radius_computed"])
        self.assertFalse(result["interpretation"]["declared_gap_reduction_classified_as_improvement"])

    def test_build_trace_011_completeness_shape_is_rejected(self):
        observer = IntegrationObserver(LegacyTrace())
        with self.assertRaises(ObservationError) as caught:
            observer.world(A)
        self.assertEqual(caught.exception.code, "unsupported-build-trace-contract")
        self.assertIn("build-trace 0.12", caught.exception.message)

    def test_same_snapshot_rejected(self):
        with self.assertRaises(ObservationError) as caught:
            self.observer.compare(A, A)
        self.assertEqual(caught.exception.code, "same-snapshot")

    def test_page_limit_bounds(self):
        with self.assertRaises(ValueError):
            IntegrationObserver(FakeTrace(), page_limit=0)
        with self.assertRaises(ValueError):
            IntegrationObserver(FakeTrace(), page_limit=101)


if __name__ == "__main__":
    unittest.main()
