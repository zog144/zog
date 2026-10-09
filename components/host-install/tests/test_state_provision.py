import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zog.host_install.state_contract import StateError, canonical, decode, digest
from zog.host_install.state_inspect import directory
from zog.host_install.state_io import publish
from zog.host_install.state_provision import prepare_tree, stage_overlay, transition
from zog.host_install.state_initialize import authorize, coordinate, authorization, operations, worker_process

BUNDLE = json.loads((Path(__file__).resolve().parents[1] / 'examples/state-contract-v1/bundle.json').read_text())

class Crash(BaseException): pass


def crash_at(wanted):
    def check(point):
        if point == wanted: raise Crash(point)
    return check


class Context:
    """Synthetic mounted-volume boundary; real filesystem below it."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.chmod(0o755)
        self.fd = directory(str(self.root))
        self.bundle = copy.deepcopy(BUNDLE)
        # Library-only integration fixture; never accepted by live validation.
        self.bundle['bootstrap']['state']['identity_directory'] = str(self.root / 'host-discover/identity')
        self.fault = False
    def recheck(self):
        if self.fault: raise StateError('mount-changed', 'injected disappearance')
    def close(self): os.close(self.fd)


class OverlayTests(unittest.TestCase):
    def test_canonical_publication_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'overlay'
            result = stage_overlay(BUNDLE, output)
            self.assertFalse(result['identity_created'])
            config = output / 'etc/zog/host-install'
            for key in ('accounts', 'installation', 'bootstrap'):
                self.assertEqual((config / (key + '.json')).read_bytes(), canonical(BUNDLE[key]))
                self.assertEqual((config / (key + '.json')).stat().st_mode & 0o777, 0o444)
            self.assertEqual(stage_overlay(BUNDLE, output), result)
            self.assertFalse((output / 'state').exists())

    def test_bootstrap_last_and_interrupted_publication_resumes(self):
        for point in ('staged:overlay-intent.json', 'linked:overlay-intent.json', 'directory-staged:etc',
                      'published:installation.json', 'linked:bootstrap.json'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'overlay'
                with self.assertRaises(Crash): stage_overlay(BUNDLE, output, checkpoint=crash_at(point))
                if point != 'linked:bootstrap.json': self.assertFalse((output / 'etc/zog/host-install/bootstrap.json').exists())
                stage_overlay(BUNDLE, output)
                self.assertEqual((output / 'etc/zog/host-install/bootstrap.json').read_bytes(), canonical(BUNDLE['bootstrap']))

    def test_partial_or_conflicting_record_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'overlay'
            with self.assertRaises(Crash): stage_overlay(BUNDLE, output, checkpoint=crash_at('published:installation.json'))
            target = output / 'etc/zog/host-install/accounts.json'
            target.chmod(0o600); target.write_bytes(b'partial'); target.chmod(0o444)
            with self.assertRaises(StateError): stage_overlay(BUNDLE, output)
            self.assertEqual(target.read_bytes(), b'partial')

    def test_transition_rejects_identity_and_authority_changes(self):
        for field in ('installation_id', 'state', 'initialization', 'control_authority'):
            b = copy.deepcopy(BUNDLE)
            # Validator rejects malformed changed references before publication.
            b['bootstrap'][field] = 'different'
            with self.subTest(field=field), self.assertRaises((StateError, TypeError)):
                transition(b, BUNDLE)
        new = copy.deepcopy(BUNDLE)
        new['installation']['operation'] = 'upgrade'
        new['installation']['record_id'] = '99999999-9999-4999-8999-999999999999'
        new['bootstrap']['configuration_revision'] = 2
        new['bootstrap']['mode'] = 'existing'
        new['bootstrap']['installation_record']['sha256'] = digest(new['installation'])
        transition(new, BUNDLE)
        with self.assertRaises(StateError): transition(new, None)

    def test_wrong_ca_bytes_are_rejected_before_writes(self):
        b = copy.deepcopy(BUNDLE)
        b['bootstrap']['registries'][0]['ca'] = dict(path='/etc/zog/host-install/ca/primary.pem', sha256='a' * 64)
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'overlay'
            with self.assertRaises(StateError): stage_overlay(b, out, ca_bytes={'primary': b'wrong'})
            self.assertFalse(out.exists())


class PreparationTests(unittest.TestCase):
    def test_requires_explicit_fresh_volume_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as temp:
            c = Context(temp)
            try:
                with self.assertRaises(StateError): prepare_tree(c, service_ids=(0, 0, 0, 0))
                volume = c.bundle['bootstrap']['state']['state_volume_id']
                prepare_tree(c, volume, service_ids=(0, 0, 0, 0))
                self.assertFalse((Path(temp) / 'host-discover/identity').exists())
                marker = (Path(temp) / '.zog-state.json').read_bytes()
                sentinel = Path(temp) / 'host-discover/control/existing-journal'
                sentinel.write_bytes(b'preserve')
                prepare_tree(c, service_ids=(0, 0, 0, 0))
                self.assertEqual(sentinel.read_bytes(), b'preserve')
                self.assertEqual((Path(temp) / '.zog-state.json').read_bytes(), marker)
            finally: c.close()

    def test_unmarked_nonempty_volume_never_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'foreign').write_bytes(b'data')
            c = Context(temp)
            try:
                with self.assertRaisesRegex(StateError, 'nonempty-unmarked-volume'):
                    prepare_tree(c, c.bundle['bootstrap']['state']['state_volume_id'], service_ids=(0, 0, 0, 0))
                self.assertEqual(Path(temp, 'foreign').read_bytes(), b'data')
            finally: c.close()

    def test_interrupted_marker_and_directory_provisioning(self):
        for point in ('staged:.zog-state.json', 'linked:.zog-state.json', 'directory-staged:host-install', 'directory-staged:host-discover'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                c = Context(temp)
                try:
                    volume = c.bundle['bootstrap']['state']['state_volume_id']
                    with self.assertRaises(Crash): prepare_tree(c, volume, crash_at(point), service_ids=(0, 0, 0, 0))
                    prepare_tree(c, volume, service_ids=(0, 0, 0, 0))
                    self.assertTrue(Path(temp, 'host-discover/health').is_dir())
                finally: c.close()

    def test_wrong_permissions_and_symlink_not_repaired(self):
        for variant in ('mode', 'symlink'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                c = Context(temp)
                try:
                    prepare_tree(c, c.bundle['bootstrap']['state']['state_volume_id'], service_ids=(0, 0, 0, 0))
                    target = Path(temp, 'host-discover/health')
                    if variant == 'mode': target.chmod(0o755)
                    else: target.rmdir(); target.symlink_to('control')
                    with self.assertRaises((StateError, OSError)): prepare_tree(c, service_ids=(0, 0, 0, 0))
                    self.assertTrue(target.is_symlink() if variant == 'symlink' else target.stat().st_mode & 0o777 == 0o755)
                finally: c.close()

    def test_mount_loss_precedes_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            c = Context(temp)
            try:
                c.fault = True
                with self.assertRaises(StateError): prepare_tree(c, 'any', service_ids=(0, 0, 0, 0))
                self.assertEqual(list(Path(temp).iterdir()), [])
            finally: c.close()


@unittest.skipUnless(os.environ.get('HOST_IDENTIFY_SOURCE'), 'pinned host-identify dependency not supplied')
class IdentityCoordinatorTests(unittest.TestCase):
    def setUp(self):
        from zog.host_identify.initialization import prepare, load_existing
        self.prepare, self.load_existing = prepare, load_existing
        self.temp = tempfile.TemporaryDirectory()
        self.c = Context(self.temp.name)
        prepare_tree(self.c, self.c.bundle['bootstrap']['state']['state_volume_id'], service_ids=(0, 0, 0, 0))
        self.calls = []

    def tearDown(self): self.c.close(); self.temp.cleanup()

    def worker(self, action, auth, receipt):
        self.calls.append(action)
        if action == 'prepare': return self.prepare(auth['identity_directory'], auth)
        self.load_existing(auth['identity_directory'], receipt)
        return receipt

    def authorize(self, checkpoint=lambda _: None):
        return authorize(self.c, self.c.bundle['bootstrap']['initialization']['authorization_id'], checkpoint)

    def coordinate(self, checkpoint=lambda _: None):
        return coordinate(self.c, self.worker, checkpoint, service_ids=(0, 0))

    def test_fresh_flag_is_not_authorization(self):
        with self.assertRaisesRegex(StateError, 'initialization-not-authorized'): self.coordinate()
        self.assertEqual(self.calls, [])
        self.assertFalse(Path(self.temp.name, 'host-discover/identity').exists())

    def test_real_prepare_consume_and_load_are_idempotent(self):
        self.authorize()
        result = self.coordinate()
        key = Path(self.temp.name, 'host-discover/identity/identity.pem').read_bytes()
        self.calls.clear()
        self.assertEqual(self.coordinate(), result)
        self.assertEqual(self.calls, ['load-existing', 'load-existing'])
        self.assertEqual(Path(self.temp.name, 'host-discover/identity/identity.pem').read_bytes(), key)
        self.assertFalse(result['transport_enabled'])
        record = Path(self.temp.name, 'host-install/operations/identity-consumed.json')
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b'PRIVATE KEY', record.read_bytes())

    def test_resume_after_key_publication_uses_same_key(self):
        self.authorize()
        with self.assertRaises(Crash): self.coordinate(crash_at('identity-prepared'))
        key = Path(self.temp.name, 'host-discover/identity/identity.pem').read_bytes()
        result = self.coordinate()
        self.assertEqual(Path(self.temp.name, 'host-discover/identity/identity.pem').read_bytes(), key)
        self.assertEqual(result['receipt'], json.loads(Path(self.temp.name, 'host-discover/identity/receipt.json').read_text()))

    def test_resume_consumption_link_does_not_prepare_again(self):
        self.authorize()
        with self.assertRaises(Crash): self.coordinate(crash_at('linked:identity-consumed.json'))
        self.calls.clear(); self.coordinate()
        self.assertNotIn('prepare', self.calls)
        self.assertFalse(Path(self.temp.name, 'host-install/operations/.pending.identity-consumed.json').exists())

    def test_authorization_link_crash_resumes(self):
        with self.assertRaises(Crash): self.authorize(crash_at('linked:identity-authorization.json'))
        self.authorize(); self.coordinate()

    def test_consumed_missing_key_enters_hold_without_regeneration(self):
        self.authorize(); self.coordinate(); self.calls.clear()
        key = Path(self.temp.name, 'host-discover/identity/identity.pem'); key.unlink()
        with self.assertRaises(ValueError): self.coordinate()
        self.assertNotIn('prepare', self.calls)
        self.assertFalse(key.exists())
        self.assertTrue(Path(self.temp.name, 'host-install/operations/recovery-hold.json').exists())
        with self.assertRaisesRegex(StateError, 'recovery-required'): self.coordinate()

    def test_changed_authorization_cannot_adopt_key(self):
        self.authorize(); self.coordinate(); self.calls.clear()
        self.c.bundle['bootstrap']['initialization']['authorization_id'] = '99999999-9999-4999-8999-999999999999'
        with self.assertRaises(StateError): self.coordinate()
        with self.assertRaises(StateError): self.authorize()
        self.assertEqual(self.calls, [])

    def test_corrupt_consumption_is_not_replaced(self):
        self.authorize(); self.coordinate(); self.calls.clear()
        record = Path(self.temp.name, 'host-install/operations/identity-consumed.json')
        record.write_bytes(b'{broken')
        with self.assertRaises(StateError): self.coordinate()
        self.assertEqual(record.read_bytes(), b'{broken')
        self.assertEqual(self.calls, [])

    def test_prepared_transaction_missing_key_is_recovery(self):
        self.authorize()
        def crash_prepare(action, auth, receipt):
            from zog.host_identify import initialization
            original = initialization.create
            def create(fd, name, data):
                original(fd, name, data)
                if name == 'initialization.json': raise Crash()
            with patch.object(initialization, 'create', side_effect=create): return self.worker(action, auth, receipt)
        with self.assertRaises(Crash): coordinate(self.c, crash_prepare, service_ids=(0, 0))
        with self.assertRaises(ValueError): self.coordinate()
        self.assertFalse(Path(self.temp.name, 'host-discover/identity/identity.pem').exists())
        self.assertTrue(Path(self.temp.name, 'host-install/operations/recovery-hold.json').exists())

    def test_consumption_fsync_failure_blocks_and_preserves_key(self):
        self.authorize()
        from zog.host_install import state_initialize
        original = state_initialize.publish
        def publish_failed(fd, name, *args, **kwargs):
            if name == 'identity-consumed.json': raise OSError(errno.EIO, 'injected fsync')
            return original(fd, name, *args, **kwargs)
        with patch.object(state_initialize, 'publish', side_effect=publish_failed):
            with self.assertRaises(OSError): self.coordinate()
        self.assertTrue(Path(self.temp.name, 'host-discover/identity/identity.pem').exists())
        self.assertFalse(Path(self.temp.name, 'host-install/operations/identity-consumed.json').exists())
        with self.assertRaisesRegex(StateError, 'recovery-required'): self.coordinate()

    def test_wrong_receipt_cannot_be_consumed(self):
        self.authorize()
        def wrong(action, auth, receipt):
            result = self.worker(action, auth, receipt)
            result['authorization_id'] = '99999999-9999-4999-8999-999999999999'
            return result
        with self.assertRaises(StateError): coordinate(self.c, wrong, service_ids=(0, 0))
        self.assertFalse(Path(self.temp.name, 'host-install/operations/identity-consumed.json').exists())

    def test_mount_loss_after_prepare_prevents_consumption(self):
        self.authorize()
        def lose(action, auth, receipt):
            result = self.worker(action, auth, receipt)
            self.c.fault = True
            return result
        with self.assertRaises(StateError): coordinate(self.c, lose, service_ids=(0, 0))
        self.assertFalse(Path(self.temp.name, 'host-install/operations/identity-consumed.json').exists())


class WorkerBoundaryTests(unittest.TestCase):
    def test_no_root_identity_worker(self):
        from zog.host_install.identity_worker import run
        with patch('zog.host_install.identity_worker.os.geteuid', return_value=0):
            with self.assertRaisesRegex(StateError, 'worker-account'): run({})

    def test_subprocess_drops_credentials_and_does_not_inherit_environment(self):
        from types import SimpleNamespace
        with patch('zog.host_install.state_initialize.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'{}')) as run:
            worker_process('prepare', {}, None)
        opts = run.call_args.kwargs
        self.assertEqual((opts['user'], opts['group'], opts['extra_groups']), (970, 970, [972, 973]))
        self.assertNotIn('PYTHONPATH', opts['env'])
        self.assertTrue(opts['close_fds'])

class CompletedLayoutTests(unittest.TestCase):
    def test_missing_completed_journal_directory_is_never_recreated(self):
        with tempfile.TemporaryDirectory() as temp:
            c = Context(temp)
            try:
                prepare_tree(c, c.bundle['bootstrap']['state']['state_volume_id'], service_ids=(0, 0, 0, 0))
                control = Path(temp, 'host-discover/control'); control.rmdir()
                with self.assertRaises(FileNotFoundError): prepare_tree(c, service_ids=(0, 0, 0, 0))
                self.assertFalse(control.exists())
            finally: c.close()

    def test_marker_alone_does_not_authorize_layout_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            c = Context(temp)
            try:
                marker = Path(temp, '.zog-state.json'); marker.write_bytes(canonical(c.bundle['marker'])); marker.chmod(0o444)
                with self.assertRaisesRegex(StateError, 'layout-not-authorized'): prepare_tree(c, service_ids=(0, 0, 0, 0))
                self.assertFalse(Path(temp, 'host-discover').exists())
            finally: c.close()

class ProjectionTests(unittest.TestCase):
    def test_projection_is_public_metadata_bound_to_boot_and_configuration(self):
        from zog.host_install.state_initialize import publish_projection, clear_projection
        auth = authorization(BUNDLE)
        receipt = dict(schema=1, kind='zog-identity-receipt', authorization_sha256=hashlib.sha256(canonical(auth) + b'\n').hexdigest(),
                       authorization_id=auth['authorization_id'], installation_id=auth['installation_id'],
                       state_volume_id=auth['state_volume_id'], fingerprint='a' * 64)
        with tempfile.TemporaryDirectory() as temp:
            fd = directory(temp)
            try:
                value = publish_projection(fd, BUNDLE, {'receipt': receipt}, '99999999-9999-4999-8999-999999999999')
                self.assertEqual(value['bootstrap_sha256'], digest(BUNDLE['bootstrap']))
                self.assertFalse(value['control_authorized'])
                self.assertEqual(Path(temp, 'identity-consumed.json').stat().st_mode & 0o777, 0o444)
                clear_projection(fd)
                self.assertEqual(list(Path(temp).iterdir()), [])
            finally: os.close(fd)

    def test_interrupted_projection_link_can_be_discarded_safely(self):
        from zog.host_install.state_initialize import clear_projection
        with tempfile.TemporaryDirectory() as temp:
            fd = directory(temp)
            try:
                with self.assertRaises(Crash): publish(fd, 'identity-consumed.json', b'{}', 0o444, checkpoint=crash_at('linked:identity-consumed.json'))
                clear_projection(fd)
                self.assertEqual(list(Path(temp).iterdir()), [])
            finally: os.close(fd)
