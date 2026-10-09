import copy
import hashlib
import unittest

from zog.build_record import (RecordError, canonical, generation_observation_snapshot,
                          ingest_image_build_snapshot, inspect, make_record, record_id)
from examples.local_pipeline import fixture


def producer_id(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def terminal(generation_id, root_digest, invocation="invocation-1"):
    value = {
        "schema": "image-build-verification-observation-v1",
        "check_id": "image-build/installed-trust/command/0",
        "definition_digest": "sha256:" + "1" * 64,
        "subject": {
            "kind": "generation-candidate",
            "generation_id": generation_id,
            "root_inventory_digest": root_digest,
        },
        "attempt_id": '["host","project","attempt-1"]',
        "sequence": 0,
        "outcome": "PASS",
        "execution": {"invocation_id": invocation, "exit_code": 0},
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


def relationship():
    value = {
        "subject": {
            "kind": "artifact",
            "path": "/usr/bin/demo",
            "digest": "sha256:" + "3" * 64,
            "packages": ["demo-package"],
        },
        "relation": "needs-library",
        "target": {"kind": "soname", "value": "libc.so.6"},
        "evidence": {
            "kind": "elf-metadata",
            "tool": {"name": "readelf", "sha256": "4" * 64},
        },
    }
    value["id"] = producer_id(value)
    return value


def source_row(bundle, ids):
    selected = bundle["records"][ids["source"]]["data"]
    archive = copy.deepcopy(selected["archives"][0])
    value = {
        "package": "demo-package",
        "project": "demo-project",
        "output_record": ids["output"],
        "build_inputs_record": ids["inputs"],
        "source_selection_record": ids["source"],
        "pin": copy.deepcopy(selected["pin"]),
        "archive": archive,
        "downloads": [{
            "url": "https://example.invalid/demo.tar.xz",
            "sha256": archive["digest"][7:],
            "destination": archive["name"],
            "archive": True,
        }],
        "upstream": [{
            "repository": "https://example.invalid/demo.git",
            "revision": "a" * 40,
            "revision_type": "git",
        }],
        "archive_revision_relationship": "declared-not-independently-reproduced",
        "release_tags": [],
        "gaps": [],
    }
    value["id"] = producer_id(value)
    return value


def envelope(bundle, ids, results):
    generation = bundle["records"][bundle["roots"][0]]["data"]
    root_digest = "sha256:" + "e" * 64
    rel = relationship()
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
            "checks": [{
                "check_id": results[0]["check_id"],
                "definition_digest": results[0]["definition_digest"],
                "granularity": "command",
            }],
            "results": results,
            "coverage": "named installed command checks only; no parsed upstream subtests",
        },
        "relationships": [rel],
        "sources": [source_row(bundle, ids)],
        "coverage": {
            "elf_files": 1,
            "script_files": 0,
            "readelf": {"name": "readelf", "sha256": "4" * 64},
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


def rooted_bundle(base, new_records, root):
    return {
        "schema_version": 1,
        "roots": [root],
        "records": {
            **base["records"],
            **{record_id(record): record for record in new_records},
        },
    }


class GenerationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _, self.ids = fixture()
        self.generation = self.bundle["roots"][0]
        self.generation_id = self.bundle["records"][self.generation]["data"]["generation_id"]
        self.root_digest = "sha256:" + "e" * 64
        self.first = terminal(self.generation_id, self.root_digest)

    def test_image_build_snapshot_is_portable_root_for_all_canonical_families(self):
        records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        snapshot = records[-1]
        self.assertEqual(snapshot["kind"], "generation-observation-snapshot")
        groups = snapshot["data"]["observations"]
        self.assertEqual(len(groups["verification_checks"]), 1)
        self.assertEqual(len(groups["verification_executions"]), 1)
        self.assertEqual(len(groups["relationships"]), 1)
        self.assertEqual(len(groups["source_provenance"]), 1)
        self.assertEqual(len(groups["coverage"]), 6)

        snapshot_id = record_id(snapshot)
        report = inspect(rooted_bundle(self.bundle, records, snapshot_id))
        self.assertTrue(report["snapshots"])
        self.assertEqual(report["snapshots"][0]["record"], snapshot_id)
        self.assertEqual(report["snapshots"][0]["record_set_digest"],
                         snapshot["data"]["record_set_digest"])
        self.assertEqual(len(report["verification"]), 1)
        self.assertEqual(len(report["relationships"]), 1)
        self.assertEqual(len(report["source_provenance"]), 1)
        self.assertEqual(len(report["coverage"]), 6)

    def test_later_execution_creates_s2_without_mutating_generation_or_s1(self):
        first_records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        s1 = first_records[-1]
        s1_id = record_id(s1)
        first_execution = s1["data"]["observations"]["verification_executions"][0]

        second = terminal(self.generation_id, self.root_digest, "invocation-2")
        second_records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first, second]), self.bundle)
        s2 = second_records[-1]
        s2_id = record_id(s2)

        self.assertEqual(s1["data"]["generation"], self.generation)
        self.assertEqual(s2["data"]["generation"], self.generation)
        self.assertEqual(s1["data"]["generation_id"], self.generation_id)
        self.assertEqual(s2["data"]["generation_id"], self.generation_id)
        self.assertEqual(record_id(s1), s1_id)
        self.assertNotEqual(s1_id, s2_id)
        self.assertNotEqual(s1["data"]["record_set_digest"],
                            s2["data"]["record_set_digest"])
        self.assertEqual(
            set(s2["data"]["observations"]["verification_executions"]) -
            set(s1["data"]["observations"]["verification_executions"]),
            {next(identity for identity in
                  s2["data"]["observations"]["verification_executions"]
                  if identity != first_execution)})
        self.assertEqual(
            s1["data"]["observations"]["verification_checks"],
            s2["data"]["observations"]["verification_checks"])
        self.assertEqual(
            s1["data"]["observations"]["relationships"],
            s2["data"]["observations"]["relationships"])
        self.assertEqual(
            s1["data"]["observations"]["source_provenance"],
            s2["data"]["observations"]["source_provenance"])

    def test_independent_consumer_can_diff_two_snapshot_exports_by_canonical_ids(self):
        one = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        second = terminal(self.generation_id, self.root_digest, "invocation-2")
        two = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first, second]), self.bundle)
        s1, s2 = one[-1], two[-1]
        report1 = inspect(rooted_bundle(self.bundle, one, record_id(s1)))
        report2 = inspect(rooted_bundle(self.bundle, two, record_id(s2)))
        a = report1["snapshots"][0]["observations"]
        b = report2["snapshots"][0]["observations"]
        added = set(b["verification_executions"]) - set(a["verification_executions"])
        self.assertEqual(len(added), 1)
        self.assertEqual(a["verification_checks"], b["verification_checks"])
        self.assertEqual(a["relationships"], b["relationships"])
        self.assertEqual(a["source_provenance"], b["source_provenance"])

    def test_snapshot_rejects_execution_without_included_definition(self):
        records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        snapshot = records[-1]
        execution = snapshot["data"]["observations"]["verification_executions"][0]
        bad = generation_observation_snapshot(
            self.generation, self.generation_id, self.root_digest,
            verification_executions=[execution])
        with self.assertRaises(RecordError):
            inspect(rooted_bundle(self.bundle, records + [bad], record_id(bad)))

    def test_snapshot_rejects_observation_subject_from_another_root_inventory(self):
        records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        snapshot = records[-1]
        groups = snapshot["data"]["observations"]
        bad = generation_observation_snapshot(
            self.generation, self.generation_id, "sha256:" + "9" * 64,
            verification_checks=groups["verification_checks"],
            verification_executions=groups["verification_executions"],
            relationships=groups["relationships"],
            source_provenance=groups["source_provenance"],
            coverage=groups["coverage"])
        with self.assertRaises(RecordError):
            inspect(rooted_bundle(self.bundle, records + [bad], record_id(bad)))

    def test_snapshot_record_set_digest_is_checked(self):
        records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        data = copy.deepcopy(records[-1]["data"])
        data["record_set_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(RecordError):
            make_record("generation-observation-snapshot", data)

    def test_constructor_sorts_input_but_does_not_hide_duplicates(self):
        records = ingest_image_build_snapshot(
            envelope(self.bundle, self.ids, [self.first]), self.bundle)
        groups = records[-1]["data"]["observations"]
        coverage = list(reversed(groups["coverage"]))
        left = generation_observation_snapshot(
            self.generation, self.generation_id, self.root_digest,
            coverage=coverage)
        right = generation_observation_snapshot(
            self.generation, self.generation_id, self.root_digest,
            coverage=groups["coverage"])
        self.assertEqual(record_id(left), record_id(right))
        with self.assertRaises(RecordError):
            generation_observation_snapshot(
                self.generation, self.generation_id, self.root_digest,
                coverage=[groups["coverage"][0], groups["coverage"][0]])

    def test_empty_legacy_snapshot_does_not_invent_observations(self):
        snapshot = generation_observation_snapshot(
            self.generation, self.generation_id, self.root_digest)
        report = inspect(rooted_bundle(self.bundle, [snapshot], record_id(snapshot)))
        groups = report["snapshots"][0]["observations"]
        self.assertTrue(all(not identities for identities in groups.values()))


if __name__ == "__main__":
    unittest.main()
