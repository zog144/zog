import copy
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from zog.host_install.state_contract import StateError, canonical, decode, digest, validate
from zog.host_install.state_gate import decide
from zog.host_install.state_inspect import assess_mount, directory, inspect_live, metadata, mounts, read_at
from zog.host_install.state_probe import _probe_directory, probe_live

FIXTURE = Path(__file__).resolve().parents[1] / 'examples/state-contract-v1'
BUNDLE = json.loads((FIXTURE / 'bundle.json').read_text())
CASES = json.loads((FIXTURE / 'scenarios.json').read_text())


def scenario(case):
    def test(self):
        evidence = copy.deepcopy(case['evidence'])
        try:
            assess_mount(case['mounts'], case['devices'], BUNDLE['bootstrap']['state'], '8:1')
        except StateError:
            evidence['mount_verified'] = False
        self.assertEqual(decide(BUNDLE, evidence), case['expected'])
    return test


class ScenarioTests(unittest.TestCase):
    pass

for case in CASES:
    setattr(ScenarioTests, 'test_' + case['name'].replace('-', '_'), scenario(case))


class RecordTests(unittest.TestCase):
    def test_fixture_records_and_hashes(self):
        validate(BUNDLE)
        self.assertEqual(len(CASES), 19)
        self.assertEqual(len({c['name'] for c in CASES}), 19)
        for name in BUNDLE:
            self.assertEqual(BUNDLE[name], json.loads((FIXTURE / (name + '.json')).read_text()))

    def test_duplicate_float_nan_and_oversize(self):
        for data in (b'{"a":1,"a":2}', b'{"n":1.5}', b'{"n":NaN}', b' ' * 65537):
            with self.subTest(data=data[:30]), self.assertRaises(StateError): decode(data)

    def test_bad_shapes_features_hashes_and_paths(self):
        variants = [
            ('bootstrap', 'schema', True), ('bootstrap', 'schema', 2),
            ('bootstrap', 'required_features', ['unknown']), ('bootstrap', 'mode', 'reset'),
            ('bootstrap', 'configuration_revision', True),
            ('bootstrap', 'installation_id', 'wrong'),
            ('accounts', 'profile', 'allocate-dynamically')]
        for name, key, value in variants:
            with self.subTest(key=key, value=value):
                b = copy.deepcopy(BUNDLE); b[name][key] = value
                with self.assertRaises(StateError): validate(b)
        for mutation in ('path', 'marker', 'record', 'unknown', 'boolean-account'):
            b = copy.deepcopy(BUNDLE)
            if mutation == 'path': b['bootstrap']['state']['mount_point'] = '/tmp/state'
            if mutation == 'marker': b['marker']['filesystem_uuid'] = b['marker']['partition_partuuid']
            if mutation == 'record': b['bootstrap']['installation_record']['sha256'] = '0' * 64
            if mutation == 'unknown': b['bootstrap']['auto_initialize'] = True
            if mutation == 'boolean-account': b['accounts']['schema'] = True
            with self.subTest(mutation=mutation), self.assertRaises(StateError): validate(b)

    def test_registry_credentials_and_control_rules(self):
        for origin in ('http://example.invalid', 'https://user:secret@example.invalid', 'https://example.invalid/a', 'https://example.invalid/#x', 'https://example.invalid:bad'):
            b = copy.deepcopy(BUNDLE); b['bootstrap']['registries'][0]['origin'] = origin
            with self.subTest(origin=origin), self.assertRaises(StateError): validate(b)
        b = copy.deepcopy(BUNDLE); b['bootstrap']['registries'][0]['role'] = 'observation'
        with self.assertRaises(StateError): validate(b)
        b = copy.deepcopy(BUNDLE); b['bootstrap']['control_authority']['offline_commands'] = 0
        with self.assertRaises(StateError): validate(b)

    def test_recovery_requires_named_identity(self):
        b = copy.deepcopy(BUNDLE); b['bootstrap']['mode'] = 'recovery'
        with self.assertRaises(StateError): validate(b)

    def test_offline_cli_never_reports_readiness(self):
        r = subprocess.run([sys.executable, '-m', 'zog.host_install', 'state-validate', str(FIXTURE / 'bundle.json')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['result'], {'status': 'offline-records-valid', 'control_authorized': False})


class GateTests(unittest.TestCase):
    def test_truthy_strings_are_rejected(self):
        for key in ('mount_verified', 'accounts_verified', 'recovery_hold'):
            e = copy.deepcopy(CASES[0]['evidence']); e[key] = 'yes'
            with self.subTest(key=key), self.assertRaises(StateError): decide(BUNDLE, e)

    def test_authorization_bound_to_volume_and_transaction(self):
        source = next(c for c in CASES if c['name'] == 'fresh-authorized')
        for key in ('installation_id', 'state_volume_id', 'initialization_id'):
            e = copy.deepcopy(source['evidence']); e['authorization'][key] = 'different'
            self.assertEqual(decide(BUNDLE, e)['identity_action'], 'block')

    def test_prepared_key_mismatch_blocked(self):
        e = copy.deepcopy(next(c for c in CASES if c['name'] == 'resume-prepared')['evidence'])
        e['identity']['initialization_id'] = 'other'
        self.assertEqual(decide(BUNDLE, e)['code'], 'prepared-identity-mismatch')

    def test_completed_identity_wins_over_fresh_permission(self):
        e = copy.deepcopy(CASES[0]['evidence'])
        e['authorization'].update(verified_current_transaction=True, action='initialize')
        self.assertEqual(decide(BUNDLE, e)['identity_action'], 'load-existing')

    def test_no_control_before_durability_or_expected_identity(self):
        for field, value in [('storage_probe', 'not-run'), ('storage_probe', 'failed')]:
            e = copy.deepcopy(CASES[0]['evidence']); e[field] = value
            self.assertEqual(decide(BUNDLE, e)['identity_action'], 'block')
        e['storage_probe'] = 'passed'; e['identity']['matches_expected'] = False
        self.assertEqual(decide(BUNDLE, e)['code'], 'identity-mismatch')


class MountTests(unittest.TestCase):
    def check(self, rows, devices=None, root='8:1'):
        return assess_mount(rows, devices or CASES[0]['devices'], BUNDLE['bootstrap']['state'], root)

    def test_mountinfo_escaping(self):
        rows = mounts('42 1 8:3 / /state rw,nosuid - ext4 /dev/sda3 rw\n43 42 8:3 /x /state/a\\040b rw - ext4 /dev/sda3 rw\n')
        self.assertEqual(rows[1]['target'], '/state/a b')
        with self.assertRaisesRegex(StateError, 'nested-mount'): self.check(rows)

    def test_superblock_readonly_subvolume_wrongdevice_and_root(self):
        for key, value in [('super_options', ['ro']), ('root', '/subdir'), ('device', '8:4'), ('type', 'tmpfs')]:
            rows = copy.deepcopy(CASES[0]['mounts']); rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(StateError): self.check(rows)
        with self.assertRaisesRegex(StateError, 'host-root-device'): self.check(CASES[0]['mounts'], root='8:3')

    def test_wrong_and_duplicate_partition(self):
        d = copy.deepcopy(CASES[0]['devices']); d[0]['partuuid'] = 'wrong'
        with self.assertRaises(StateError): self.check(CASES[0]['mounts'], d)
        d = copy.deepcopy(CASES[0]['devices']); d.append(dict(d[0], uuid='different', **{'maj:min': '8:4'}))
        with self.assertRaises(StateError): self.check(CASES[0]['mounts'], d)

    def test_mount_failure_precedes_any_state_open(self):
        with patch('zog.host_install.state_inspect.load_configuration', return_value=BUNDLE), patch('zog.host_install.state_inspect._mount', side_effect=StateError('state-not-mounted', 'test')), patch('zog.host_install.state_inspect.directory') as opened:
            with self.assertRaises(StateError): inspect_live()
            opened.assert_not_called()

    def test_recheck_rejects_mount_change(self):
        from zog.host_install.state_inspect import VerifiedState
        with tempfile.TemporaryDirectory() as tmp:
            fd = directory(tmp)
            with VerifiedState(BUNDLE, fd, CASES[0]['mounts'][0]) as c, patch('zog.host_install.state_inspect._mount', return_value={'id': 'changed'}):
                with self.assertRaisesRegex(StateError, 'mount-changed'): c.recheck()


class FileSafetyTests(unittest.TestCase):
    def test_symlink_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'real').mkdir(); Path(tmp, 'link').symlink_to('real')
            with self.assertRaises(OSError): directory(tmp + '/link')

    def test_record_owner_mode_symlink_hardlink_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            fd = directory(tmp)
            try:
                p = Path(tmp, 'record'); p.write_bytes(b'{}'); p.chmod(0o444)
                def read(name): return read_at(fd, name, os.getuid(), os.getgid())
                self.assertEqual(read('record'), b'{}')
                Path(tmp, 'link').symlink_to('record')
                with self.assertRaises(OSError): read('link')
                os.link(p, Path(tmp, 'hardlink'))
                with self.assertRaisesRegex(StateError, 'hardlink'): read('record')
                Path(tmp, 'hardlink').unlink(); p.chmod(0o644)
                with self.assertRaisesRegex(StateError, 'ownership-mode'): read('record')
                p.write_bytes(b'x' * 65537); p.chmod(0o444)
                with self.assertRaisesRegex(StateError, 'record-size'): read('record')
                with self.assertRaisesRegex(StateError, 'unsafe-path'): read('../record')
            finally: os.close(fd)

    def test_fifo_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkfifo(tmp + '/pipe', 0o444)
            fd = directory(tmp)
            try:
                with self.assertRaisesRegex(StateError, 'ownership-mode'): read_at(fd, 'pipe', os.getuid(), os.getgid())
            finally: os.close(fd)


