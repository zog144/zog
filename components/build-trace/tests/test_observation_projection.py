"""Repository-only tests for observation presentation logic."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zog.build_trace import BuildTrace
from zog.build_trace.observations import _relationship_item, _relationship_package, _source_item


class FakeBuildRecord:
    @staticmethod
    def record_id(record):
        raw = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def relationship_observation(value):
        return {
            "schema_version": 1,
            "kind": "relationship-observation",
            "data": {
                "producer": {"name": "image-build", "contract": "image-build-integration-observations-v1"},
                "producer_observation": value["id"],
                "subject": value["subject"],
                "relation": value["relation"],
                "target": value["target"],
                "evidence": value["evidence"],
            },
            "gaps": [],
        }

    @classmethod
    def source_provenance_records(cls, value):
        repository = {
            "schema_version": 1, "kind": "source-repository",
            "data": {"location": value["repository"], "normalization": "exact-literal-v1"},
            "gaps": [],
        }
        repository_id = cls.record_id(repository)
        reference = {
            "schema_version": 1, "kind": "source-reference",
            "data": {"repository": repository_id, "kind": value["reference_kind"],
                     "value": value["reference"]},
            "gaps": [],
        }
        reference_id = cls.record_id(reference)
        archive = {
            "schema_version": 1, "kind": "source-archive",
            "data": {"digest": value["archive_digest"], "size": 1},
            "gaps": [],
        }
        archive_id = cls.record_id(archive)
        association = {
            "schema_version": 1, "kind": "source-archive-association",
            "data": {
                "archive": archive_id, "reference": reference_id,
                "relationship": "declared-not-independently-reproduced",
                "producer": {"name": "image-build", "contract": "image-build-integration-observations-v1"},
            },
            "gaps": [],
        }
        association_id = cls.record_id(association)
        provenance = {
            "schema_version": 1, "kind": "source-provenance",
            "data": {
                "producer": {"name": "image-build", "contract": "image-build-integration-observations-v1"},
                "producer_observation": value["id"],
                "package": value["package"], "project": value["project"],
                "output": value["output"], "build_inputs": value["build_inputs"],
                "source_selection": value["source_selection"],
                "archive": archive_id, "associations": [association_id],
            },
            "gaps": [],
        }
        return [repository, reference, archive, association, provenance]


class ObservationProjectionTests(unittest.TestCase):
    def relationship(self, relation="needs-library", package="demo"):
        return {
            "id": "sha256:" + "1" * 64,
            "subject": {
                "kind": "artifact", "path": "/usr/bin/demo",
                "digest": "sha256:" + "2" * 64, "packages": [package],
            },
            "relation": relation,
            "target": {"kind": "soname", "value": "libdemo.so.1"},
            "evidence": {"kind": "elf-metadata",
                         "tool": {"name": "readelf", "sha256": "3" * 64}},
        }

    def source(self, package="demo"):
        return {
            "id": "sha256:" + "4" * 64,
            "package": package, "project": "demo-project",
            "output": "sha256:" + "5" * 64,
            "build_inputs": "sha256:" + "6" * 64,
            "source_selection": "sha256:" + "7" * 64,
            "repository": "https://example.invalid/demo.git",
            "reference_kind": "tag", "reference": "v1.0",
            "archive_digest": "sha256:" + "8" * 64,
        }

    def trace(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "state/image-build").mkdir(parents=True)
        return BuildTrace(root, host_id="host",
                          record_store=root / "records",
                          record_project_id="project")

    def test_relationship_projection_has_canonical_identity(self):
        item = _relationship_item(FakeBuildRecord, self.relationship())
        self.assertEqual(item["canonical_kind"], "relationship-observation")
        self.assertEqual(item["authority"], "build-record")
        self.assertEqual(item["persistence"], "not-checked")
        self.assertEqual(item["id"], item["record"])
        self.assertTrue(_relationship_package(item, "demo"))
        self.assertFalse(_relationship_package(item, "other"))

    def test_source_projection_preserves_typed_chain(self):
        item = _source_item(FakeBuildRecord, self.source())
        self.assertEqual(item["canonical_kind"], "source-provenance")
        self.assertEqual(item["package"], "demo")
        self.assertEqual(
            [record["kind"] for record in item["canonical_records"]],
            ["source-repository", "source-reference", "source-archive",
             "source-archive-association", "source-provenance"],
        )
        reference = item["canonical_records"][1]
        self.assertEqual((reference["data"]["kind"], reference["data"]["value"]),
                         ("tag", "v1.0"))

    def test_generation_filters_apply_before_paging_and_bind_cursor(self):
        trace = self.trace()
        envelope = {
            "id": "sha256:" + "9" * 64,
            "producer": {"name": "image-build"},
            "context": {"generation_record": "sha256:" + "a" * 64},
            "verification": {"checks": [], "results": [], "coverage": "none"},
            "relationships": [
                self.relationship("needs-library", "demo"),
                self.relationship("provides-soname", "provider"),
            ],
            "sources": [self.source("demo"), self.source("provider")],
            "coverage": {"interfaces": "examined"},
            "gaps": [],
            "derivation": "fixture",
        }
        trace._generation_observation = lambda generation: (envelope, {"source_bytes": 0})
        with patch("zog.build_trace.observations._observation_library", return_value=FakeBuildRecord):
            first = trace.generation_observations(
                "a" * 64, collection="relationships", package="demo", limit=1)
            self.assertEqual(len(first["items"]["items"]), 1)
            self.assertEqual(first["items"]["items"][0]["relation"], "needs-library")
            sources = trace.generation_observations(
                "a" * 64, collection="sources", package="provider")
            self.assertEqual([row["package"] for row in sources["items"]["items"]], ["provider"])


if __name__ == "__main__":
    unittest.main()
