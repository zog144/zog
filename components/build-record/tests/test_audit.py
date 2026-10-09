"""Independent target binding, incomplete history and byte-verification gates."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from zog.build_record import RecordError, audit_generation, canonical
from zog.build_record.cli import main
from examples.local_pipeline import fixture


class GenerationAuditTests(unittest.TestCase):
    def setUp(self):
        self.bundle, self.blobs, self.ids = fixture()
        self.expected = dict(schema_version=1, record=self.ids['generation'],
                             generation_id='fixture:generation:1', packages=['demo-package'])

    def test_complete_metadata_does_not_claim_bytes_or_authenticity(self):
        before = canonical(self.bundle)
        result = audit_generation(self.bundle, self.expected)
        self.assertTrue(result['passed'])
        self.assertEqual(result['scope'], 'metadata')
        self.assertEqual(result['inspection']['artifact_verification'], 'not-checked')
        self.assertEqual(result['inspection']['authenticity'], 'not-verified')
        self.assertEqual(canonical(self.bundle), before)
        self.assertIn(self.ids['failed_result'], result['inspection']['records'])

    def test_valid_graph_for_wrong_target_is_rejected(self):
        for key, value in [('record', 'sha256:'+'0'*64), ('generation_id', 'different-host:generation:1'),
                           ('packages', ['other-package']), ('packages', []),
                           ('packages', ['demo-package', 'missing-package'])]:
            with self.subTest(key=key, value=value):
                result = audit_generation(self.bundle, {**self.expected, key:value})
                self.assertFalse(result['passed'])
                self.assertFalse(result['matches_expected_generation'])
                self.assertTrue(result['inspection']['complete'])

    def test_preparation_and_multi_root_exports_are_not_generation_audits(self):
        for roots in ([self.ids['start']], [self.ids['generation'], self.ids['failed_result']]):
            with self.subTest(roots=roots), self.assertRaises(RecordError):
                audit_generation({**self.bundle, 'roots':roots}, self.expected)

    def test_missing_root_is_unavailable_not_empty_inventory(self):
        del self.bundle['records'][self.ids['generation']]
        result = audit_generation(self.bundle, self.expected)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['generation_id'], 'unavailable')
        self.assertEqual(result['checks']['packages'], 'unavailable')
        self.assertIsNone(result['packages']['missing'])

    def test_missing_output_does_not_invent_package_history(self):
        del self.bundle['records'][self.ids['output']]
        result = audit_generation(self.bundle, self.expected)
        self.assertEqual(result['checks']['packages'], 'unavailable')
        self.assertEqual(result['packages']['unresolved_outputs'], [self.ids['output']])
        self.assertIsNone(result['packages']['missing'])
        self.assertFalse(result['passed'])

    def test_missing_transitive_source_blocks_even_when_membership_matches(self):
        del self.bundle['records'][self.ids['source']]
        result = audit_generation(self.bundle, self.expected)
        self.assertTrue(result['matches_expected_generation'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['references'], 'incomplete')

    def test_legacy_history_remains_incomplete(self):
        bundle, _, ids = fixture(legacy=True)
        result = audit_generation(bundle, {**self.expected, 'record':ids['generation']})
        self.assertTrue(result['matches_expected_generation'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['packages']['legacy'], ['demo-package'])
        self.assertTrue(result['inspection']['gaps'])

    def test_conflicting_expectations_and_bad_paths_are_errors(self):
        for change in [{'packages':['demo-package','demo-package']}, {'schema_version':True},
                       {'generation_id':''}, {'extra':1}, {'packages':None}]:
            with self.subTest(change=change), self.assertRaises(RecordError):
                audit_generation(self.bundle, {**self.expected, **change})
        with self.assertRaises(RecordError):
            audit_generation(self.bundle, self.expected, paths={next(iter(self.blobs)):3})

    def test_artifact_mapping_is_explicit_and_all_bytes_are_required(self):
        self.assertFalse(audit_generation(self.bundle, self.expected, paths={})['passed'])
        with tempfile.TemporaryDirectory() as directory:
            paths = {}
            for identity, raw in self.blobs.items():
                path = Path(directory)/identity[7:]; path.write_bytes(raw); paths[identity] = path
            self.assertTrue(audit_generation(self.bundle, self.expected, paths=paths)['passed'])
            path.write_bytes(b'changed')
            result = audit_generation(self.bundle, self.expected, paths=paths)
            self.assertFalse(result['passed'])
            self.assertIn('mismatch', [a['status'] for a in result['inspection']['artifact_verification']])
            path.unlink()
            result = audit_generation(self.bundle, self.expected, paths=paths)
            self.assertIn('unavailable', [a['status'] for a in result['inspection']['artifact_verification']])

    def test_cli_exit_codes_distinguish_mismatch_from_invalid_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); bundle = root/'bundle.json'; expected = root/'expected.json'
            bundle.write_bytes(canonical(self.bundle))
            for expectation, code in [(self.expected, 0), ({**self.expected, 'packages':[]}, 3),
                                      ({**self.expected, 'schema_version':2}, 2)]:
                expected.write_text(json.dumps(expectation))
                output = io.StringIO()
                with redirect_stdout(output):
                    actual = main(['audit-generation', str(bundle), '--expected', str(expected)])
                self.assertEqual(actual, code)
                self.assertIsInstance(json.loads(output.getvalue()), dict)

    def test_altered_record_is_not_a_valid_target(self):
        self.bundle['records'][self.ids['source']]['data']['package'] = 'tampered'
        with self.assertRaises(RecordError):
            audit_generation(self.bundle, self.expected)
