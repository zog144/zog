import copy
import hashlib
import unittest

from zog.build_record import (RecordError, canonical, ingest_image_build_relationships,
                          inspect, record_id, relationship_observation,
                          validate_image_build_generation)
from zog.build_record.model import artifact_references, references
from examples.local_pipeline import fixture


def producer_id(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def with_id(value):
    value = copy.deepcopy(value)
    value["id"] = producer_id(value)
    return value


def package_subject(ids, *, package="demo-package", output=None):
    return {
        "kind": "package",
        "package": package,
        "output_record": output or ids["output"],
    }


def declared(ids, relation="declares-runtime-dependency", target="openssl"):
    return with_id({
        "subject": package_subject(ids),
        "relation": relation,
        "target": {"kind": "package", "value": target},
        "evidence": {
            "kind": "frozen-recipe",
            "artifact": {
                "name": "package/dependencies.py",
                "digest": "sha256:" + "a" * 64,
                "size": 1,
            },
        },
    })


def artifact_relation(relation="needs-library", *, packages=None):
    target = ({"kind": "soname", "value": "libdemo.so.1"}
              if relation in ("needs-library", "provides-soname")
              else {"kind": "path", "value": "/lib64/ld-linux-x86-64.so.2"})
    evidence = ({"kind": "shebang", "argument": None}
                if relation == "script-interpreter"
                else {"kind": "elf-metadata",
                      "tool": {"name": "readelf", "sha256": "b" * 64}})
    if relation == "script-interpreter":
        target = {"kind": "path", "value": "/usr/bin/env"}
    return with_id({
        "subject": {
            "kind": "artifact",
            "path": "/usr/bin/demo",
            "digest": "sha256:" + "c" * 64,
            "packages": ["demo-package"] if packages is None else packages,
        },
        "relation": relation,
        "target": target,
        "evidence": evidence,
    })


def used(ids, *, target=None, target_package="demo-package"):
    return with_id({
        "subject": package_subject(ids, package="rootfs", output=ids["assembly_output"]),
        "relation": "used-build-output",
        "target": {
            "kind": "package-output",
            "value": target or ids["output"],
            "package": target_package,
        },
        "evidence": {
            "kind": "canonical-build-inputs",
            "record": ids["assembly_inputs"],
        },
    })


def envelope(bundle, relationships):
    generation = bundle["records"][bundle["roots"][0]]["data"]
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
            "root_inventory_digest": "sha256:" + "e" * 64,
        },
        "verification": {
            "checks": [],
            "results": [],
            "coverage": "named installed command checks only; no parsed upstream subtests",
        },
        "relationships": relationships,
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


class RelationshipObservationTests(unittest.TestCase):
    def setUp(self):
        self.bundle, _, self.ids = fixture()

    def test_artifact_interfaces_remain_literal_requirements_and_provisions(self):
        for relation in ("needs-library", "provides-soname",
                         "elf-interpreter", "script-interpreter"):
            producer = artifact_relation(relation)
            record = relationship_observation(producer)
            self.assertEqual(record["data"]["relation"], relation)
            self.assertEqual(record["data"]["producer_observation"], producer["id"])
            self.assertEqual(references(record), [])
        library = relationship_observation(artifact_relation("needs-library"))
        self.assertEqual(library["data"]["target"],
                         {"kind": "soname", "value": "libdemo.so.1"})
        self.assertNotIn("package", library["data"]["target"])

    def test_declared_dependency_is_not_resolved_to_an_output(self):
        producer = declared(self.ids)
        record = relationship_observation(producer)
        self.assertEqual(record["data"]["target"],
                         {"kind": "package", "value": "openssl"})
        self.assertEqual(references(record),
                         [(self.ids["output"], "package-output")])
        self.assertEqual(artifact_references(record),
                         [producer["evidence"]["artifact"]])

    def test_used_build_output_is_bound_to_exact_canonical_inputs(self):
        record = relationship_observation(used(self.ids))
        identity = record_id(record)
        combined = {
            "schema_version": 1,
            "roots": [identity],
            "records": {**self.bundle["records"], identity: record},
        }
        report = inspect(combined)
        self.assertTrue(report["complete"])
        self.assertEqual(report["relationships"][0]["relation"], "used-build-output")
        self.assertEqual(report["relationships"][0]["target"]["value"], self.ids["output"])

    def test_used_output_not_present_in_inputs_is_rejected(self):
        producer = used(self.ids, target=self.ids["assembly_output"], target_package="rootfs")
        record = relationship_observation(producer)
        identity = record_id(record)
        combined = {
            "schema_version": 1,
            "roots": [identity],
            "records": {**self.bundle["records"], identity: record},
        }
        with self.assertRaises(RecordError):
            inspect(combined)

    def test_generation_ingestion_canonicalizes_installed_package_declaration(self):
        producer = declared(self.ids, "declares-build-dependency", "m4")
        records = ingest_image_build_relationships(
            envelope(self.bundle, [producer]), self.bundle)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "relationship-observation")
        self.assertEqual(records[0]["data"]["producer_observation"], producer["id"])

    def test_generation_rejects_package_subject_not_installed_as_that_output(self):
        producer = declared(self.ids)
        producer["subject"] = package_subject(
            self.ids, package="rootfs", output=self.ids["assembly_output"])
        producer["id"] = producer_id({k: v for k, v in producer.items() if k != "id"})
        with self.assertRaises(RecordError):
            validate_image_build_generation(envelope(self.bundle, [producer]), self.bundle)

    def test_generation_rejects_unknown_artifact_owner(self):
        producer = artifact_relation("needs-library", packages=["not-installed"])
        with self.assertRaises(RecordError):
            validate_image_build_generation(envelope(self.bundle, [producer]), self.bundle)

    def test_duplicate_producer_relationship_is_rejected(self):
        producer = declared(self.ids)
        with self.assertRaises(RecordError):
            validate_image_build_generation(
                envelope(self.bundle, [producer, copy.deepcopy(producer)]), self.bundle)

    def test_relation_specific_target_shape_is_strict(self):
        producer = artifact_relation("needs-library")
        producer["target"] = {"kind": "package", "value": "libdemo"}
        producer["id"] = producer_id({k: v for k, v in producer.items() if k != "id"})
        with self.assertRaises(RecordError):
            relationship_observation(producer)

    def test_tampered_producer_relationship_identity_is_rejected(self):
        producer = declared(self.ids)
        producer["target"]["value"] = "changed"
        with self.assertRaises(RecordError):
            relationship_observation(producer)


if __name__ == "__main__":
    unittest.main()
