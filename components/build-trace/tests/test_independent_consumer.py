"""Acceptance gate for a consumer that depends only on the public zog.build_trace API."""
import ast
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zog.build_trace import BuildTrace

import test_snapshot_observations as snapshot_fixture


ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / "acceptance" / "integrate_observe_consumer.py"


def load_consumer():
    spec = importlib.util.spec_from_file_location("independent_integrate_observe_consumer", CONSUMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IndependentConsumerAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.consumer = load_consumer()

    def setUp(self):
        fixture = snapshot_fixture.SnapshotTests(
            methodName="test_manifest_separates_reference_closure_declared_gaps_and_coverage")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        shutil.rmtree(fixture.root / "state/image-build")
        fixture.trace = BuildTrace(
            fixture.root,
            host_id="host",
            record_store=fixture.root / "records",
            record_project_id="project",
        )
        self.assertFalse((fixture.root / "state/image-build").exists())
        self.fixture = fixture

    def run_consumer(self, snapshots):
        with patch("zog.build_trace.snapshot_observations.Reader", snapshot_fixture.FakeReader):
            return self.consumer.inspect_sequence(
                self.fixture.trace,
                snapshots,
                check_id=self.fixture.check["data"]["check_id"],
                soname="libdemo.so.1",
                package="provider",
            )

    def test_consumer_imports_only_public_build_trace_surface(self):
        tree = ast.parse(CONSUMER.read_text(), filename=str(CONSUMER))
        forbidden = []
        public_import_seen = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("zog.build_record", "zog.image_build") or alias.name.startswith(
                            ("zog.build_record.", "zog.image_build.", "zog.build_trace.")):
                        forbidden.append(alias.name)
                    if alias.name == "zog.build_trace":
                        public_import_seen = True
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in ("zog.build_record", "zog.image_build") or module.startswith(
                        ("zog.build_record.", "zog.image_build.", "zog.build_trace.")):
                    forbidden.append(module)
                if module == "zog.build_trace":
                    public_import_seen = True
        self.assertTrue(public_import_seen)
        self.assertEqual(forbidden, [])

    def test_consumer_uses_only_documented_public_query_methods(self):
        source = CONSUMER.read_text()
        expected = {
            "observation_snapshot",
            "compare_observation_snapshots",
            "verification_history",
            "relationship_traversal",
        }
        called = set()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "trace":
                    called.add(node.func.attr)
        self.assertEqual(called, expected)

    def test_consumer_can_reconstruct_required_facts_without_interpretation(self):
        result = self.run_consumer([
            self.fixture.s1["_id"],
            self.fixture.s3["_id"],
        ])
        self.assertEqual(result["contract"], "build-trace-independent-consumer-v1")
        self.assertEqual(result["snapshot_count"], 2)
        self.assertEqual(
            result["caller_order"],
            [self.fixture.s1["_id"], self.fixture.s3["_id"]],
        )

        self.assertTrue(result["comparison"]["same_generation_record"])
        self.assertFalse(result["comparison"]["same_record_set"])
        self.assertTrue(result["first"]["reference_closure_complete"])
        self.assertTrue(result["last"]["reference_closure_complete"])
        self.assertTrue(result["first"]["declared_gap_free"])
        self.assertTrue(result["last"]["declared_gap_free"])
        self.assertEqual(
            result["comparison"]["collections"]["verification-executions"]["added_count"],
            2,
        )

        verification = result["verification"]
        self.assertEqual(verification["order"], "caller-supplied")
        self.assertEqual(verification["chronology"], "not-inferred")
        self.assertEqual(verification["points"][0]["execution_count"], 1)
        self.assertEqual(verification["points"][1]["execution_count"], 3)
        self.assertEqual(
            {item["definition_digest"] for item in verification["points"][1]["definitions"]},
            {self.fixture.check["data"]["definition_digest"],
             self.fixture.check2["data"]["definition_digest"]},
        )

        reverse = result["reverse_interfaces"]
        self.assertEqual(reverse["match_semantics"], "literal-canonical-fields-only")
        self.assertEqual(reverse["points"][0]["relationship_count"], 1)
        self.assertEqual(reverse["points"][1]["relationship_count"], 2)
        self.assertEqual(
            {row["relation"] for row in reverse["points"][1]["relationships"]},
            {"needs-library", "provides-soname"},
        )

        forward = result["package_relationships"]
        self.assertEqual(forward["points"][0]["relationship_count"], 0)
        self.assertEqual(forward["points"][1]["relationship_count"], 1)

        self.assertEqual(
            result["interpretation"],
            {
                "baseline_selected": False,
                "chronology_inferred": False,
                "representative_execution_selected": False,
                "provider_resolution_performed": False,
                "regression_classified": False,
                "blast_radius_computed": False,
            },
        )

    def test_consumer_preserves_coverage_when_no_relationship_matches(self):
        result = self.run_consumer([
            self.fixture.s1["_id"],
            self.fixture.s3["_id"],
        ])
        first_forward = result["package_relationships"]["points"][0]
        self.assertEqual(first_forward["relationship_count"], 0)
        coverage = {row["family"]: row for row in first_forward["coverage"]}
        self.assertIn("elf-interfaces", coverage)
        self.assertEqual(coverage["elf-interfaces"]["outcome"], "complete")

    def test_consumer_output_is_json_serializable_public_data(self):
        result = self.run_consumer([self.fixture.s1["_id"], self.fixture.s3["_id"]])
        encoded = json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["contract"], "build-trace-independent-consumer-v1")


if __name__ == "__main__":
    unittest.main()
