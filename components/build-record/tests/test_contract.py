import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zog.build_record import (RecordError, Store, canonical, compare, inspect, loads,
                          make_record, record_id, validate, verify_artifacts)
from zog.build_record.cli import main
from zog.build_record.model import MAX_RECORD_BYTES
from examples.local_pipeline import fixture

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle, self.blobs, self.ids = fixture()
    def record(self, name):
        return copy.deepcopy(self.bundle["records"][self.ids[name]])
    def bundle_with(self, record, roots=None):
        identity = record_id(record)
        return {"schema_version": 1, "roots": roots or [identity],
                "records": {**self.bundle["records"], identity: record}}

    def test_complete_graph_and_failed_retry_retained(self):
        report = inspect(self.bundle)
        self.assertTrue(report["complete"])
        self.assertEqual(report["subjects"][0]["packages"][0]["package"], "demo-package")
        self.assertEqual(len(report["evidence"]), 3)
        self.assertIn(self.ids["failed_result"], report["records"])
        self.assertEqual(report["artifact_verification"], "not-checked")
        self.assertEqual(report["authenticity"], "not-verified")
    def test_canonical_golden(self):
        self.assertEqual(canonical({"z": "é", "a": [True, None, 1]}),
                         b'{"a":[true,null,1],"z":"\\u00e9"}')
    def test_record_golden_and_order_independence(self):
        record = make_record("package-output", {"package": "x", "attempt": None,
            "artifacts": [{"name": "x", "digest": "sha256:" + "0" * 64, "size": 0}]}, gaps=["legacy"])
        raw = ('{"data":{"artifacts":[{"digest":"sha256:' + '0' * 64 +
               '","name":"x","size":0}],"attempt":null,"package":"x"},'
               '"gaps":["legacy"],"kind":"package-output","schema_version":1}').encode()
        self.assertEqual(canonical(record), raw)
        self.assertEqual(record_id(record), "sha256:" + hashlib.sha256(raw).hexdigest())
        self.assertEqual(record_id(record), record_id(dict(reversed(list(record.items())))))
    def test_reject_invalid_json(self):
        for raw in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":1.5}', '{"x":9007199254740992}',
                    '{"x":"\\ud800"}', '[' * 1000 + ']' * 1000):
            with self.subTest(raw=raw[:30]), self.assertRaises(RecordError): loads(raw)
    def test_limits(self):
        with self.assertRaises(RecordError): loads(b' ' * (MAX_RECORD_BYTES + 1))
        record = self.record("inputs")
        record["data"]["options"]["huge"] = "x" * MAX_RECORD_BYTES
        with self.assertRaises(RecordError): validate(record)
    def test_schema_and_unknown_fields(self):
        for value in (2, True, "1"):
            record = self.record("source"); record["schema_version"] = value
            with self.assertRaises(RecordError): validate(record)
        record = self.record("source"); record["data"]["extra"] = "ignored?"
        with self.assertRaises(RecordError): validate(record)
    def test_source_or_recipe_change_identity(self):
        other, _, ids = fixture(source_bytes=b"different", recipe_bytes=b"different recipe")
        self.assertNotEqual(self.ids["source"], ids["source"])
        self.assertNotEqual(self.ids["inputs"], ids["inputs"])
        report = compare(self.bundle, other)
        self.assertEqual(report["packages"][0]["changed_input_fields"], ["recipe", "sources"])
    def test_pin_month_correction_changes_identity(self):
        record = self.record("source"); record["data"]["pin"]["revision"] = "3" * 40
        self.assertNotEqual(record_id(record), self.ids["source"])
        record["data"]["pin"]["month"] = "2026-10-02"
        with self.assertRaises(RecordError): validate(record)
    def test_unknown_upstream_needs_gap(self):
        record = self.record("source"); record["data"]["upstream"][0]["revision"] = None
        with self.assertRaises(RecordError): validate(record)
        record["gaps"] = ["Initial monthly set did not capture upstream commit"]
        self.assertFalse(inspect(self.bundle_with(record))["complete"])
    def test_no_unrestricted_environment(self):
        record = self.record("inputs"); record["data"]["environment"]["PRIVATE_PASSWORD"] = "fixture"
        with self.assertRaises(RecordError): validate(record)
    def test_missing_edges_are_not_success(self):
        del self.bundle["records"][self.ids["source"]]
        report = inspect(self.bundle)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_records"], [self.ids["source"]])
        with self.assertRaises(RecordError): compare(self.bundle, self.bundle)
    def test_wrong_reference_type(self):
        record = self.record("start"); record["data"]["inputs"] = self.ids["source"]
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_record_tampering(self):
        self.bundle["records"][self.ids["source"]]["data"]["package"] = "different"
        with self.assertRaises(RecordError): inspect(self.bundle)
    def test_source_package_mismatch(self):
        record = self.record("inputs"); record["data"]["package"] = "other"
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_output_package_mismatch(self):
        record = self.record("output"); record["data"]["package"] = "other"
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_wrong_attempt_result_binding(self):
        record = self.record("result"); record["data"]["attempt"] = self.ids["failed_start"]
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_result_time_is_chronological_not_lexical(self):
        start = self.record("start")
        start["data"].update(prepared_at="2026-10-02T12:03:00.1Z", retry_of=None)
        start_id = record_id(start); self.bundle["records"][start_id] = start
        result = self.record("failed_result")
        result["data"].update(attempt=start_id, finished_at="2026-10-02T12:03:00Z")
        with self.assertRaises(RecordError): inspect(self.bundle_with(result))
    def test_retry_requires_new_identity(self):
        record = self.record("start"); record["data"]["attempt_id"] = "fixture:package:1"
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_conflicting_results(self):
        record = self.record("result"); record["data"]["summary"] = "different final result"
        with self.assertRaises(RecordError):
            inspect(self.bundle_with(record, [record_id(record), self.ids["result"]]))
    def test_failure_cannot_publish_outputs(self):
        record = self.record("result"); record["data"]["outcome"] = "failed"
        with self.assertRaises(RecordError): validate(record)
    def test_uncertain_outcome_is_preserved(self):
        record = self.record("failed_result"); record["data"]["outcome"] = "uncertain"
        validate(record)
        self.assertEqual(loads(canonical(record))["data"]["outcome"], "uncertain")
    def test_generation_requires_assembly(self):
        record = self.record("generation"); record["data"]["assembly_result"] = self.ids["result"]
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_generation_artifact_binding(self):
        record = self.record("generation"); record["data"]["artifact"]["digest"] = "sha256:" + "f" * 64
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_generation_package_binding(self):
        record = self.record("generation"); record["data"]["packages"][0]["result"] = self.ids["failed_result"]
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))
    def test_legacy_gap_propagation(self):
        report = inspect(fixture(legacy=True)[0])
        self.assertFalse(report["complete"]); self.assertTrue(report["gaps"])
        self.assertFalse(report["missing_records"])
    def test_store_durable_reopen_and_idempotent_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for record in self.bundle["records"].values():
                self.assertEqual(store.put(record), store.put(record))
            recovered = Store(directory)
            self.assertEqual(recovered.get(self.ids["start"]), self.record("start"))
            exported = recovered.bundle(self.bundle["roots"])
            self.assertTrue(inspect(exported)["complete"])
            self.assertIn(self.ids["failed_result"], exported["records"])
            self.assertFalse(list(Path(directory).glob('.prepared-*')))
    def test_store_tampering_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); identity = store.put(self.record("source"))
            path = Path(directory) / (identity[7:] + ".json"); path.write_text('{}')
            with self.assertRaises(RecordError): store.put(self.record("source"))
            self.assertEqual(path.read_text(), '{}')
    def test_store_missing_and_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            for identity in (self.ids["source"], "../../file"):
                with self.assertRaises(RecordError): Store(directory).get(identity)
    def test_failed_publication_leaves_no_partial_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            with patch('zog.build_record.store.os.link', side_effect=OSError("fixture interruption")):
                with self.assertRaises(OSError): store.put(self.record("source"))
            self.assertFalse(list(Path(directory).iterdir()))
            store.put(self.record("source"))
    def test_verify_source_and_recipe_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for identity, raw in self.blobs.items():
                path = Path(directory) / identity[7:]; path.write_bytes(raw); paths[identity] = str(path)
            report = verify_artifacts(self.bundle, paths)
            self.assertTrue(all(x["status"] == "verified" for x in report["artifact_verification"]))
            for identity in (self.record("source")["data"]["archives"][0]["digest"],
                             self.record("inputs")["data"]["recipe"]["digest"]):
                Path(paths[identity]).write_bytes(b"tampered")
            report = verify_artifacts(self.bundle, paths)
            self.assertEqual(sum(x["status"] == "mismatch" for x in report["artifact_verification"]), 2)
    def test_missing_artifacts_distinct_from_valid_graph(self):
        report = verify_artifacts(self.bundle, {})
        self.assertTrue(report["complete"])
        self.assertTrue(all(x["status"] == "not-provided" for x in report["artifact_verification"]))
    def test_cli_operational_errors_and_incomplete(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            path = Path(directory) / 'bundle.json'; path.write_bytes(canonical(fixture(legacy=True)[0]))
            self.assertEqual(main(['inspect', str(path)]), 3)
            self.assertEqual(main(['inspect', str(path) + '.absent']), 2)
            for line in output.getvalue().splitlines(): json.loads(line)
    def test_dependency_requires_successful_bound_result(self):
        record = self.record("assembly_inputs")
        record["data"]["dependencies"][0]["result"] = self.ids["failed_result"]
        with self.assertRaises(RecordError): inspect(self.bundle_with(record))

    def test_dependency_result_missing_is_incomplete(self):
        del self.bundle["records"][self.ids["result"]]
        self.assertIn(self.ids["result"], inspect(self.bundle)["missing_records"])

    def test_conflicting_attempt_bindings(self):
        record = self.record("start")
        record["data"]["prepared_at"] = "2026-10-02T12:02:01Z"
        with self.assertRaises(RecordError):
            inspect(self.bundle_with(record, [record_id(record), self.ids["start"]]))

    def test_retry_changed_current_inputs_does_not_rebind_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for record in self.bundle["records"].values(): store.put(record)
            changed, _, changed_ids = fixture(recipe_bytes=b"new current recipe")
            for label in ("source", "inputs"):
                store.put(changed["records"][changed_ids[label]])
            self.assertEqual(Store(directory).get(self.ids["start"])["data"]["inputs"], self.ids["inputs"])
            self.assertNotEqual(changed_ids["inputs"], self.ids["inputs"])

    def test_error_after_link_can_be_retried_without_rebinding(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            original = os.fsync
            calls = []
            def fail_directory(fd):
                calls.append(fd)
                if len(calls) == 2: raise OSError("fixture directory sync failure")
                original(fd)
            with patch('zog.build_record.store.os.fsync', side_effect=fail_directory):
                with self.assertRaises(OSError): Store(directory).put(self.record("start"))
            self.assertEqual(Store(directory).put(self.record("start")), self.ids["start"])

    def test_record_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'target'
            target.write_bytes(canonical(self.record("source")))
            (Path(directory) / (self.ids["source"][7:] + '.json')).symlink_to(target)
            with self.assertRaises(RecordError): Store(directory).get(self.ids["source"])

    def test_nonregular_artifact_rejected_without_blocking(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fifo'
            os.mkfifo(path)
            identity = self.record("source")["data"]["archives"][0]["digest"]
            with self.assertRaises(RecordError): verify_artifacts(self.bundle, {identity: path})

    def test_comparison_unchanged(self):
        result = compare(self.bundle, self.bundle)
        self.assertEqual(result["packages"], []); self.assertFalse(result["assembly_inputs_changed"])

if __name__ == '__main__': unittest.main()
