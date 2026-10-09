"""Read-only integrate-observe observation projections."""
import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from zog.build_trace import BuildTrace, TraceError
from zog.build_trace.cli import main

try:
    import zog.build_record as build_record
    AVAILABLE = all(hasattr(build_record, name) for name in (
        "verification_execution", "relationship_observation", "source_provenance_records"
    ))
except ImportError:
    build_record = None
    AVAILABLE = False


class Provider:
    def __init__(self, generation, candidate):
        self.generation_value = generation
        self.candidate_value = candidate

    def generation(self, generation):
        return copy.deepcopy(self.generation_value)

    def candidate(self, candidate):
        return copy.deepcopy(self.candidate_value)


@unittest.skipUnless(AVAILABLE, "requires build-record 0.5 observation adapter")
class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state/image-build"
        self.state.mkdir(parents=True)
        self.store = build_record.Store(self.state / "build-record/records")
        self.host = "host-a"
        self.project = "project-a"
        self.generation = "a" * 64
        self.pointer, self.package = self.make_generation()
        self.observation = self.make_observation()
        self.envelope = self.make_envelope(self.observation)
        self.candidate = {
            "schema": "image-build-candidate-verifications-v1",
            "generation_id": self.observation["subject"]["generation_id"],
            "results": [self.observation],
            "coverage": "captured terminal commands only; absence is not SKIP",
        }
        self.provider = Provider(self.envelope, self.candidate)
        self.trace = self.reader()

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, name, digit):
        return {"name": name, "digest": "sha256:" + digit * 64, "size": 1}

    def put(self, kind, data, gaps=None):
        return self.store.put(build_record.make_record(kind, data, gaps=gaps))

    def make_generation(self):
        source = self.put("source-selection", {
            "package": "fixture",
            "pin": {
                "month": "2026-10-01",
                "repository": "zog",
                "revision": "1" * 40,
                "path": "commit-pin.py",
                "digest": "sha256:" + "2" * 64,
            },
            "upstream": [{"repository": "https://example.invalid/fixture.git", "revision": "3" * 40}],
            "archives": [self.asset("fixture.tar", "4")],
        })
        inputs = self.put("build-inputs", {
            "package": "fixture",
            "step": "build",
            "purpose": "package",
            "sources": [source],
            "recipe": self.asset("recipe.json", "5"),
            "patches": [],
            "target": "fixture",
            "options": {},
            "environment": {},
            "materials": [self.asset("builder", "6")],
            "dependencies": [],
        })
        prepared = self.put("attempt-start", {
            "attempt_id": json.dumps([self.host, self.project, "package-attempt", "fixture"], separators=(",", ":")),
            "inputs": inputs,
            "prepared_at": "2026-10-06T12:00:00Z",
            "retry_of": None,
        })
        output = self.put("package-output", {
            "package": "fixture",
            "attempt": prepared,
            "artifacts": [self.asset("fixture-output.json", "7")],
        })
        result = self.put("attempt-result", {
            "attempt": prepared,
            "outcome": "succeeded",
            "finished_at": "2026-10-06T12:01:00Z",
            "jobs": [],
            "traces": [{"host_id": self.host, "build_id": "attempt:package-attempt"}],
            "outputs": [output],
            "summary": "fixture",
        })
        assembly_inputs = self.put("build-inputs", {
            "package": "@rootfs-assembly",
            "step": "assemble",
            "purpose": "assembly",
            "sources": [],
            "recipe": self.asset("assembly.json", "8"),
            "patches": [],
            "target": "fixture",
            "options": {"owner_generation": self.generation},
            "environment": {},
            "materials": [self.asset("assembler", "9")],
            "dependencies": [{"output": output, "result": result}],
        })
        assembly_prepared = self.put("attempt-start", {
            "attempt_id": json.dumps([self.host, self.project, "assembly", "@rootfs-assembly"], separators=(",", ":")),
            "inputs": assembly_inputs,
            "prepared_at": "2026-10-06T12:02:00Z",
            "retry_of": None,
        })
        assembly_output = self.put("package-output", {
            "package": "@rootfs-assembly",
            "attempt": assembly_prepared,
            "artifacts": [self.asset("rootfs.tar", "a"), self.asset("rootfs-content.json", "b")],
        })
        assembly_result = self.put("attempt-result", {
            "attempt": assembly_prepared,
            "outcome": "succeeded",
            "finished_at": "2026-10-06T12:03:00Z",
            "jobs": [],
            "traces": [{"host_id": self.host, "build_id": "attempt:assembly"}],
            "outputs": [assembly_output],
            "summary": "assembly",
        })
        record = self.put("generation", {
            "generation_id": json.dumps([self.host, self.project, self.generation], separators=(",", ":")),
            "assembly_result": assembly_result,
            "packages": [{"output": output, "result": result}],
            "artifact": self.asset("rootfs.tar", "a"),
            "content_manifest": self.asset("rootfs-content.json", "b"),
            "verification": [],
        })
        pointer = {
            "schema": 1,
            "host_id": self.host,
            "project_id": self.project,
            "generation": self.generation,
            "build_id": "attempt:assembly",
            "prepared": assembly_prepared,
            "inputs": assembly_inputs,
            "record": record,
            "result": assembly_result,
            "output": assembly_output,
        }
        path = self.state / "generations" / self.generation / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": 2, "generation": self.generation, "build_record": pointer}))
        return pointer, {"source": source, "inputs": inputs, "output": output, "result": result}

    def producer_id(self, value):
        return "sha256:" + hashlib.sha256(build_record.canonical(value)).hexdigest()

    def make_observation(self, *, outcome="PASS", invocation="invocation-1", definition=None):
        value = {
            "schema": "image-build-verification-observation-v1",
            "check_id": "image-build/installed-trust/command/0",
            "definition_digest": definition or ("sha256:" + "c" * 64),
            "subject": {
                "kind": "generation-candidate",
                "generation_id": json.dumps([self.host, self.project, self.generation], separators=(",", ":")),
                "root_inventory_digest": "sha256:" + "d" * 64,
            },
            "attempt_id": json.dumps([self.host, self.project, "verify-attempt"], separators=(",", ":")),
            "sequence": 0,
            "outcome": outcome,
            "execution": {"invocation_id": invocation, "exit_code": 0 if outcome == "PASS" else 2},
            "environment_digest": "sha256:" + "e" * 64,
            "evidence": [{"kind": "build-trace", "host_id": self.host, "build_id": "attempt:verify-attempt"}],
            "granularity": "command",
            "timing": {"started_at": None, "finished_at": None, "observed_at": None},
            "producer": {"name": "image-build", "contract": "image-build-verification-observation-v1"},
        }
        value["id"] = self.producer_id(value)
        return value

    def make_envelope(self, observation):
        relationship = {
            "subject": {"kind": "package", "package": "fixture", "output_record": self.package["output"]},
            "relation": "declares-runtime-dependency",
            "target": {"kind": "package", "value": "openssl"},
            "evidence": {"kind": "frozen-recipe",
                         "artifact": self.asset("package/dependencies.py", "5")},
        }
        relationship["id"] = self.producer_id(relationship)
        selected = self.store.get(self.package["source"])["data"]
        source = {
            "package": "fixture",
            "project": "fixture",
            "output_record": self.package["output"],
            "build_inputs_record": self.package["inputs"],
            "source_selection_record": self.package["source"],
            "pin": copy.deepcopy(selected["pin"]),
            "archive": copy.deepcopy(selected["archives"][0]),
            "downloads": [],
            "upstream": [{"repository": "https://example.invalid/fixture.git",
                          "revision": "3" * 40, "revision_type": "git"}],
            "archive_revision_relationship": "declared-not-independently-reproduced",
            "release_tags": [],
            "gaps": [],
        }
        source["id"] = self.producer_id(source)
        value = {
            "schema": "image-build-integration-observations-v1",
            "producer": {
                "name": "image-build",
                "contract": "image-build-integration-observations-v1",
                "implementation_digest": "sha256:" + "f" * 64,
            },
            "context": {
                "generation_id": observation["subject"]["generation_id"],
                "generation_record": self.pointer["record"],
                "root_inventory_digest": observation["subject"]["root_inventory_digest"],
            },
            "verification": {
                "checks": [{
                    "check_id": observation["check_id"],
                    "definition_digest": observation["definition_digest"],
                    "granularity": "command",
                }],
                "results": [observation],
                "coverage": "named installed command checks only; no parsed upstream subtests",
            },
            "relationships": [relationship],
            "sources": [source],
            "coverage": {
                "elf_files": 0,
                "script_files": 0,
                "readelf": {"name": "readelf", "sha256": "1" * 64},
                "symlinks": "not-followed",
                "resolution": "interfaces-only",
                "unsupported": ["dlopen-provider-resolution", "service-dependencies"],
            },
            "gaps": [{"reason": "dlopen-not-observed"}, {"reason": "service-dependencies-not-observed"}],
            "derivation": "post-build-inspection; does not retrofit canonical pre-execution evidence",
        }
        value["id"] = self.producer_id(value)
        return value

    def reader(self, allowed=None, provider=None):
        return BuildTrace(
            self.root,
            host_id=self.host,
            record_store=self.store.directory,
            record_project_id=self.project,
            allowed_build_ids=allowed,
            observation_provider=self.provider if provider is None and hasattr(self, "provider") else provider,
        )

    def test_generation_manifest_and_collections(self):
        result = self.trace.generation_observations(self.generation)
        self.assertEqual(result["availability"], "available")
        self.assertEqual(result["collections"]["verification"]["count"], 1)
        self.assertEqual(result["collections"]["relationships"]["authority"], "build-record")
        self.assertEqual(result["collections"]["sources"]["authority"], "build-record")
        self.assertEqual(result["collections"]["verification"]["canonicalization"], "verification-execution")
        self.assertEqual(result["collections"]["relationships"]["canonicalization"], "relationship-observation")
        self.assertEqual(result["collections"]["sources"]["canonicalization"], "source-provenance-chain")

        page = self.trace.generation_observations(self.generation, collection="verification")
        expected = build_record.record_id(build_record.verification_execution(self.observation))
        self.assertEqual(page["items"]["items"][0]["record"], expected)
        self.assertEqual(page["items"]["items"][0]["producer_observation"], self.observation["id"])
        self.assertEqual(page["items"]["items"][0]["persistence"], "not-checked")

        relations = self.trace.generation_observations(self.generation, collection="relationships")
        expected_relation = build_record.record_id(
            build_record.relationship_observation(self.envelope["relationships"][0]))
        self.assertEqual(relations["items"]["items"][0]["record"], expected_relation)
        self.assertEqual(relations["canonicalization"], "relationship-observation")
        self.assertEqual(relations["items"]["items"][0]["persistence"], "not-checked")

        sources = self.trace.generation_observations(self.generation, collection="sources")
        canonical = build_record.source_provenance_records(self.envelope["sources"][0])
        expected_source = build_record.record_id(
            next(record for record in canonical if record["kind"] == "source-provenance"))
        row = sources["items"]["items"][0]
        self.assertEqual(row["record"], expected_source)
        self.assertEqual(row["canonical_kind"], "source-provenance")
        self.assertEqual(
            {item["kind"] for item in row["canonical_records"]},
            {"source-repository", "source-reference", "source-archive",
             "source-archive-association", "source-provenance"})
        reference = next(item for item in row["canonical_records"]
                         if item["kind"] == "source-reference")
        self.assertEqual(reference["data"]["kind"], "git")

    def test_relationship_and_source_filters_are_cursor_scoped(self):
        relations = self.trace.generation_observations(
            self.generation, collection="relationships",
            relation="declares-runtime-dependency", package="fixture")
        self.assertEqual(len(relations["items"]["items"]), 1)
        self.assertEqual(relations["filters"]["package"], "fixture")
        missing = self.trace.generation_observations(
            self.generation, collection="sources", package="missing")
        self.assertEqual(missing["items"]["items"], [])
        with self.assertRaises(TraceError):
            self.trace.generation_observations(
                self.generation, collection="sources", relation="needs-library")
        with self.assertRaises(TraceError):
            self.trace.generation_observations(
                self.generation, collection="relationships", relation="not-a-relation")

    def test_gaps_are_paged_and_cursor_is_collection_bound(self):
        first = self.trace.generation_observations(self.generation, collection="gaps", limit=1)
        self.assertTrue(first["items"]["has_more"])
        second = self.trace.generation_observations(
            self.generation, collection="gaps", limit=1, cursor=first["items"]["next_cursor"])
        self.assertFalse(second["items"]["has_more"])
        with self.assertRaises(TraceError):
            self.trace.generation_observations(
                self.generation, collection="checks", cursor=first["items"]["next_cursor"])

    def test_candidate_repeated_results_preserve_logical_and_definition_identity(self):
        changed = self.make_observation(outcome="FAIL", invocation="invocation-2",
                                        definition="sha256:" + "1" * 64)
        candidate = copy.deepcopy(self.candidate)
        candidate["results"].append(changed)
        trace = self.reader(provider=Provider(self.envelope, candidate))
        result = trace.candidate_verifications(self.generation)
        rows = result["results"]["items"]
        self.assertEqual(result["result_count"], 2)
        self.assertEqual({row["check_id"] for row in rows}, {self.observation["check_id"]})
        self.assertEqual(len({row["definition_digest"] for row in rows}), 2)
        self.assertEqual({row["outcome"] for row in rows}, {"PASS", "FAIL"})
        self.assertEqual(result["interpretation"],
                         "Absence is not SKIP and no published generation is implied.")

    def test_verification_scope_respects_allowed_builds(self):
        trace = self.reader(allowed=["attempt:package-attempt", "attempt:assembly"])
        with self.assertRaises(TraceError) as caught:
            trace.generation_observations(self.generation, collection="verification")
        self.assertEqual(caught.exception.code, "not-found")

    def test_unsupported_schema_is_rejected(self):
        bad = copy.deepcopy(self.envelope)
        bad["schema"] = "image-build-integration-observations-v2"
        trace = self.reader(provider=Provider(bad, self.candidate))
        with self.assertRaises(TraceError) as caught:
            trace.generation_observations(self.generation)
        self.assertEqual(caught.exception.code, "invalid-record")

    def test_not_configured_is_explicit(self):
        trace = self.reader(provider=None)
        trace.observation_provider = None
        result = trace.generation_observations(self.generation)
        self.assertEqual(result["availability"], "not-configured")
        result = trace.candidate_verifications(self.generation)
        self.assertEqual(result["availability"], "not-configured")

    def test_cli_reads_one_explicit_producer_export(self):
        path = self.root / "observations.json"
        path.write_text(json.dumps(self.envelope))
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([
                "--project-root", str(self.root),
                "--host-id", self.host,
                "--record-store", str(self.store.directory),
                "--record-project-id", self.project,
                "--observation-file", str(path),
                "generation-observations", self.generation,
                "--collection", "relationships",
                "--relation", "declares-runtime-dependency",
                "--package", "fixture",
            ])
        self.assertEqual(code, 0)
        value = json.loads(out.getvalue())
        self.assertEqual(value["kind"], "generation-observation-collection")
        self.assertEqual(value["items"]["items"][0]["relation"], "declares-runtime-dependency")
        self.assertEqual(value["canonicalization"], "relationship-observation")


if __name__ == "__main__":
    unittest.main()
