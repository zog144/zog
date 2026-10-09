import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from zog.build_trace import BuildTrace, InspectionLimits, TraceError
from zog.build_trace.source import Snapshot
from zog.build_trace.shell import inline_shell


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.root = self.project / 'state/image-build'
        self.root.mkdir(parents=True)

    def put(self, path, record):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
        return path

    def trace(self, **kwargs):
        return BuildTrace(self.project, host_id='fixture', **kwargs)

    def view(self, attempt, package='gcc-final', alias='gcc'):
        self.put(f'attempts/{attempt}/status.json', {'status': 'failed'})
        self.put(f'attempts/{attempt}/packages/{package}/build-0.view.json',
                 dict(schema=1, attempt_id=attempt, pipeline_id='p', package=alias,
                      phase='build', command_index=0, command=['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'echo fixture'],
                      checkpoint='build-0.controller.json'))

    def test_history_above_64_mib_small_pages_do_not_read_inventories(self):
        padding = 'x' * (9 * 1024 * 1024)
        for index in range(8):
            attempt = f'build-{index}'
            self.view(attempt)
            self.put(f'attempts/{attempt}/packages/gcc-final/prepared.json',
                     {'inputs': {'package': 'recipe'}, 'root': [{'path': 'fixture', 'padding': padding}]})
        # A broken unrelated pipeline inventory cannot block a package search.
        self.put('pipelines/unrelated/pipeline.json', {'schema': 999})
        seen, cursor, pages = [], None, 0
        original = Snapshot.read
        def checked(snapshot, path, **kwargs):
            self.assertFalse(path.endswith(('/prepared.json', '/result.json', '/pipeline.json')), path)
            return original(snapshot, path, **kwargs)
        with patch.object(Snapshot, 'read', checked):
            while True:
                page = self.trace().list_builds(package='gcc-final', limit=2, cursor=cursor)
                seen += [r['id'] for r in page['items']]
                self.assertLess(page['inspection']['source_bytes'], 128 * 1024)
                self.assertLessEqual(page['inspection']['scanned_builds'], 2)
                pages += 1
                cursor = page['next_cursor']
                if not page['has_more']:
                    break
        self.assertEqual(seen, [f'attempt:build-{i}' for i in range(8)])
        self.assertEqual(pages, 4)

    def test_deep_inspection_above_old_64_mib_budget(self):
        self.put('attempts/deep/status.json', {'status': 'complete'})
        payload = 'x' * (9 * 1024 * 1024)
        for i in range(8):
            self.put(f'attempts/deep/packages/p{i}/prepared.json',
                     {'inputs': {'package': f'recipe-{i}'}, 'root': [{'path': 'fixture', 'padding': payload}]})
        result = self.trace().inspect_build('attempt:deep')
        self.assertGreater(result['inspection']['source_bytes'], 64 * 1024 * 1024)
        self.assertEqual(result['inspection']['source_byte_limit'], 256 * 1024 * 1024)
        with self.assertRaises(TraceError) as error:
            self.trace(limits=InspectionLimits(source_bytes=64 * 1024 * 1024)).inspect_build('attempt:deep')
        self.assertEqual(error.exception.details['budget'], 'source-bytes')

    def test_redaction_precedes_preview_truncation(self):
        self.view('a')
        path = self.root / 'attempts/a/packages/gcc-final/build-0.view.json'
        record = json.loads(path.read_text())
        record['command'] = ['curl', 'https://user:' + 'sensitive-value' * 100 + '@example.invalid']
        path.write_text(json.dumps(record))
        row = self.trace().list_builds()['items'][0]
        self.assertNotIn('sensitive-value', json.dumps(row))
        self.assertIn('[REDACTED]', row['command_preview'][1])

    def test_alias_filter_and_filtered_commands_preserve_total_count(self):
        self.view('build-a')
        self.view('build-a', package='other', alias='other')
        rows = self.trace().list_builds(package='gcc')['items']
        self.assertEqual(rows[0]['command_count'], 2)
        self.assertEqual(rows[0]['matched_command_count'], 1)

    def test_scan_continuation_can_return_empty_page_without_skipping(self):
        for i in range(5):
            self.put(f'attempts/a{i}/status.json', {'status': 'failed' if i == 4 else 'complete'})
        trace = self.trace(limits=InspectionLimits(scan_builds=2))
        first = trace.list_builds(status='failed')
        self.assertEqual(first['items'], [])
        self.assertTrue(first['has_more'])
        second = trace.list_builds(status='failed', cursor=first['next_cursor'])
        self.assertEqual(second['items'], [])
        last = trace.list_builds(status='failed', cursor=second['next_cursor'])
        self.assertEqual(last['items'][0]['id'], 'attempt:a4')
        self.assertFalse(last['has_more'])

    def test_byte_budget_continuation_does_not_skip_candidate(self):
        for i in range(3):
            self.put(f'attempts/a{i}/status.json', {'status': 'complete'})
        trace = self.trace(limits=InspectionLimits(list_source_bytes=30))
        first = trace.list_builds()
        self.assertEqual(first['items'][0]['id'], 'attempt:a0')
        self.assertEqual(first['inspection']['stopped_reason'], 'source-budget')
        second = trace.list_builds(cursor=first['next_cursor'])
        self.assertEqual(second['items'][0]['id'], 'attempt:a1')

    def test_single_record_budget_error_is_actionable(self):
        self.put('attempts/a/status.json', {'status': 'complete'})
        try:
            self.trace(limits=InspectionLimits(list_source_bytes=2)).list_builds()
        except TraceError as error:
            self.assertEqual(error.code, 'source-too-large')
            self.assertEqual(error.details['budget'], 'source-bytes')
            self.assertEqual(error.details['record'], 'attempts/a/status.json')
            self.assertEqual(error.details['source_byte_limit'], 2)
            self.assertGreater(error.details['required_bytes'], 2)
        else:
            self.fail('missing budget error')

    def test_direct_command_and_logs_ignore_unrelated_metadata(self):
        self.view('a')
        self.put('attempts/a/packages/gcc-final/prepared.json', {'oversized': 'x' * (17 * 1024 * 1024)})
        self.put('attempts/a/packages/other/build-0.controller.json', {'malformed': True})
        self.put('pipelines/other/pipeline.json', {'schema': 999})
        trace = self.trace(limits=InspectionLimits(source_bytes=8192))
        command = trace.inspect_command('attempt:a', 'packages/gcc-final/build-0')
        self.assertEqual(command['script']['value'], 'echo fixture')
        self.assertEqual(command['shell_parsing'], 'captured')
        self.assertLess(command['inspection']['source_bytes'], 8192)
        page = trace.logs('attempt:a', 'packages/gcc-final/build-0')
        self.assertEqual(page['availability'], 'identity-unavailable')
        self.assertEqual(page['inspection'], command['inspection'])

    def test_selected_attempt_ignores_unrelated_pipeline(self):
        self.view('a')
        self.put('pipelines/p/pipeline.json', {'schema': 1, 'pipeline_id': 'p', 'recipes': [], 'attempts': {'a': 'a'}})
        self.put('pipelines/broken/pipeline.json', {'schema': 999})
        result = self.trace().inspect_build('attempt:a')
        self.assertEqual(result['pipeline_id'], 'p')

    def test_diagnostics_report_unsupported_instead_of_empty_success(self):
        self.put('attempts/gcc-fixture-pass2/focused-20261002-launch.json', {'job_id': 'opaque'})
        self.put('attempts/gcc-fixture-pass2/focused-20261002-job.json', {'outcome': 'success'})
        result = self.trace().inspect_build('attempt:gcc-fixture-pass2')
        self.assertEqual(result['layout']['status'], 'unsupported-layout')
        self.assertIsNone(result['command_count'])
        self.assertIsNone(result['status']['value'])
        self.assertEqual(result['layout']['reason'], 'diagnostic-receipts-without-owner-adapter')
        self.assertEqual(result['retry_relationships']['origin'], 'missing')
        self.assertIsNone(self.trace().list_builds()['items'][0]['command_count'])
        with self.assertRaises(TraceError) as error:
            self.trace().logs('attempt:gcc-fixture-pass2', 'focused-20261002')
        self.assertEqual(error.exception.code, 'unsupported-layout')

    def test_config_validation_and_cli_budget_details(self):
        self.assertEqual(InspectionLimits().source_bytes, 256 * 1024 * 1024)
        for invalid in (0, -1, True):
            with self.assertRaises(TraceError):
                InspectionLimits(source_bytes=invalid)
        self.put('attempts/a/status.json', {'status': 'complete', 'error': 'x' * (2 * 1024 * 1024)})
        result = subprocess.run([sys.executable, '-m', 'zog.build_trace', '--project-root', str(self.project),
            '--host-id', 'fixture', '--list-source-limit-mib', '1', 'list'], capture_output=True, text=True)
        error = json.loads(result.stdout)['error']
        self.assertEqual(result.returncode, 3)
        self.assertEqual(error['details']['record'], 'attempts/a/status.json')


class ShellTests(unittest.TestCase):
    def test_supported_option_sequences(self):
        for options in (['-eu', '-o', 'pipefail', '-c'], ['-ec'], ['-c', '-e'],
                        ['--noprofile', '--norc', '-c'], ['-O', 'extglob', '-c'], ['-c', '--']):
            with self.subTest(options=options):
                parsed = inline_shell(['/bin/bash', *options, 'echo safe', 'name', 'argument'])
                self.assertEqual(parsed['script'], 'echo safe')
                self.assertEqual(parsed['status'], 'captured')
        self.assertEqual(inline_shell(['/bin/sh', '-c', ''])['script'], '')

    def test_no_guessing_or_searching_later_argv(self):
        for argv, status in [(['/bin/bash', 'file.sh', '-c', 'not-inline'], 'no-inline-script'),
            (['/usr/bin/python', '-c', 'code'], 'not-shell'),
            (['/bin/bash', '--unknown', '-c', 'body'], 'unsupported-options'),
            (['/bin/bash', '-o'], 'unsupported-options'),
            (['/bin/bash', '-c'], 'missing-command-string'),
            (['/bin/bash', '--', '-c', 'body'], 'no-inline-script')]:
            with self.subTest(argv=argv):
                self.assertEqual(inline_shell(argv)['status'], status)
                self.assertIsNone(inline_shell(argv)['script'])

if __name__ == '__main__':
    unittest.main()
