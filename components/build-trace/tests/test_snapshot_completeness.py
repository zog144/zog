"""Canonical-only snapshot completeness and declared-gap contract tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zog.build_trace import BuildTrace, TraceError


def rid(token):
    return "sha256:" + (token * 64)[:64]


class FakeLib:
    @staticmethod
    def record_id(record):
        return record["_id"]

    @staticmethod
    def snapshot_record_set_digest(generation, observations):
        return rid("f")


class FakeReader:
    graphs = {}

    def __init__(self, trace):
        self.trace = trace
        self.lib = FakeLib

    def graph(self, root):
        return self.graphs[root]

    def finish(self):
        return {"owner": {"source_bytes": 0}, "records": {"source_bytes": 0}}


class SnapshotCompletenessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "offline-project"
        # Deliberately do not create PROJECT/state/image-build.
        self.record_store = Path(temporary.name) / "canonical-records"
        self.trace = BuildTrace(
            self.root,
            host_id="host",
            record_store=self.record_store,
            record_project_id="project",
        )
        self.assertFalse((self.root / "state/image-build").exists())

        self.generation = "g" * 64
        self.generation_id = json.dumps(
            ["host", "project", self.generation], separators=(",", ":"))
        self.generation_record = self.record("generation", {
            "generation_id": self.generation_id,
            "assembly_result": rid("0"),
            "packages": [],
            "artifact": {"name": "rootfs", "digest": rid("1"), "size": 1},
            "content_manifest": {"name": "manifest", "digest": rid("2"), "size": 1},
            "verification": [],
        }, "0")

        self.check = self.record("verification-check", {
            "producer": {"name": "image-build", "contract": "fixture"},
            "check_id": "image-build/demo/command/0",
            "definition_digest": rid("3"),
            "granularity": "command",
        }, "3")
        self.execution = self.record("verification-execution", {
            "producer": {"name": "image-build", "contract": "fixture"},
            "producer_observation": rid("4"),
            "check_id": self.check["data"]["check_id"],
            "definition_digest": self.check["data"]["definition_digest"],
            "subject": {
                "kind": "generation-candidate",
                "generation_id": self.generation_id,
                "root_inventory_digest": rid("5"),
            },
            "attempt_id": json.dumps(["host", "project", "verify"], separators=(",", ":")),
            "sequence": 0,
            "outcome": "PASS",
            "execution": {"invocation_id": "invocation", "exit_code": 0},
            "environment_digest": rid("6"),
            "evidence": [{
                "kind": "build-trace", "host_id": "host", "build_id": "attempt:verify"
            }],
            "granularity": "command",
            "timing": {"started_at": None, "finished_at": None, "observed_at": None},
        }, "4")
        self.relationship = self.record("relationship-observation", {
            "producer": {"name": "image-build", "contract": "fixture"},
            "producer_observation": rid("7"),
            "subject": {
                "kind": "artifact",
                "path": "/usr/bin/demo",
                "digest": rid("8"),
                "packages": ["demo"],
            },
            "relation": "needs-library",
            "target": {"kind": "soname", "value": "libdemo.so.1"},
            "evidence": {
                "kind": "elf-metadata",
                "tool": {"name": "readelf", "sha256": "9" * 64},
            },
        }, "7")
        self.coverage_elf_complete = self.coverage(
            "elf-interfaces", "complete", 0, "a")
        self.coverage_verification_unavailable = self.coverage(
            "verification-commands", "unavailable", 0, "b")
        self.coverage_elf_partial = self.coverage(
            "elf-interfaces", "partial", 1, "c")

        self.gap_upstream = self.record(
            "source-reference", {"kind": "unknown"}, "d",
            gaps=["Upstream source reference is explicitly unknown."])
        self.gap_output = self.record(
            "package-output", {"package": "demo"}, "e",
            gaps=[
                "Package output is represented by a verified inventory artifact; "
                "output file bytes are retained by image-build, not this artifact store."
            ])
        self.gap_environment = self.record(
            "build-inputs", {"package": "demo"}, "f",
            gaps=[
                "Controller/runtime implementation bytes, custom execution callbacks "
                "and host kernel are not captured.",
                "Environment outside the canonical allowlist: SECRET_SETTING",
            ])

        self.s1 = self.snapshot(
            "a1",
            coverage=[self.coverage_elf_complete["_id"],
                      self.coverage_verification_unavailable["_id"]])
        self.s2 = self.snapshot(
            "b2",
            coverage=[self.coverage_elf_partial["_id"],
                      self.coverage_verification_unavailable["_id"]])

        self.install(
            self.s1,
            gaps=[
                self.gap_upstream,
                self.gap_output,
                self.gap_environment,
            ],
            missing=[],
        )
        self.install(
            self.s2,
            gaps=[self.gap_upstream],
            missing=[rid("ff")],
        )

    def record(self, kind, data, token, *, gaps=None):
        return {
            "_id": rid(token),
            "schema_version": 1,
            "kind": kind,
            "data": data,
            "gaps": gaps or [],
        }

    def coverage(self, family, outcome, count, token):
        return self.record("observation-coverage", {
            "producer": {"name": "image-build", "contract": "fixture"},
            "subject": {
                "kind": "generation-candidate",
                "generation_id": self.generation_id,
                "root_inventory_digest": rid("5"),
            },
            "family": family,
            "collector": {"implementation_digest": rid("6")},
            "scope": {"selection": "fixture"},
            "outcome": outcome,
            "observation_count": count,
            "details": {},
        }, token)

    def snapshot(self, token, *, coverage):
        return self.record("generation-observation-snapshot", {
            "generation": self.generation_record["_id"],
            "generation_id": self.generation_id,
            "root_inventory_digest": rid("5"),
            "observations": {
                "verification_checks": [self.check["_id"]],
                "verification_executions": [self.execution["_id"]],
                "relationships": [self.relationship["_id"]],
                "source_provenance": [],
                "coverage": coverage,
            },
            "record_set_digest": rid(token),
        }, token)

    def install(self, snapshot, *, gaps, missing):
        records = {
            item["_id"]: item
            for item in (
                snapshot, self.generation_record, self.check, self.execution,
                self.relationship, self.coverage_elf_complete,
                self.coverage_verification_unavailable, self.coverage_elf_partial,
                self.gap_upstream, self.gap_output, self.gap_environment,
            )
        }
        gap_rows = [
            {"record": item["_id"], "reasons": list(item["gaps"])}
            for item in gaps
        ]
        # Deliberately model build-record <=0.7 aggregate semantics: declared gaps
        # make aggregate complete false even with zero missing canonical references.
        report = {
            "complete": not missing and not gap_rows,
            "missing_records": list(missing),
            "gaps": gap_rows,
        }
        FakeReader.graphs[snapshot["_id"]] = (
            {"schema_version": 1, "roots": [snapshot["_id"]], "records": records},
            report,
        )

    def query(self, method, *args, **kwargs):
        with patch("zog.build_trace.snapshot_observations.Reader", FakeReader):
            return getattr(self.trace, method)(*args, **kwargs)

    def test_canonical_only_snapshot_inspection_needs_no_owner_state(self):
        result = self.query("observation_snapshot", self.s1["_id"])
        self.assertEqual(result["availability"], "available")
        self.assertTrue(result["reference_closure_complete"])
        self.assertFalse((self.root / "state/image-build").exists())

    def test_canonical_only_snapshot_comparison_needs_no_owner_state(self):
        result = self.query(
            "compare_observation_snapshots", self.s1["_id"], self.s2["_id"])
        self.assertEqual(result["before"], self.s1["_id"])
        self.assertEqual(result["after"], self.s2["_id"])
        self.assertFalse((self.root / "state/image-build").exists())

    def test_canonical_only_verification_history_needs_no_owner_state(self):
        result = self.query(
            "verification_history",
            [self.s1["_id"], self.s2["_id"]],
            self.check["data"]["check_id"],
        )
        self.assertEqual([point["execution_count"] for point in result["points"]], [1, 1])
        self.assertFalse((self.root / "state/image-build").exists())

    def test_canonical_only_relationship_traversal_needs_no_owner_state(self):
        result = self.query(
            "relationship_traversal",
            [self.s1["_id"], self.s2["_id"]],
            "reverse", "soname", "libdemo.so.1",
        )
        self.assertEqual([point["relationship_count"] for point in result["points"]], [1, 1])
        self.assertFalse((self.root / "state/image-build").exists())

    def test_complete_reference_closure_is_independent_of_declared_gaps(self):
        result = self.query("observation_snapshot", self.s1["_id"])
        self.assertTrue(result["reference_closure_complete"])
        self.assertEqual(result["missing_record_count"], 0)
        self.assertFalse(result["declared_gap_free"])
        self.assertEqual(result["declared_gap_count"], 3)
        summary = {row["category"]: row for row in result["declared_gap_summary"]}
        self.assertEqual(summary["upstream-identity"]["record_count"], 1)
        self.assertEqual(summary["inventory-only-output"]["record_count"], 1)
        self.assertEqual(summary["external-environment-runtime"]["record_count"], 1)
        self.assertEqual(summary["external-environment-runtime"]["reason_count"], 2)

        details = self.query(
            "observation_snapshot", self.s1["_id"],
            collection="declared-gaps",
            gap_category="external-environment-runtime",
        )
        self.assertEqual(len(details["items"]["items"]), 1)
        self.assertEqual(details["items"]["items"][0]["canonical_kind"], "build-inputs")
        self.assertEqual(details["items"]["items"][0]["reason_count"], 2)

    def test_missing_canonical_reference_is_reference_closure_failure(self):
        result = self.query("observation_snapshot", self.s2["_id"])
        self.assertFalse(result["reference_closure_complete"])
        self.assertEqual(result["missing_record_count"], 1)
        self.assertFalse(result["declared_gap_free"])
        self.assertEqual(result["declared_gap_count"], 1)

    def test_complete_zero_observation_coverage_remains_complete(self):
        result = self.query("observation_snapshot", self.s1["_id"])
        coverage = {row["family"]: row for row in result["coverage"]}
        self.assertEqual(coverage["elf-interfaces"]["outcome"], "complete")
        self.assertEqual(coverage["elf-interfaces"]["observation_count"], 0)
        self.assertTrue(result["reference_closure_complete"])
        self.assertFalse(result["declared_gap_free"])

    def test_partial_and_unavailable_coverage_remain_distinct(self):
        result = self.query("observation_snapshot", self.s2["_id"])
        coverage = {row["family"]: row for row in result["coverage"]}
        self.assertEqual(coverage["elf-interfaces"]["outcome"], "partial")
        self.assertEqual(coverage["verification-commands"]["outcome"], "unavailable")

    def test_comparison_preserves_reference_gaps_and_coverage_independently(self):
        result = self.query(
            "compare_observation_snapshots", self.s1["_id"], self.s2["_id"])
        self.assertTrue(result["before_reference_closure_complete"])
        self.assertFalse(result["after_reference_closure_complete"])
        self.assertEqual(result["before_missing_record_count"], 0)
        self.assertEqual(result["after_missing_record_count"], 1)

        self.assertEqual(result["before_declared_gap_count"], 3)
        self.assertEqual(result["after_declared_gap_count"], 1)
        self.assertFalse(result["before_declared_gap_free"])
        self.assertFalse(result["after_declared_gap_free"])

        before_coverage = {row["family"]: row for row in result["before_coverage"]}
        after_coverage = {row["family"]: row for row in result["after_coverage"]}
        self.assertEqual(before_coverage["elf-interfaces"]["outcome"], "complete")
        self.assertEqual(after_coverage["elf-interfaces"]["outcome"], "partial")
        self.assertEqual(
            before_coverage["verification-commands"]["outcome"], "unavailable")
        self.assertEqual(
            after_coverage["verification-commands"]["outcome"], "unavailable")


class LazyOwnerStateTests(unittest.TestCase):
    def test_owner_local_operation_still_fails_source_unavailable(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "offline-project"
        trace = BuildTrace(
            root, host_id="host",
            record_store=Path(temporary.name) / "records",
            record_project_id="project",
        )
        with self.assertRaises(TraceError) as caught:
            trace.list_builds()
        self.assertEqual(caught.exception.code, "source-unavailable")


if __name__ == "__main__":
    unittest.main()
