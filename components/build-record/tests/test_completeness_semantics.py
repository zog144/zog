import copy
import unittest

from zog.build_record import (generation_observation_snapshot, inspect, make_record,
                          record_id)
from examples.local_pipeline import fixture


ROOT_DIGEST = "sha256:" + "9" * 64
COLLECTOR_DIGEST = "sha256:" + "8" * 64


def coverage_record(generation_id, family, outcome, *, count=0, details=None):
    return make_record("observation-coverage", {
        "producer": {"name": "fixture", "contract": "fixture-coverage-v1"},
        "subject": {
            "kind": "generation-candidate",
            "generation_id": generation_id,
            "root_inventory_digest": ROOT_DIGEST,
        },
        "family": family,
        "collector": {"implementation_digest": COLLECTOR_DIGEST},
        "scope": {"fixture": family},
        "outcome": outcome,
        "observation_count": count,
        "details": details or {},
    })


def snapshot_bundle(base, snapshot, extra=()):
    records = {
        **base["records"],
        **{record_id(record): record for record in extra},
        record_id(snapshot): snapshot,
    }
    return {
        "schema_version": 1,
        "roots": [record_id(snapshot)],
        "records": records,
    }


class CompletenessSemanticsTests(unittest.TestCase):
    def test_complete_reference_closure_and_zero_declared_gaps(self):
        bundle, _, _ = fixture()
        report = inspect(bundle)
        self.assertTrue(report["reference_closure_complete"])
        self.assertEqual(report["missing_record_count"], 0)
        self.assertTrue(report["declared_gap_free"])
        self.assertEqual(report["declared_gap_count"], 0)
        self.assertEqual(report["declared_gap_record_count"], 0)
        self.assertEqual(report["declared_gap_summary"],
                         {"record_count": 0, "reason_count": 0, "by_kind": []})
        self.assertTrue(report["complete"])

    def test_complete_reference_closure_with_declared_gaps(self):
        bundle, _, _ = fixture(legacy=True)
        generation = bundle["records"][bundle["roots"][0]]["data"]
        snapshot = generation_observation_snapshot(
            bundle["roots"][0], generation["generation_id"], ROOT_DIGEST)
        report = inspect(snapshot_bundle(bundle, snapshot))

        self.assertTrue(report["reference_closure_complete"])
        self.assertEqual(report["missing_record_count"], 0)
        self.assertFalse(report["declared_gap_free"])
        self.assertGreater(report["declared_gap_count"], 0)
        self.assertGreater(report["declared_gap_record_count"], 0)
        self.assertEqual(report["declared_gap_summary"]["reason_count"],
                         report["declared_gap_count"])
        self.assertEqual(report["declared_gap_summary"]["record_count"],
                         report["declared_gap_record_count"])
        self.assertTrue(report["declared_gap_summary"]["by_kind"])
        self.assertFalse(report["complete"])
        self.assertTrue(report["snapshots"])

    def test_missing_reference_is_separate_from_declared_gaps(self):
        clean, _, clean_ids = fixture()
        del clean["records"][clean_ids["source"]]
        clean_report = inspect(clean)
        self.assertFalse(clean_report["reference_closure_complete"])
        self.assertEqual(clean_report["missing_record_count"], 1)
        self.assertTrue(clean_report["declared_gap_free"])
        self.assertFalse(clean_report["complete"])

        legacy, _, legacy_ids = fixture(legacy=True)
        del legacy["records"][legacy_ids["assembly_result"]]
        legacy_report = inspect(legacy)
        self.assertFalse(legacy_report["reference_closure_complete"])
        self.assertGreaterEqual(legacy_report["missing_record_count"], 1)
        self.assertFalse(legacy_report["declared_gap_free"])
        self.assertGreater(legacy_report["declared_gap_count"], 0)
        self.assertFalse(legacy_report["complete"])

    def test_snapshot_with_complete_zero_count_coverage(self):
        bundle, _, _ = fixture()
        generation_record = bundle["roots"][0]
        generation_id = bundle["records"][generation_record]["data"]["generation_id"]
        coverage = coverage_record(
            generation_id, "elf-interfaces", "complete", count=0,
            details={"examined": "installed-regular-elf"})
        coverage_id = record_id(coverage)
        snapshot = generation_observation_snapshot(
            generation_record, generation_id, ROOT_DIGEST,
            coverage=[coverage_id])
        report = inspect(snapshot_bundle(bundle, snapshot, [coverage]))

        self.assertTrue(report["reference_closure_complete"])
        self.assertTrue(report["declared_gap_free"])
        self.assertTrue(report["complete"])
        self.assertEqual(report["coverage"][0]["outcome"], "complete")
        self.assertEqual(report["coverage"][0]["observation_count"], 0)

    def test_snapshot_with_partial_and_unavailable_coverage(self):
        bundle, _, _ = fixture()
        generation_record = bundle["roots"][0]
        generation_id = bundle["records"][generation_record]["data"]["generation_id"]
        partial = coverage_record(
            generation_id, "verification-commands", "partial",
            details={"reason": "scope intentionally bounded"})
        unavailable = coverage_record(
            generation_id, "elf-interfaces", "unavailable",
            details={"reason": "collector unavailable"})
        snapshot = generation_observation_snapshot(
            generation_record, generation_id, ROOT_DIGEST,
            coverage=[record_id(partial), record_id(unavailable)])
        report = inspect(snapshot_bundle(bundle, snapshot, [partial, unavailable]))

        self.assertTrue(report["reference_closure_complete"])
        self.assertTrue(report["declared_gap_free"])
        self.assertTrue(report["complete"])
        self.assertEqual(
            {item["family"]: item["outcome"] for item in report["coverage"]},
            {"elf-interfaces": "unavailable", "verification-commands": "partial"})

    def test_multiple_snapshots_do_not_mutate_generation_or_prior_snapshot(self):
        bundle, _, _ = fixture()
        generation_record = bundle["roots"][0]
        generation_id = bundle["records"][generation_record]["data"]["generation_id"]
        empty = coverage_record(generation_id, "script-interpreters", "complete")
        first = generation_observation_snapshot(
            generation_record, generation_id, ROOT_DIGEST,
            coverage=[record_id(empty)])
        first_id = record_id(first)
        first_copy = copy.deepcopy(first)

        later = coverage_record(
            generation_id, "verification-commands", "partial",
            details={"reason": "newer observation"})
        second = generation_observation_snapshot(
            generation_record, generation_id, ROOT_DIGEST,
            coverage=[record_id(empty), record_id(later)])

        self.assertEqual(first, first_copy)
        self.assertEqual(record_id(first), first_id)
        self.assertEqual(first["data"]["generation"], generation_record)
        self.assertEqual(second["data"]["generation"], generation_record)
        self.assertNotEqual(first_id, record_id(second))
        self.assertNotEqual(first["data"]["record_set_digest"],
                            second["data"]["record_set_digest"])


if __name__ == "__main__":
    unittest.main()
