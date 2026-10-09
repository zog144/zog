import copy
import hashlib
import unittest

from zog.build_record import (canonical, ingest_image_build_candidate_checks,
                          ingest_image_build_checks, ingest_image_build_coverage,
                          inspect, make_record, record_id, verification_check)
from examples.local_pipeline import fixture


def producer_id(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def terminal(generation_id, root_digest, definition="sha256:" + "1" * 64):
    value = {
        "schema": "image-build-verification-observation-v1",
        "check_id": "image-build/installed-trust/command/0",
        "definition_digest": definition,
        "subject": {
            "kind": "generation-candidate",
            "generation_id": generation_id,
            "root_inventory_digest": root_digest,
        },
        "attempt_id": '["host","project","attempt-1"]',
        "sequence": 0,
        "outcome": "PASS",
        "execution": {"invocation_id": "invocation-1", "exit_code": 0},
        "environment_digest": "sha256:" + "2" * 64,
        "evidence": [{"kind": "build-trace", "host_id": "host",
                      "build_id": "attempt:attempt-1"}],
        "granularity": "command",
        "timing": {"started_at": None, "finished_at": None,
                   "observed_at": "2026-10-06T12:00:00+00:00"},
        "producer": {"name": "image-build",
                     "contract": "image-build-verification-observation-v1"},
    }
    value["id"] = producer_id(value)
    return value


def base_coverage():
    return {
        "elf_files": 0,
        "script_files": 0,
        "readelf": {"name": "readelf", "sha256": "a" * 64},
        "symlinks": "not-followed",
        "resolution": "interfaces-only",
        "unsupported": ["dlopen", "ABI-compatibility", "service-dependencies",
                        "env-PATH-resolution"],
    }


def generation_envelope(bundle, *, checks=None, results=None, relationships=None,
                        sources=None, coverage=None, gaps=None):
    generation = bundle["records"][bundle["roots"][0]]["data"]
    root_digest = "sha256:" + "e" * 64
    value = {
        "schema": "image-build-integration-observations-v1",
        "producer": {
            "name": "image-build",
            "contract": "image-build-integration-observations-v1",
            "implementation_digest": "sha256:" + "d" * 64,
        },
        "context": {
            "generation_id": generation["generation_id"],
            "generation_record": bundle["roots"][0],
            "root_inventory_digest": root_digest,
        },
        "verification": {
            "checks": checks or [],
            "results": results or [],
            "coverage": "named installed command checks only; no parsed upstream subtests",
        },
        "relationships": relationships or [],
        "sources": sources or [],
        "coverage": coverage or base_coverage(),
        "gaps": gaps or [],
        "derivation": "post-build-inspection; does not retrofit canonical pre-execution evidence",
    }
    value["id"] = producer_id(value)
    return value


def candidate(generation_id, results):
    return {
        "schema": "image-build-candidate-verifications-v1",
        "generation_id": generation_id,
        "results": results,
        "coverage": "captured terminal commands only; absence is not SKIP",
    }


class CheckAndCoverageTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _, self.ids = fixture()
        self.generation_id = self.bundle["records"][self.bundle["roots"][0]]["data"]["generation_id"]
        self.root_digest = "sha256:" + "e" * 64

    def test_candidate_and_generation_share_check_definition_identity(self):
        result = terminal(self.generation_id, self.root_digest)
        candidate_check = ingest_image_build_candidate_checks(
            candidate(self.generation_id, [result]))[0]
        declared = {
            "check_id": result["check_id"],
            "definition_digest": result["definition_digest"],
            "granularity": "command",
        }
        generation_check = ingest_image_build_checks(
            generation_envelope(self.bundle, checks=[declared], results=[result]),
            self.bundle)[0]
        self.assertEqual(record_id(candidate_check), record_id(generation_check))

    def test_same_logical_check_changed_definition_is_distinct(self):
        first = verification_check({
            "check_id": "image-build/trust/command/0",
            "definition_digest": "sha256:" + "1" * 64,
            "granularity": "command",
        })
        second = verification_check({
            "check_id": "image-build/trust/command/0",
            "definition_digest": "sha256:" + "2" * 64,
            "granularity": "command",
        })
        self.assertEqual(first["data"]["check_id"], second["data"]["check_id"])
        self.assertNotEqual(record_id(first), record_id(second))

    def test_generation_derives_definition_from_execution_when_check_list_is_empty(self):
        result = terminal(self.generation_id, self.root_digest)
        records = ingest_image_build_checks(
            generation_envelope(
                self.bundle, results=[result],
                gaps=[{"reason": "no-canonical-named-verification-report"}]),
            self.bundle)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["definition_digest"],
                         result["definition_digest"])

    def test_complete_empty_coverage_is_distinct_from_missing_collection(self):
        records = ingest_image_build_coverage(generation_envelope(self.bundle), self.bundle)
        by_family = {record["data"]["family"]: record for record in records}
        self.assertEqual(by_family["elf-interfaces"]["data"]["outcome"], "complete")
        self.assertEqual(by_family["elf-interfaces"]["data"]["observation_count"], 0)
        self.assertEqual(by_family["script-interpreters"]["data"]["outcome"], "complete")
        self.assertEqual(by_family["source-provenance"]["data"]["outcome"], "complete")

    def test_readelf_unavailable_marks_elf_family_unavailable(self):
        coverage = base_coverage()
        coverage["elf_files"] = 2
        coverage["readelf"] = None
        value = generation_envelope(
            self.bundle, coverage=coverage,
            gaps=[{"path": "/usr/bin/demo", "reason": "readelf-unavailable"}])
        records = ingest_image_build_coverage(value, self.bundle)
        elf = next(record for record in records
                   if record["data"]["family"] == "elf-interfaces")
        self.assertEqual(elf["data"]["outcome"], "unavailable")
        self.assertEqual(elf["data"]["observation_count"], 0)

    def test_per_file_inspection_failure_marks_family_partial(self):
        coverage = base_coverage()
        coverage["elf_files"] = 3
        value = generation_envelope(
            self.bundle, coverage=coverage,
            gaps=[{"path": "/usr/bin/demo", "reason": "readelf-timeout"}])
        elf = next(record for record in ingest_image_build_coverage(value, self.bundle)
                   if record["data"]["family"] == "elf-interfaces")
        self.assertEqual(elf["data"]["outcome"], "partial")
        self.assertEqual(elf["data"]["details"]["file_count"], 3)

    def test_verification_coverage_remains_partial_for_explicit_exclusions(self):
        result = terminal(self.generation_id, self.root_digest)
        check = {"check_id": result["check_id"],
                 "definition_digest": result["definition_digest"],
                 "granularity": "command"}
        coverage = ingest_image_build_coverage(
            generation_envelope(self.bundle, checks=[check], results=[result]),
            self.bundle)
        verification = next(record for record in coverage
                            if record["data"]["family"] == "verification-commands")
        self.assertEqual(verification["data"]["outcome"], "partial")
        self.assertIn("upstream-subtests", verification["data"]["details"]["exclusions"])

    def test_no_named_verification_evidence_can_be_unavailable(self):
        value = generation_envelope(
            self.bundle,
            gaps=[{"reason": "no-canonical-named-verification-report"}])
        verification = next(
            record for record in ingest_image_build_coverage(value, self.bundle)
            if record["data"]["family"] == "verification-commands")
        self.assertEqual(verification["data"]["outcome"], "unavailable")

    def test_dependency_declaration_gap_does_not_poison_other_families(self):
        value = generation_envelope(
            self.bundle,
            gaps=[{"package": "demo-package",
                   "reason": "no-frozen-dependency-declaration"}])
        coverage = {record["data"]["family"]: record["data"]["outcome"]
                    for record in ingest_image_build_coverage(value, self.bundle)}
        self.assertEqual(coverage["declared-package-dependencies"], "partial")
        self.assertEqual(coverage["used-build-output"], "complete")
        self.assertEqual(coverage["source-provenance"], "complete")

    def test_reserved_not_performed_and_not_applicable_are_distinct(self):
        common = {
            "producer": {"name": "fixture", "contract": "fixture-v1"},
            "subject": {"kind": "generation-candidate",
                        "generation_id": "fixture-generation",
                        "root_inventory_digest": "sha256:" + "9" * 64},
            "family": "source-provenance",
            "collector": {"implementation_digest": "sha256:" + "8" * 64},
            "scope": {"packages": "fixture"},
            "observation_count": 0,
            "details": {},
        }
        not_performed = make_record(
            "observation-coverage", {**common, "outcome": "not-performed"})
        not_applicable = make_record(
            "observation-coverage", {**common, "outcome": "not-applicable"})
        self.assertNotEqual(record_id(not_performed), record_id(not_applicable))

    def test_partial_coverage_does_not_mean_metadata_closure_is_corrupt(self):
        common = {
            "producer": {"name": "fixture", "contract": "fixture-v1"},
            "subject": {"kind": "generation-candidate",
                        "generation_id": "fixture-generation",
                        "root_inventory_digest": "sha256:" + "7" * 64},
            "family": "verification-commands",
            "collector": {"implementation_digest": "sha256:" + "6" * 64},
            "scope": {"selection": "named"},
            "outcome": "partial",
            "observation_count": 0,
            "details": {"reason": "scope intentionally bounded"},
        }
        record = make_record("observation-coverage", common)
        identity = record_id(record)
        report = inspect({"schema_version": 1, "roots": [identity],
                          "records": {identity: record}})
        self.assertTrue(report["complete"])
        self.assertEqual(report["coverage"][0]["outcome"], "partial")


if __name__ == "__main__":
    unittest.main()
