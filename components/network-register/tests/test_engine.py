import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zog.network_register.contracts import NetworkError, Page
from zog.network_register.models import Connection, ZoneBinding, RecordSnapshot
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.engine import DnsEngine

RESOURCE = '12345678-1234-1234-1234-123456789abc'


class Auth:
    enabled = True
    def authorize(self, *args): return self.enabled


class Gate:
    denied = False
    def check(self, *args):
        if self.denied: raise NetworkError('permission')


class Provider:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.error = None
        self.read_error = None
        self.hidden = False
        self.apply_write = True
        self.on_list = None
        self.zone = dict(id='zone', name='example.com', account={'id': 'account'}, status='active')

    def get_zone(self, zone): return copy.deepcopy(self.zone)

    def list_records(self, zone, cursor=None):
        if self.on_list:
            callback, self.on_list = self.on_list, None; callback()
        if self.read_error: raise self.read_error
        return Page(tuple(copy.deepcopy(self.rows if not self.hidden else [])))

    def create_record(self, zone, record, *, marker, idempotency_key):
        self.calls.append('create')
        row = dict(id='record', name=record.name, type='A', content=record.address,
                   ttl=record.ttl, proxied=False, comment=marker)
        if self.apply_write: self.rows.append(row)
        if self.error: raise self.error
        return copy.deepcopy(row)

    def update_record(self, zone, record_id, record, *, marker, idempotency_key):
        self.calls.append('update')
        row = dict(id=record_id, name=record.name, type='A', content=record.address,
                   ttl=record.ttl, proxied=False, comment=marker)
        if self.apply_write: self.rows = [r if r['id'] != record_id else row for r in self.rows]
        if self.error: raise self.error
        return copy.deepcopy(row)

    def delete_record(self, zone, record_id, *, idempotency_key):
        self.calls.append('delete')
        if self.apply_write: self.rows = [r for r in self.rows if r['id'] != record_id]
        if self.error: raise self.error


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.store = SqliteStateStore(self.path, create=True)
        self.auth, self.gate, self.provider = Auth(), Gate(), Provider()
        self.now = 1000
        self.ledger = OperationLedger(self.store, self.auth, lambda: self.now)
        self.connection = Connection('connection', 'owner', 'cloudflare', 'account', 'vault:1', status='ready')
        self.binding = ZoneBinding('binding', 'owner', 'connection', 'zone', 'example.com', 'hosts.example.com', status='ready')
        self.ledger.put_connection('admin', self.connection, 0)
        self.ledger.put_binding('admin', self.binding, 0)
        self.engine = DnsEngine(self.ledger, self.gate, provider_factory=lambda _: self.provider, jitter=lambda: 1)
        self.desired = RecordSnapshot('one.hosts.example.com', '8.8.8.8', 300)

    def plan(self, desired=None, rev=1, delete=False):
        return self.engine.plan('admin', 'owner', 'binding', RESOURCE,
                                None if delete else desired or self.desired, rev, delete=delete)

    def prepare(self, request='create', plan=None):
        return self.ledger.prepare('admin', request, plan or self.plan())

    def apply(self, row): return self.engine.apply('admin', 'owner', row['request_id'], row['revision'])
    def inspect(self, request='create'): return self.ledger.inspect_operation('admin', 'owner', request)

    def assertCode(self, code, call):
        with self.assertRaises(NetworkError) as ctx: call()
        self.assertEqual(ctx.exception.code, code)

    def test_create_update_delete_and_unchanged_no_write(self):
        row = self.apply(self.prepare()); self.assertEqual(row['state'], 'succeeded')
        self.assertEqual(row['response_record_id'], 'record')
        self.assertIsNone(self.plan(rev=2))
        row = self.apply(self.prepare('update', self.plan(replace(self.desired, address='9.9.9.9'), 2)))
        self.assertEqual(row['state'], 'succeeded')
        self.assertEqual(self.provider.rows[0]['content'], '9.9.9.9')
        row = self.apply(self.prepare('delete', self.plan(rev=3, delete=True)))
        self.assertEqual(row['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create', 'update', 'delete'])
        self.assertEqual(self.apply(row), row)

    def test_manual_address_edit_blocks_even_when_it_matches_new_desired(self):
        self.apply(self.prepare())
        self.provider.rows[0]['content'] = '9.9.9.9'
        self.assertCode('conflict', lambda: self.plan(replace(self.desired, address='9.9.9.9'), 2))
        self.assertEqual(self.ledger.context('admin', 'owner', 'binding', RESOURCE)[1].status, 'blocked')
        self.assertEqual(self.provider.calls, ['create'])

    def test_manual_delete_is_not_recreated(self):
        self.apply(self.prepare()); self.provider.rows = []
        self.assertCode('conflict', lambda: self.plan(rev=2))
        self.assertEqual(self.provider.calls, ['create'])

    def test_manual_marker_ttl_proxy_edits_detected(self):
        self.apply(self.prepare())
        for field, value in [('comment', 'manual'), ('ttl', 600), ('proxied', True)]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.provider.rows)
                self.provider.rows[0][field] = value
                self.assertCode('conflict', lambda: self.plan(rev=2))
                self.provider.rows = original
                b = self.ledger.context('admin', 'owner', 'binding', RESOURCE)[1]
                self.ledger.put_binding('admin', replace(b, status='ready', revision=b.revision+1), b.revision)

    def test_foreign_identical_record_is_not_adopted(self):
        self.provider.rows = [dict(id='foreign', name=self.desired.name, type='A', content='8.8.8.8', ttl=300, proxied=False)]
        self.assertCode('conflict', self.plan)
        self.assertEqual(self.provider.calls, [])

    def test_unrelated_unknown_txt_and_wildcard_are_preserved(self):
        rows = [dict(id='txt', name=self.desired.name, type='TXT', content='hello'),
                dict(id='wild', name='*.example.com', type='A', content='1.1.1.1'),
                dict(id='future', name='other.example.com', type='FUTURE', content='opaque')]
        self.provider.rows = copy.deepcopy(rows)
        self.assertEqual(self.apply(self.prepare())['state'], 'succeeded')
        self.assertEqual(self.provider.rows[:3], rows)

    def test_parent_delegation_and_cname_block(self):
        self.provider.rows = [dict(id='ns', name='hosts.example.com', type='NS', content='ns.other.net')]
        self.assertCode('conflict', self.plan)
        self.assertEqual(self.provider.calls, [])

    def test_preflight_detects_record_created_after_plan(self):
        row = self.prepare()
        self.provider.rows = [dict(id='cname', name=self.desired.name, type='CNAME', content='other.example.com')]
        self.assertEqual(self.apply(row)['state'], 'conflict')
        self.assertEqual(self.provider.calls, [])

    def test_preflight_prevents_deleting_manually_edited_record(self):
        self.apply(self.prepare())
        row = self.prepare('delete', self.plan(rev=2, delete=True))
        self.provider.rows[0]['content'] = '9.9.9.9'
        self.assertEqual(self.apply(row)['state'], 'conflict')
        self.assertEqual(self.provider.calls, ['create'])

    def test_lost_create_response_is_verified_without_replay(self):
        self.provider.error = NetworkError('uncertain')
        self.assertEqual(self.apply(self.prepare())['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create'])

    def test_empty_listing_after_unknown_create_becomes_uncertain(self):
        row = self.prepare(); self.provider.apply_write = False; self.provider.error = NetworkError('uncertain')
        row = self.apply(row)
        for _ in range(4):
            self.now += 60; row = self.apply(row)
        self.assertEqual(row['state'], 'uncertain')
        self.assertEqual(row['read_attempts'], 5)
        self.assertEqual(self.apply(row), row)
        self.assertEqual(self.provider.calls, ['create'])

    def test_delayed_visibility_recovers_on_due_read(self):
        row = self.prepare()
        original = self.provider.create_record
        def hidden(*args, **kw):
            result = original(*args, **kw); self.provider.hidden = True; return result
        self.provider.create_record = hidden
        row = self.apply(row); self.assertEqual(row['state'], 'verifying')
        self.assertEqual(self.apply(row), row)
        self.now += 1; self.provider.hidden = False
        self.assertEqual(self.apply(row)['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create'])

    def test_lost_update_and_delete_responses(self):
        self.apply(self.prepare()); self.provider.error = NetworkError('uncertain')
        row = self.apply(self.prepare('update', self.plan(replace(self.desired, address='9.9.9.9'), 2)))
        self.assertEqual(row['state'], 'succeeded')
        row = self.apply(self.prepare('delete', self.plan(rev=3, delete=True)))
        self.assertEqual(row['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create', 'update', 'delete'])

    def test_missing_access_never_proves_delete(self):
        self.apply(self.prepare())
        row = self.prepare('delete', self.plan(rev=2, delete=True))
        original = self.provider.delete_record
        def revoke(*args, **kw):
            original(*args, **kw); self.provider.read_error = NetworkError('not-found')
        self.provider.delete_record = revoke
        self.assertEqual(self.apply(row)['state'], 'uncertain')

    def test_post_write_divergence_is_conflict(self):
        original = self.provider.create_record
        def edit(*args, **kw):
            result = original(*args, **kw); self.provider.rows[0]['content'] = '9.9.9.9'; return result
        self.provider.create_record = edit
        self.assertEqual(self.apply(self.prepare())['state'], 'conflict')

    def test_returned_id_is_cross_checked(self):
        original = self.provider.create_record
        def wrong(*args, **kw):
            result = original(*args, **kw); result['id'] = 'different'; return result
        self.provider.create_record = wrong
        self.assertEqual(self.apply(self.prepare())['state'], 'conflict')

    def test_ambiguous_matching_markers_are_not_accepted(self):
        original = self.provider.create_record
        def duplicate(*args, **kw):
            result = original(*args, **kw); self.provider.rows.append(dict(result, id='second')); return result
        self.provider.create_record = duplicate
        self.assertEqual(self.apply(self.prepare())['state'], 'conflict')

    def test_storage_failure_after_provider_success_recovers_by_read(self):
        row = self.prepare(); original = self.ledger.transition
        def fail(*args, **kw):
            if args[4] == 'succeeded': raise OSError('disk unavailable')
            return original(*args, **kw)
        with patch.object(self.ledger, 'transition', side_effect=fail):
            with self.assertRaises(OSError): self.apply(row)
        self.assertEqual(self.inspect()['state'], 'verifying')
        self.assertEqual(self.apply(self.inspect())['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create'])

    def test_unexpected_exception_leaves_dispatch_marker_and_never_replays(self):
        class Crash(BaseException): pass
        self.provider.error = Crash()
        with self.assertRaises(Crash): self.apply(self.prepare())
        self.assertEqual(self.inspect()['state'], 'dispatching')
        self.assertEqual(self.apply(self.inspect())['state'], 'succeeded')
        self.assertEqual(self.provider.calls, ['create'])

    def test_crash_after_dispatch_before_http_is_uncertain_not_replayed(self):
        import subprocess, sys
        self.prepare()
        script = '''
import os,sys
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.engine import DnsEngine
from zog.network_register.contracts import Page
class Auth:
    def authorize(self,*a):return True
class Gate:
    def check(self,*a):pass
class Provider:
    def get_zone(self,*a):return dict(id='zone',name='example.com',account={'id':'account'},status='active')
    def list_records(self,*a):return Page(())
    def create_record(self,*a,**kw):os._exit(19)
l=OperationLedger(SqliteStateStore(sys.argv[1]),Auth())
DnsEngine(l,Gate(),provider_factory=lambda c:Provider()).apply('admin','owner','create',1)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.path)], check=False)
        self.assertEqual(result.returncode, 19)
        self.assertEqual(self.inspect()['state'], 'dispatching')
        row = self.apply(self.inspect())
        self.assertEqual(row['state'], 'verifying')
        self.assertEqual(self.provider.calls, [])

    def test_authorization_changed_during_reads_stops_dispatch(self):
        row = self.prepare(); self.provider.on_list = lambda: setattr(self.auth, 'enabled', False)
        self.assertCode('permission', lambda: self.apply(row))
        self.assertEqual(self.provider.calls, [])

    def test_gate_failure_stops_planning_and_false_is_not_success(self):
        self.gate.denied = True
        self.assertCode('permission', self.plan)
        self.gate.check = lambda *args: False
        self.assertCode('permission', self.plan)

    def test_revocation_and_rotation_block_dispatch(self):
        row = self.prepare()
        self.ledger.put_connection('admin', replace(self.connection, credential_ref='vault:2', revision=2), 1)
        self.assertCode('permission', lambda: self.apply(row))
        self.assertEqual(self.provider.calls, [])

    def test_stale_revision_and_competing_worker(self):
        row = self.prepare()
        self.assertCode('conflict', lambda: self.engine.apply('admin', 'owner', 'create', 0))
        with self.store.worker_lock(): self.assertCode('conflict', lambda: self.apply(row))
        self.assertEqual(self.provider.calls, [])

    def test_retry_after_is_durable_and_no_mutation_replay(self):
        row = self.prepare(); self.provider.apply_write = False
        self.provider.error = NetworkError('rate-limit', retry_after=120)
        row = self.apply(row)
        self.assertEqual(row['next_check_at'], 1120)
        self.now = 1119; self.assertEqual(self.apply(row), row)
        self.now = 1120; row = self.apply(row)
        self.assertEqual(row['state'], 'verifying')
        self.assertEqual(self.provider.calls, ['create'])

    def test_wrong_zone_account_and_inactive_zone_block(self):
        self.provider.zone['account']['id'] = 'other'
        self.assertCode('conflict', self.plan)
        self.assertEqual(self.provider.calls, [])

    def test_predispatch_read_retry_is_bounded_and_honors_due_time(self):
        row = self.prepare(); self.provider.read_error = NetworkError('rate-limit', retry_after=120)
        row = self.apply(row)
        self.assertEqual(row['state'], 'prepared')
        self.assertEqual(row['next_check_at'], 1120)
        self.assertEqual(self.apply(row), row)
        for _ in range(4):
            self.now += 120; row = self.apply(row)
        self.assertEqual(row['state'], 'failed')
        self.assertEqual(row['preflight_attempts'], 5)
        self.assertEqual(self.provider.calls, [])

    def test_two_page_inventory_and_duplicate_ids(self):
        original = self.provider.list_records
        txt = dict(id='txt', name='other.example.com', type='TXT')
        def pages(zone, cursor=None):
            if cursor is None: return Page((txt,), 'second')
            return original(zone)
        self.provider.list_records = pages
        self.assertEqual(self.apply(self.prepare())['state'], 'succeeded')
        self.provider.list_records = lambda zone, cursor=None: Page((txt,), 'second' if cursor is None else None)
        self.assertCode('conflict', lambda: self.plan(rev=2))

    def test_budget_survives_reopen_after_more_than_48_hours(self):
        row = self.prepare(); self.provider.apply_write = False; self.provider.error = NetworkError('uncertain')
        row = self.apply(row)
        self.ledger = OperationLedger(SqliteStateStore(self.path), self.auth, lambda: self.now)
        self.engine = DnsEngine(self.ledger, self.gate, provider_factory=lambda _: self.provider, jitter=lambda: 1)
        self.now += 72 * 3600
        row = self.apply(self.inspect())
        self.assertEqual(row['read_attempts'], 2)
        self.assertEqual(self.provider.calls, ['create'])

    def test_gate_changes_after_plan_prevent_write(self):
        row = self.prepare(); self.gate.denied = True
        self.assertCode('permission', lambda: self.apply(row))
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.inspect()['state'], 'prepared')

    def test_superseded_desired_revision_blocks_dispatch(self):
        row = self.prepare()
        def latest(connection, binding, resource, desired, action, desired_revision):
            if action != 'inspect' and desired_revision != 2: raise NetworkError('conflict')
        self.gate.check = latest
        self.assertCode('conflict', lambda: self.apply(row))
        self.assertEqual(self.provider.calls, [])

    def test_inactive_zone_cannot_be_planned(self):
        self.provider.zone['status'] = 'pending'
        self.assertCode('conflict', self.plan)
        self.assertEqual(self.provider.calls, [])

    def test_real_adapter_roundtrip_with_injected_http_and_secrets(self):
        import json
        from urllib.parse import urlsplit
        from zog.network_register.cloudflare import CloudflareDns
        account, zone, record_id = 'a'*32, 'b'*32, 'c'*32
        # Separate durable binding to a syntactically valid Cloudflare account.
        c = Connection('http', 'owner', 'cloudflare', account, 'vault:http', status='ready')
        b = ZoneBinding('http', 'owner', 'http', zone, 'other.net', 'hosts.other.net', status='ready')
        self.ledger.put_connection('admin', c, 0); self.ledger.put_binding('admin', b, 0)
        class Secrets:
            def resolve(self, *args): return {'api_token': 'fixture-secret'}
        class Http:
            def __init__(self): self.rows = []; self.writes = []
            def request(self, method, url, *, body, **kw):
                path = urlsplit(url).path
                if method == 'GET' and path.endswith('/zones/'+zone):
                    result = dict(id=zone, name='other.net', account={'id':account}, status='active')
                    payload = dict(success=True, result=result)
                elif method == 'GET':
                    payload = dict(success=True, result=copy.deepcopy(self.rows), result_info={'page':1,'total_pages':1})
                else:
                    self.writes.append(method)
                    if method == 'POST': self.rows = [dict(json.loads(body), id=record_id)]
                    elif method == 'PATCH': self.rows = [dict(json.loads(body), id=record_id)]
                    elif method == 'DELETE': self.rows = []
                    payload = dict(success=True, result=self.rows[0] if self.rows else {'id':record_id})
                return 200, {}, json.dumps(payload).encode()
        http = Http(); engine = DnsEngine(self.ledger, self.gate, Secrets(), http)
        snapshot = replace(self.desired, name='one.hosts.other.net')
        for number, desired in enumerate((snapshot, replace(snapshot, address='9.9.9.9'), None), 1):
            p = engine.plan('admin','owner','http',RESOURCE,desired,number,delete=desired is None)
            row = self.ledger.prepare('admin','http-'+str(number),p)
            result = engine.apply('admin','owner',row['request_id'],row['revision'])
            self.assertEqual(result['state'],'succeeded')
        self.assertEqual(http.writes,['POST','PATCH','DELETE'])


if __name__ == '__main__': unittest.main()
