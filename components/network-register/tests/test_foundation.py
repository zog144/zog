import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zog.network_register.contracts import Capability, NetworkError
from zog.network_register.models import Connection, ZoneBinding, Plan, RecordSnapshot
from zog.network_register.ledger import OperationLedger
from zog.network_register.store import SqliteStateStore


class Authorization:
    enabled = True
    def authorize(self, actor, owner, connection, binding, action):
        return self.enabled and actor == 'admin' and owner == 'owner'


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.store = SqliteStateStore(self.path, create=True)
        self.auth = Authorization(); self.now = 1000
        self.ledger = OperationLedger(self.store, self.auth, lambda: self.now)
        self.connection = Connection('connection', 'owner', 'cloudflare', 'account', 'vault:credential:1', status='ready')
        self.binding = ZoneBinding('binding', 'owner', 'connection', 'zone', 'Example.COM.', 'hosts.example.com', status='ready')
        self.ledger.put_connection('admin', self.connection, 0)
        self.ledger.put_binding('admin', self.binding, 0)
        self.snapshot = RecordSnapshot('one.hosts.example.com', '8.8.8.8', 300)
        self.plan = Plan('owner', 'binding', '12345678-1234-1234-1234-123456789abc', 1, 1, 1, 'create', None, self.snapshot)

    def prepare(self, request='request', plan=None):
        return self.ledger.prepare('admin', request, plan or self.plan)

    def step(self, row, state, **kwargs):
        return self.ledger.transition('admin', 'owner', row['request_id'], row['revision'], state, **kwargs)

    def success(self):
        r = self.prepare(); r = self.step(r, 'dispatching'); r = self.step(r, 'verifying')
        return self.step(r, 'succeeded', proof='matched', record_id='provider-record')

    def assertCode(self, code, fn):
        with self.assertRaises(NetworkError) as ctx: fn()
        self.assertEqual(ctx.exception.code, code)

    def test_normalization_and_scope(self):
        self.assertEqual(self.binding.zone_name, 'example.com')
        self.assertEqual(RecordSnapshot('BÜCHER.hosts.example.com.', '8.8.8.8', 300).name, 'xn--bcher-kva.hosts.example.com')
        for name in ('hosts.example.com', 'one.evilhosts.example.com', 'one.two.hosts.example.com'):
            p = replace(self.plan, after=replace(self.snapshot, name=name))
            self.assertCode('validation', lambda: self.prepare(plan=p))

    def test_snapshot_rejects_private_reserved_and_unsupported_writes(self):
        for address in ('127.0.0.1', '192.0.2.1', '10.0.0.1', '::1'):
            with self.assertRaises(ValueError): replace(self.snapshot, address=address)
        for change in ({'type': 'AAAA'}, {'proxied': True}, {'ttl': True}, {'name': '*.hosts.example.com'}):
            with self.assertRaises(ValueError): replace(self.snapshot, **change)

    def test_capability_unknown_is_distinct_from_denied(self):
        self.assertIsNone(Capability(True, None, None, 'unchecked').authorized)
        with self.assertRaises(ValueError): Capability(True, None, True, 'unchecked')

    def test_duplicate_returns_identical_operation_and_conflicting_payload_rejected(self):
        first = self.prepare(); self.assertEqual(first, self.prepare())
        self.assertCode('conflict', lambda: self.prepare(plan=replace(self.plan, after=replace(self.snapshot, address='9.9.9.9'))))

    def test_request_key_is_owner_scoped_and_read_authorized(self):
        self.prepare()
        self.assertCode('permission', lambda: self.ledger.inspect_operation('other', 'owner', 'request'))
        self.assertCode('not-found', lambda: self.ledger.inspect_operation('admin', 'other-owner', 'request'))
        self.assertCode('permission', lambda: self.prepare(plan=replace(self.plan, owner_id='other-owner')))

    def test_concurrent_duplicate_preparation_creates_once(self):
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(lambda _: self.prepare(), range(2)))
        self.assertEqual(rows[0]['id'], rows[1]['id'])
        with self.store.transaction(): self.assertEqual(len(self.store.all('operation')), 1)

    def test_single_active_operation_blocks_new_intent(self):
        self.prepare()
        self.assertCode('conflict', lambda: self.prepare('new', replace(self.plan, desired_revision=2)))

    def test_connection_revision_and_account_binding(self):
        self.assertCode('conflict', lambda: self.ledger.put_connection('admin', replace(self.connection, revision=2), 0))
        self.assertCode('conflict', lambda: self.ledger.put_connection('admin', replace(self.connection, account_ref='other', revision=2), 1))

    def test_overlapping_prefixes_rejected(self):
        for prefix in ('hosts.example.com', 'nested.hosts.example.com'):
            self.assertCode('conflict', lambda: self.ledger.put_binding('admin', replace(self.binding, id='other', prefix=prefix), 0))

    def test_discovery_grants_no_management_rights(self):
        self.ledger.put_binding('admin', replace(self.binding, status='discovered', revision=2), 1)
        self.assertCode('permission', lambda: self.prepare(plan=replace(self.plan, binding_revision=2)))

    def test_rotation_or_revocation_blocks_prepared_dispatch(self):
        row = self.prepare()
        self.ledger.put_connection('admin', replace(self.connection, credential_ref='vault:credential:2', revision=2), 1)
        self.assertCode('conflict', lambda: self.step(row, 'dispatching'))
        self.ledger.put_connection('admin', replace(self.connection, status='revoked', revision=3), 2)
        self.assertCode('permission', lambda: self.step(row, 'dispatching'))
        self.assertEqual(self.ledger.inspect_operation('admin', 'owner', 'request')['state'], 'prepared')

    def test_authorization_rechecked_before_dispatch(self):
        row = self.prepare(); self.auth.enabled = False
        self.assertCode('permission', lambda: self.step(row, 'dispatching'))

    def test_stale_transition_and_skipping_verification_rejected(self):
        row = self.prepare(); dispatched = self.step(row, 'dispatching')
        self.assertCode('conflict', lambda: self.step(row, 'cancelled'))
        self.assertCode('conflict', lambda: self.step(dispatched, 'succeeded', proof='matched', record_id='record'))
        self.assertCode('conflict', lambda: self.step(dispatched, 'failed'))

    def test_reopen_preserves_dispatched_intent_not_new_desired_state(self):
        row = self.step(self.prepare(), 'dispatching')
        reopened = OperationLedger(SqliteStateStore(self.path), self.auth)
        self.assertEqual(reopened.inspect_operation('admin', 'owner', 'request'), row)
        self.assertCode('conflict', lambda: reopened.prepare('admin', 'new', replace(self.plan, desired_revision=2)))

    def test_uncertainty_blocks_until_verified(self):
        row = self.step(self.step(self.prepare(), 'dispatching'), 'uncertain')
        self.assertCode('conflict', lambda: self.step(row, 'dispatching'))
        row = self.step(row, 'verifying')
        self.assertCode('validation', lambda: self.step(row, 'succeeded'))
        row = self.step(row, 'succeeded', proof='matched', record_id='provider-record')
        self.assertEqual(row['state'], 'succeeded')

    def test_retry_requires_proven_unapplied_and_persisted_due_time(self):
        row = self.step(self.step(self.prepare(), 'dispatching'), 'verifying')
        self.assertCode('validation', lambda: self.step(row, 'retry-wait', retry_at=1100))
        row = self.step(row, 'retry-wait', proof='unapplied', retry_at=1100)
        self.assertCode('conflict', lambda: self.step(row, 'dispatching'))
        self.now = 1100
        self.assertEqual(self.step(row, 'dispatching')['state'], 'dispatching')

    def test_owned_record_update_requires_last_applied_and_exact_id(self):
        self.success()
        p = Plan('owner', 'binding', '12345678-1234-1234-1234-123456789abc', 1, 1, 2, 'update', self.snapshot, replace(self.snapshot, address='9.9.9.9'), 'provider-record')
        self.assertCode('conflict', lambda: self.prepare('update', replace(p, record_id='foreign')))
        self.assertCode('conflict', lambda: self.prepare('update', replace(p, before=replace(self.snapshot, address='1.1.1.1'))))
        self.assertEqual(self.prepare('update', p)['plan']['record_id'], 'provider-record')

    def test_unowned_update_and_delete_rejected(self):
        p = Plan('owner', 'binding', '12345678-1234-1234-1234-123456789abc', 1, 1, 1, 'delete', self.snapshot, None, 'foreign')
        self.assertCode('conflict', lambda: self.prepare(plan=p))

    def test_delete_preserves_reservation_and_allows_explicit_recreate(self):
        self.success()
        p = Plan('owner', 'binding', '12345678-1234-1234-1234-123456789abc', 1, 1, 2, 'delete', self.snapshot, None, 'provider-record')
        r = self.prepare('delete', p); r = self.step(self.step(r, 'dispatching'), 'verifying')
        self.assertCode('validation', lambda: self.step(r, 'succeeded', proof='matched'))
        self.step(r, 'succeeded', proof='absent')
        self.assertCode('conflict', lambda: self.prepare('takeover', replace(self.plan, resource_id='87654321-1234-1234-1234-123456789abc', desired_revision=3)))
        self.assertEqual(self.prepare('recreate', replace(self.plan, desired_revision=3))['state'], 'prepared')

    def test_no_pruning_after_48_hours_including_unfinished(self):
        row = self.success(); self.now += 60 * 60 * 72
        self.assertEqual(self.prepare(), row)

    def test_transaction_rolls_back_partial_write_failure(self):
        original = self.store.write
        def fail(kind, key, value):
            if kind == 'operation': raise OSError('injected storage failure')
            original(kind, key, value)
        with patch.object(self.store, 'write', side_effect=fail):
            with self.assertRaises(OSError): self.prepare()
        with self.store.transaction():
            self.assertEqual(self.store.all('operation'), [])
            self.assertEqual(self.store.all('reservation'), [])

    def test_single_worker_lock(self):
        second = SqliteStateStore(self.path)
        with self.store.worker_lock():
            with self.assertRaises(NetworkError):
                with second.worker_lock(): pass
        with second.worker_lock(): pass

    def test_porkbun_ttl_policy(self):
        c = Connection('pb', 'owner', 'porkbun', 'user-account', 'vault:pb:1', status='ready')
        b = ZoneBinding('pb-binding', 'owner', 'pb', 'other.net', 'other.net', 'hosts.other.net', status='ready')
        self.ledger.put_connection('admin', c, 0); self.ledger.put_binding('admin', b, 0)
        p = replace(self.plan, binding_id=b.id, after=replace(self.snapshot, name='one.hosts.other.net'))
        self.assertCode('validation', lambda: self.prepare(plan=p))
        self.assertEqual(self.prepare(plan=replace(p, after=replace(p.after, ttl=600)))['state'], 'prepared')

    def test_no_secrets_or_http_in_preparation(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('HTTP forbidden')):
            row = self.prepare()
        self.assertEqual(row['credential_ref'], 'vault:credential:1')
        self.assertNotIn('secrets', json.dumps(row))

    def test_schema_mismatch_blocks_open(self):
        with self.store.transaction(): self.store.write('meta', 'schema', {'version': 99})
        self.assertCode('storage', lambda: SqliteStateStore(self.path))

    def test_missing_state_is_not_recreated(self):
        self.prepare(); self.path.unlink()
        self.assertCode('storage', lambda: SqliteStateStore(self.path))
        self.assertCode('storage', lambda: self.prepare())
        self.assertFalse(self.path.exists())

    def test_explicit_initialize_cannot_replace_existing_state(self):
        self.assertCode('conflict', lambda: SqliteStateStore(self.path, create=True))

    def test_process_exit_preserves_committed_dispatch(self):
        import subprocess, sys
        self.prepare()
        script = '''
import os, sys
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
class Auth:
    def authorize(self, *args): return True
l = OperationLedger(SqliteStateStore(sys.argv[1]), Auth())
l.transition('admin', 'owner', 'request', 1, 'dispatching')
os._exit(17)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)], check=False)
        self.assertEqual(result.returncode, 17)
        l = OperationLedger(SqliteStateStore(self.path), self.auth)
        self.assertEqual(l.inspect_operation('admin', 'owner', 'request')['state'], 'dispatching')

    def test_process_exit_rolls_back_uncommitted_state(self):
        import subprocess, sys
        script = '''
import os, sys
from zog.network_register.store import SqliteStateStore
s = SqliteStateStore(sys.argv[1])
with s.transaction():
    s.write('reservation', 'partial', {'name': 'incomplete'})
    os._exit(18)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)], check=False)
        self.assertEqual(result.returncode, 18)
        with self.store.transaction(): self.assertEqual(self.store.all('reservation'), [])


if __name__ == '__main__': unittest.main()