class ProbeTests(unittest.TestCase):
    def run_probe(self, injected=None):
        with tempfile.TemporaryDirectory() as tmp:
            fd = directory(tmp)
            try:
                if injected:
                    operation, err = injected
                    with patch('zog.host_install.state_probe.os.' + operation, side_effect=OSError(err, 'injected')):
                        with self.assertRaises(OSError): _probe_directory(fd)
                else: _probe_directory(fd)
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally: os.close(fd)

    def test_success_cleans_up(self): self.run_probe()
    def test_write_enospc(self): self.run_probe(('write', errno.ENOSPC))
    def test_fsync_eio(self): self.run_probe(('fsync', errno.EIO))
    def test_rename_erofs(self): self.run_probe(('rename', errno.EROFS))

    def test_directory_fsync_failure_is_failure(self):
        fsync = os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError(errno.EIO, 'directory fsync')
            fsync(fd)
        with tempfile.TemporaryDirectory() as tmp:
            fd = directory(tmp)
            try:
                with patch('zog.host_install.state_probe.os.fsync', side_effect=fail_directory):
                    with self.assertRaises(OSError): _probe_directory(fd)
                self.assertEqual(list(Path(tmp).iterdir()), [])
            finally: os.close(fd)

    def test_short_writes_are_completed(self):
        original = os.write
        with patch('zog.host_install.state_probe.os.write', side_effect=lambda fd, data: original(fd, data[:7])):
            self.run_probe()

    def test_probe_requires_real_service_uid_before_inspection(self):
        with patch('zog.host_install.state_probe.os.geteuid', return_value=0), patch('zog.host_install.state_probe.inspect_live') as inspect:
            with self.assertRaisesRegex(StateError, 'probe-account'): probe_live()
            inspect.assert_not_called()

