"""Focused failure injection; no live services, cloud changes or npm downloads."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('frontend_install', Path(__file__).parents[1] / 'frontend-install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def release(self, identifier, text='sample'):
        directory = self.root / 'releases' / identifier
        dist = directory / 'dist'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'index.html').write_text(text)
        (dist / 'assets/LICENSES-123456abcdef.txt').write_text('legal')
        outputs = installer.regular_files(dist)
        installer.atomic_json(dist / 'frontend-build.json', {
            'mode': 'production', 'node_env': 'production', 'outputs': outputs,
            'licenses': 'assets/LICENSES-123456abcdef.txt'})
        installer.atomic_json(directory / 'installation.json', {
            'id': identifier, 'outputs': installer.regular_files(dist),
            'serving_contract': 'station-frontend-selection-v1'})
        return dist

    def test_missing_incomplete_or_modified_asset_rejected_before_selection(self):
        identifier = 'a' * 32
        dist = self.release(identifier)
        installer.validate_release(self.root, identifier)
        (dist / 'index.html').unlink()
        with self.assertRaisesRegex(installer.InstallError, 'Incomplete'):
            installer.activate(self.root, identifier, 'http://127.0.0.1:1')
        self.assertFalse((self.root / 'selection.json').exists())

    def test_activation_repeat_retention_and_explicit_rollback(self):
        first, second = 'a' * 32, 'b' * 32
        self.release(first, 'first'); self.release(second, 'second')
        with patch.object(installer, 'check_http'):
            installer.activate(self.root, first, 'http://127.0.0.1:1')
            installer.activate(self.root, second, 'http://127.0.0.1:1')
            installer.activate(self.root, second, 'http://127.0.0.1:1')
            self.assertEqual(installer.load(self.root / 'selection.json')['retained'], [second, first])
            installer.activate(self.root, first, 'http://127.0.0.1:1')
        self.assertEqual(installer.load(self.root / 'selection.json')['active'], first)

    def test_failed_health_check_restores_prior_selection(self):
        first, second = 'a' * 32, 'b' * 32
        self.release(first); self.release(second)
        with patch.object(installer, 'check_http'):
            installer.activate(self.root, first, 'http://127.0.0.1:1')
        previous = (self.root / 'selection.json').read_bytes()
        with patch.object(installer, 'check_http', side_effect=subprocess.CalledProcessError(1, 'probe')):
            with self.assertRaisesRegex(installer.InstallError, 'previous selection restored'):
                installer.activate(self.root, second, 'http://127.0.0.1:1')
        self.assertEqual((self.root / 'selection.json').read_bytes(), previous)
        self.assertFalse((self.root / 'activation.json').exists())

    def test_failed_first_activation_removes_selection(self):
        identifier = 'a' * 32; self.release(identifier)
        with patch.object(installer, 'check_http', side_effect=TimeoutError()):
            with self.assertRaises(installer.InstallError):
                installer.activate(self.root, identifier, 'http://127.0.0.1:1')
        self.assertFalse((self.root / 'selection.json').exists())

    def test_interrupted_activation_blocks_then_recovery_restores(self):
        first = 'a' * 32; self.release(first)
        installer.atomic_json(self.root / 'activation.json', {'previous': None})
        installer.atomic_json(self.root / 'selection.json', {'active': first})
        with self.assertRaisesRegex(installer.InstallError, 'Interrupted'):
            installer.activate(self.root, first, 'http://127.0.0.1:1')
        installer.recover(self.root)
        self.assertFalse((self.root / 'selection.json').exists())

    def test_asset_collision_rejected_and_selection_unchanged(self):
        first, second = 'a' * 32, 'b' * 32
        self.release(first)
        dist = self.release(second)
        (dist / 'assets/LICENSES-123456abcdef.txt').write_text('different legal bytes')
        inventory = installer.load(dist / 'frontend-build.json')
        inventory['outputs']['assets/LICENSES-123456abcdef.txt'] = installer.digest(dist / 'assets/LICENSES-123456abcdef.txt')
        installer.atomic_json(dist / 'frontend-build.json', inventory)
        installation = installer.load(dist.parent / 'installation.json')
        installation['outputs'] = installer.regular_files(dist)
        installer.atomic_json(dist.parent / 'installation.json', installation)
        with patch.object(installer, 'check_http'):
            installer.activate(self.root, first, 'http://127.0.0.1:1')
        previous = (self.root / 'selection.json').read_bytes()
        with self.assertRaisesRegex(installer.InstallError, 'collision'):
            installer.activate(self.root, second, 'http://127.0.0.1:1')
        self.assertEqual((self.root / 'selection.json').read_bytes(), previous)

    def test_unsafe_ids_symlinks_and_runtime_writable_output_rejected(self):
        with self.assertRaises(installer.InstallError):
            installer.named_directory(self.root, '../escape')
        identifier = 'a' * 32; dist = self.release(identifier)
        (dist / 'index.html').chmod(0o666)
        with self.assertRaisesRegex(installer.InstallError, 'not writable'):
            installer.validate_release(self.root, identifier)
        (dist / 'index.html').unlink(); (dist / 'index.html').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(installer.InstallError, 'Symbolic'):
            installer.validate_release(self.root, identifier)

    def test_operation_lock_is_exclusive(self):
        with installer.locked(self.root):
            with self.assertRaisesRegex(installer.InstallError, 'Another frontend operation'):
                with installer.locked(self.root):
                    self.fail('Acquired second lock')

    def test_missing_or_wrong_toolchain_is_actionable(self):
        record = {'node_path': '/bin/false', 'toolchain': {'node': '24.19.0'},
                  'build_uid': os.getuid(), 'build_gid': os.getgid()}
        (self.root / 'work').mkdir()
        with patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            with self.assertRaisesRegex(installer.InstallError, 'Required node 24.19.0'):
                installer.check_toolchain(record, self.root)

    def test_dependency_and_compile_failures_never_mark_built(self):
        record = {'npm_path': '/bin/false', 'phase': 'prepared'}
        installer.atomic_json(self.root / 'operation.json', record)
        for fail_call in (1, 2):
            with self.subTest(fail_call=fail_call), patch.object(installer, 'get_operation', return_value=(self.root, record)), patch.object(installer, 'check_snapshot'):
                effect = [None] * (fail_call - 1) + [installer.InstallError('injected dependency/compilation failure')]
                with patch.object(installer, 'execute', side_effect=effect), self.assertRaises(installer.InstallError):
                    installer.build(self.root, 'a' * 32)
            self.assertEqual(installer.load(self.root / 'operation.json')['phase'], 'prepared')
            self.assertFalse((self.root / 'selection.json').exists())

    def test_license_or_test_failure_cannot_install_release(self):
        record = {'npm_path': '/bin/false', 'phase': 'built'}
        for fail_call in (1, 2, 3):
            with patch.object(installer, 'get_operation', return_value=(self.root, record)), patch.object(installer, 'execute', side_effect=[None] * (fail_call - 1) + [installer.InstallError('injected license/test/output failure')]):
                with self.assertRaises(installer.InstallError):
                    installer.verify(self.root, 'a' * 32)
            self.assertFalse((self.root / 'releases').exists())

    def test_missing_named_identity_and_tool_are_actionable(self):
        with patch.object(installer.pwd, 'getpwnam', side_effect=KeyError()):
            with self.assertRaisesRegex(installer.InstallError, 'Missing local identity'):
                installer.identity('missing-test-account')
        record = {'node_path': '/missing/station-test-node'}
        with self.assertRaisesRegex(installer.InstallError, 'Missing pinned node'):
            installer.check_toolchain(record, self.root)

    def test_source_commit_and_blob_mismatch_rejected(self):
        frontend = self.root / 'frontend'
        frontend.mkdir(parents=True)
        (self.root / '.version-share').mkdir()
        (frontend / 'toolchain.json').write_text('{}')
        installer.atomic_json(self.root / '.version-share/baseline.json', {
            'repository': 'zog144/station-access', 'commit': 'a' * 40,
            'files': {'frontend/toolchain.json': {'mode': '100644', 'sha': 'b' * 40}}})
        with self.assertRaisesRegex(installer.InstallError, 'Source revision/repository differs'):
            installer.source_snapshot(self.root, 'c' * 40)
        with self.assertRaisesRegex(installer.InstallError, 'Source differs from commit'):
            installer.source_snapshot(self.root, 'a' * 40)

    def test_build_environment_excludes_application_credentials(self):
        with patch.dict(os.environ, {'VITE_PASSWORD': 'example', 'AWS_SECRET_ACCESS_KEY': 'example', 'STATION_ACCESS_PASSWORD': 'example', 'NODE_ENV': 'production'}):
            environment = installer.clean_environment(self.root, '/usr/bin/node')
        self.assertFalse(any(key.startswith(('VITE_', 'AWS_', 'STATION_ACCESS_')) for key in environment))
        self.assertNotIn('NODE_ENV', environment)


if __name__ == '__main__':
    unittest.main()
