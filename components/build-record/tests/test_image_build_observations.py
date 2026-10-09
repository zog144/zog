import copy
import hashlib
import tempfile
import unittest

from zog.build_record import (RecordError, Store, canonical, ingest_image_build_candidate,
                          ingest_image_build_generation, inspect, record_id,
                          validate_image_build_candidate, validate_image_build_generation)
from examples.local_pipeline import fixture


def producer_id(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def observation(generation_id, root_digest, *, outcome="PASS", definition=None,
                invocation="invocation-1", observed_at="2026-10-06T12:00:00+00:00"):
    value = {
        "schema": "image-build-verification-observation-v1",
        "check_id": "image-build/installed-trust/command/0",
        "definition_digest": definition or ("sha256:" + "1" * 64),
        "subject": {
            "kind": "generation-candidate",
            "generation_id": generation_id,
            "root_inventory_digest": root_digest,
        },
        "attempt_id": '["host","project","attempt-1"]',
        "sequence": 0,
        "outcome": outcome,
        "execution": {"invocation_id": invocation, "exit_code": 0 if outcome == "PASS" else 2},
        "environment_digest": "sha256:" + "2" * 64,
        "evidence": [{"kind": "build-trace", "host_id": "host", "build_id": "attempt:attempt-1"}],
        "granularity": "command",
        "timing": {"started_at": None, "finished_at": None, "observed_at": observed_at},
        "producer": {"name": "image-build", "contract": "image-build-verification-observation-v1"},
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


def generation_export(bundle, result):
    generation_id = bundle["records"][bundle["roots"][0]]["data"]["generation_id"]
    value = {
        "schema": "image-build-integration-observations-v1",
        "producer": {
            "name": "image-build",
            "contract": "image-build-integration-observations-v1",
            "implementation_digest": "sha256:" + "3" * 64,
        },
        "context": {
            "generation_id": generation_id,
            "generation_record": bundle["roots"][0],
            "root_inventory_digest": result["subject"]["root_inventory_digest"],
        },
        "verification": {
            "checks": [{
                "check_id": result["check_id"],
                "definition_digest": result["definition_digest"],
                "granularity": "command",
            }],
            "results": [result],
            "coverage": "named installed command checks only; no parsed upstream subtests",
        },
        "relationships": [],
        "sources": [],
        "coverage": {
            "elf_files": 0,
            "script_files": 0,
            "readelf": {"name": "readelf", "sha256": "f" * 64},
            "symlinks": "not-followed",
            "resolution": "interfaces-only",
            "unsupported": ["dlopen", "ABI-compatibility", "service-dependencies",
                            "env-PATH-resolution"],
        },
        "gaps": [],
        "derivation": "post-build-inspection; does not retrofit canonical pre-execution evidence",
    }
    value["id"] = producer_id(value)
    return value


class ImageBuildObservationTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _, self.ids = fixture()
        self.generation_id = self.bundle["records"][self.bundle["roots"][0]]["data"]["generation_id"]
        self.root_digest = "sha256:" + "4" * 64
        self.result = observation(self.generation_id, self.root_digest)

    def test_candidate_and_published_generation_reuse_canonical_execution_identity(self):
        candidate_record = ingest_image_build_candidate(
            candidate(self.generation_id, [self.result]))[0]
        published_record = ingest_image_build_generation(
            generation_export(self.bundle, self.result), self.bundle)[0]
        self.assertEqual(record_id(candidate_record), record_id(published_record))
        self.assertEqual(candidate_record["data"]["producer_observation"], self.result["id"])
        self.assertNotIn("generation_record", candidate_record["data"]["subject"])

    def test_store_exports_generation_and_verification_as_independent_roots(self):
        verification = ingest_image_build_generation(
            generation_export(self.bundle, self.result), self.bundle)[0]
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for record in self.bundle["records"].values():
                store.put(record)
            verification_id = store.put(verification)
            exported = store.bundle([self.bundle["roots"][0], verification_id])
            report = inspect(exported)
            self.assertTrue(report["complete"])
            self.assertEqual(report["verification"][0]["record"], verification_id)
            self.assertEqual(report["verification"][0]["check_id"], self.result["check_id"])
            self.assertEqual(report["verification"][0]["outcome"], "PASS")

    def test_unpublished_candidate_is_a_valid_independent_record(self):
        verification = ingest_image_build_candidate(
            candidate(self.generation_id, [self.result]))[0]
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            verification_id = store.put(verification)
            report = inspect(store.bundle([verification_id]))
            self.assertTrue(report["complete"])
            self.assertEqual(report["verification"][0]["subject"]["generation_id"], self.generation_id)

    def test_repeated_check_and_changed_definition_are_distinct_records(self):
        repeated = observation(self.generation_id, self.root_digest,
                               outcome="FAIL", invocation="invocation-2")
        changed = observation(self.generation_id, self.root_digest,
                              definition="sha256:" + "5" * 64, invocation="invocation-3")
        records = ingest_image_build_candidate(
            candidate(self.generation_id, [self.result, repeated, changed]))
        self.assertEqual(len({record_id(record) for record in records}), 3)
        self.assertEqual({record["data"]["check_id"] for record in records},
                         {self.result["check_id"]})
        self.assertEqual(len({record["data"]["definition_digest"] for record in records}), 2)

    def test_error_and_historical_null_observation_time_are_preserved(self):
        result = observation(self.generation_id, self.root_digest, outcome="ERROR",
                             invocation="invocation-error", observed_at=None)
        record = ingest_image_build_candidate(candidate(self.generation_id, [result]))[0]
        self.assertEqual(record["data"]["outcome"], "ERROR")
        self.assertIsNone(record["data"]["timing"]["observed_at"])

    def test_tampered_observation_identity_is_rejected(self):
        value = copy.deepcopy(self.result)
        value["outcome"] = "FAIL"
        with self.assertRaises(RecordError):
            validate_image_build_candidate(candidate(self.generation_id, [value]))

    def test_published_generation_context_must_match_canonical_generation(self):
        value = generation_export(self.bundle, self.result)
        value["context"]["generation_id"] = "different-owner-generation"
        value["id"] = producer_id({key: child for key, child in value.items() if key != "id"})
        with self.assertRaises(RecordError):
            validate_image_build_generation(value, self.bundle)

    def test_published_root_inventory_must_match_each_result(self):
        value = generation_export(self.bundle, self.result)
        value["context"]["root_inventory_digest"] = "sha256:" + "9" * 64
        value["id"] = producer_id({key: child for key, child in value.items() if key != "id"})
        with self.assertRaises(RecordError):
            validate_image_build_generation(value, self.bundle)

    def test_unsupported_producer_schema_is_rejected(self):
        value = candidate(self.generation_id, [self.result])
        value["schema"] = "image-build-candidate-verifications-v2"
        with self.assertRaises(RecordError):
            validate_image_build_candidate(value)


if __name__ == "__main__":
    unittest.main()