class InspectionBoundaryTests(unittest.TestCase):
    def test_os_errors_have_stable_codes(self):
        for number, code in [(errno.ENOENT, 'required-path-missing'), (errno.EIO, 'state-io-failure'), (errno.EACCES, 'state-access-denied')]:
            with patch('zog.host_install.state_inspect.load_configuration', side_effect=OSError(number, 'injected')):
                with self.assertRaises(StateError) as error: inspect_live()
                self.assertEqual(error.exception.code, code)

    def test_read_only_success_and_component_symlink_rejection(self):
        # Only the mount collector/config loader are synthetic. File access,
        # modes, marker reading and descriptor rechecks are real. This container
        # cannot map UID 970, so only expected ownership is translated to our UID.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp, 'state'); state.mkdir(mode=0o755)
            marker = state / '.zog-state.json'; marker.write_bytes(canonical(BUNDLE['marker'])); marker.chmod(0o444)
            home = state / 'host-discover'; home.mkdir(mode=0o700)
            for name in ('identity', 'trust', 'control', 'registries', 'health'):
                p = home / name; p.mkdir(mode=0o700)
            dev = state.stat().st_dev
            mount = dict(CASES[0]['mounts'][0], device=f'{os.major(dev)}:{os.minor(dev)}')
            original_directory, original_open = directory, os.open
            def fixture_metadata(fd, uid, gid, mode, is_directory=True):
                return metadata(fd, os.getuid(), os.getgid(), mode, is_directory)
            opens = []
            def read_only_open(path, flags, *args, **kwargs):
                opens.append(flags)
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                return original_open(path, flags, *args, **kwargs)
            def mapped_directory(path):
                self.assertEqual(path, '/state')
                return original_directory(str(state))
            with patch('zog.host_install.state_inspect.load_configuration', return_value=BUNDLE), patch('zog.host_install.state_inspect._mount', return_value=mount), patch('zog.host_install.state_inspect.accounts_match'), patch('zog.host_install.state_inspect.metadata', side_effect=fixture_metadata), patch('zog.host_install.state_inspect.directory', side_effect=mapped_directory), patch('zog.host_install.state_inspect.os.open', side_effect=read_only_open):
                with inspect_live() as context:
                    self.assertIsNotNone(context.fd)
                self.assertTrue(opens)
                (home / 'identity').rmdir(); (home / 'identity').symlink_to('trust')
                with self.assertRaisesRegex(StateError, 'unsafe-path'): inspect_live()
