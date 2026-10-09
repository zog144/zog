import copy
import hashlib
import unittest

from zog.build_record import (RecordError, canonical, ingest_image_build_sources, inspect,
                          record_id, source_provenance_records,
                          validate_image_build_generation)
from examples.local_pipeline import fixture


def producer_id(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def source_row(bundle, ids, *, upstream=None, downloads=None, project="demo-project", gaps=None):
    selected = bundle["records"][ids["source"]]["data"]
    archive = copy.deepcopy(selected["archives"][0])
    upstream = upstream or [{
        "repository": "https://example.invalid/demo.git",
        "revision": "a" * 40,
        "revision_type": "git",
    }]
    value = {
        "package": "demo-package",
        "project": project,
        "output_record": ids["output"],
        "build_inputs_record": ids["inputs"],
        "source_selection_record": ids["source"],
        "pin": copy.deepcopy(selected["pin"]),
        "archive": archive,
        "downloads": downloads or [{
            "url": "https://example.invalid/demo.tar.xz",
            "sha256": archive["digest"][7:],
            "destination": archive["name"],
            "archive": True,
        }],
        "upstream": upstream,
        "archive_revision_relationship": "declared-not-independently-reproduced",
        "release_tags": [
            {"repository": item["repository"], "tag": item["revision"]}
            for item in upstream if item["revision_type"] == "tag"
        ],
        "gaps": gaps or [],
    }
    value["id"] = producer_id(value)
    return value


def envelope(bundle, source):
    generation = bundle["records"][bundle["roots"][0]]["data"]
    value = {
        "schema": "image-build-integration-observations-v1",
        "producer": {
            "name": "image-build",
            "contract": "image-build-integration-observations-v1",
            "implementation_digest": "sha256:" + "f" * 64,
        },
        "context": {
            "generation_id": generation["generation_id"],
            "generation_record": bundle["roots"][0],
            "root_inventory_digest": "sha256:" + "e" * 64,
        },
        "verification": {
            "checks": [],
            "results": [],
            "coverage": "named installed command checks only; no parsed upstream subtests",
        },
        "relationships": [],
        "sources": [source],
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


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _, self.ids = fixture()

    def test_git_source_builds_typed_canonical_chain(self):
        source = source_row(self.bundle, self.ids)
        records = source_provenance_records(source)
        self.assertEqual([record["kind"] for record in records], [
            "source-repository", "source-reference", "source-archive",
            "source-archive-association", "source-provenance",
        ])
        self.assertEqual(records[1]["data"]["kind"], "git")
        self.assertEqual(records[1]["data"]["value"], "a" * 40)
        self.assertEqual(records[-1]["data"]["producer_observation"], source["id"])

    def test_tag_is_preserved_without_git_coercion(self):
        source = source_row(self.bundle, self.ids, upstream=[{
            "repository": "https://example.invalid/demo.git",
            "revision": "v1.2.3", "revision_type": "tag"}])
        reference = next(record for record in source_provenance_records(source)
                         if record["kind"] == "source-reference")
        self.assertEqual((reference["data"]["kind"], reference["data"]["value"]),
                         ("tag", "v1.2.3"))

    def test_unknown_reference_remains_explicit_gap(self):
        source = source_row(self.bundle, self.ids, upstream=[{
            "repository": "https://example.invalid/demo.git",
            "revision": None, "revision_type": "unknown"}],
            gaps=["Upstream revision is explicitly unknown; archive bytes are pinned."])
        records = source_provenance_records(source)
        reference = next(record for record in records if record["kind"] == "source-reference")
        self.assertIsNone(reference["data"]["value"])
        self.assertTrue(reference["gaps"])
        self.assertTrue(records[-1]["gaps"])

    def test_repository_aliases_are_not_silently_merged(self):
        left = source_row(self.bundle, self.ids, upstream=[{
            "repository": "https://example.invalid/demo.git",
            "revision": "a" * 40, "revision_type": "git"}])
        right = source_row(self.bundle, self.ids, upstream=[{
            "repository": "ssh://git@example.invalid/demo.git",
            "revision": "a" * 40, "revision_type": "git"}])
        left_repo = source_provenance_records(left)[0]
        right_repo = source_provenance_records(right)[0]
        self.assertNotEqual(record_id(left_repo), record_id(right_repo))
        self.assertEqual(left_repo["data"]["normalization"], "exact-literal-v1")

    def test_parallel_declared_claims_for_one_archive_are_not_conflicts(self):
        source = source_row(self.bundle, self.ids, upstream=[
            {"repository": "https://example.invalid/a.git", "revision": "a" * 40, "revision_type": "git"},
            {"repository": "https://example.invalid/b.git", "revision": "release-1", "revision_type": "tag"},
        ])
        associations = [record for record in source_provenance_records(source)
                        if record["kind"] == "source-archive-association"]
        self.assertEqual(len(associations), 2)
        self.assertEqual(len({record_id(record) for record in associations}), 2)
        self.assertEqual({record["data"]["relationship"] for record in associations},
                         {"declared-not-independently-reproduced"})

    def test_download_url_does_not_change_core_source_identities(self):
        first = source_row(self.bundle, self.ids)
        second = source_row(self.bundle, self.ids, downloads=[{
            "url": "https://mirror.invalid/renamed-location.tar.xz",
            "sha256": first["archive"]["digest"][7:],
            "destination": first["archive"]["name"], "archive": True}])
        a = source_provenance_records(first)
        b = source_provenance_records(second)
        stable = {"source-repository", "source-reference", "source-archive",
                  "source-archive-association"}
        self.assertEqual(
            {record["kind"]: record_id(record) for record in a if record["kind"] in stable},
            {record["kind"]: record_id(record) for record in b if record["kind"] in stable})
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(record_id(a[-1]), record_id(b[-1]))

    def test_generation_ingestion_is_inspectable(self):
        source = source_row(self.bundle, self.ids)
        records = ingest_image_build_sources(envelope(self.bundle, source), self.bundle)
        combined = {"schema_version": 1, "roots": [record_id(records[-1])],
                    "records": {**self.bundle["records"],
                                **{record_id(record): record for record in records}}}
        report = inspect(combined)
        row = report["source_provenance"][0]
        self.assertEqual(row["package"], "demo-package")
        self.assertEqual(row["associations"][0]["reference_kind"], "git")
        self.assertEqual(row["associations"][0]["repository"],
                         "https://example.invalid/demo.git")

    def test_pin_and_archive_must_match_canonical_selection(self):
        source = source_row(self.bundle, self.ids)
        changed = copy.deepcopy(source)
        changed["pin"]["digest"] = "sha256:" + "9" * 64
        changed["id"] = producer_id({k: v for k, v in changed.items() if k != "id"})
        with self.assertRaises(RecordError):
            validate_image_build_generation(envelope(self.bundle, changed), self.bundle)
        changed = copy.deepcopy(source)
        changed["archive"]["size"] += 1
        changed["id"] = producer_id({k: v for k, v in changed.items() if k != "id"})
        with self.assertRaises(RecordError):
            validate_image_build_generation(envelope(self.bundle, changed), self.bundle)

    def test_release_tag_projection_must_match_typed_upstream(self):
        source = source_row(self.bundle, self.ids, upstream=[{
            "repository": "https://example.invalid/demo.git",
            "revision": "v2", "revision_type": "tag"}])
        source["release_tags"] = []
        source["id"] = producer_id({k: v for k, v in source.items() if k != "id"})
        with self.assertRaises(RecordError):
            source_provenance_records(source)


if __name__ == "__main__":
    unittest.main()
