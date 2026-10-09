import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from zog.network_register.contracts import NetworkError, ProviderWriteWarning
from zog.network_register.models import Connection, ZoneBinding, RecordSnapshot
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.engine import DnsEngine
from zog.network_register.porkbun_dns import PorkbunDns, PorkbunTransport, BASE

RESOURCE = '12345678-1234-1234-1234-123456789abc'
MARKER = 'zog-operation:' + RESOURCE
KEY = 'a' * 64


class Secrets:
    def resolve(self, *args): return {'api_key':'fixture-key', 'secret_key':'fixture-secret'}


class Policy:
    def authorize(self, *args): return True
    def check(self, *args): pass


class Http:
    """Stateful endpoint fixture with actual Porkbun response shapes."""
    def __init__(self):
        self.records = []
        self.calls = []
        self.counter = 100
        self.authority = True
        self.cloudflare = 'disabled'
        self.error = None
        self.warning = False
        self.lost = False
        self.apply_write = True
        self.ttl = None
        self.cache = {}

    def request(self, method, url, *, body, headers, **kwargs):
        path = urlsplit(url).path.removeprefix('/api/json/v3')
        self.calls.append((method,path,copy.deepcopy(headers),body))
        if self.error:
            return self.error
        if method == 'GET':
            if path == '/domain/listAll':
                payload = dict(status='SUCCESS',domains=[{'domain':'example.com','apiAccess':'yes'}])
            elif path == '/dns/preflight/example.com':
                payload = dict(status='SUCCESS',domain='example.com',checks=[{'id':'nameservers-ours','ok':self.authority}])
            elif path.startswith('/dns/retrieve/example.com'):
                rows = self.records
                if path != '/dns/retrieve/example.com': rows = [r for r in rows if r['id'] == path.rsplit('/',1)[1]]
                payload = dict(status='SUCCESS',cloudflare=self.cloudflare,records=copy.deepcopy(rows))
            else: raise AssertionError(path)
        else:
            assert path.startswith(('/dns/create/', '/dns/edit/', '/dns/delete/'))
            key = headers['Idempotency-Key']
            if key in self.cache:
                old_path,old_body,payload = self.cache[key]
                assert (path,body) == (old_path,old_body)
                return 200,{},json.dumps(payload).encode()
            data = json.loads(body)
            payload = {'status':'SUCCESS'}
            if path.startswith('/dns/create/'):
                self.counter += 1; rid = str(self.counter); payload['id'] = rid
                if self.apply_write: self.records.append(self.record(rid,data))
            elif path.startswith('/dns/edit/'):
                rid = path.rsplit('/',1)[1]
                if self.apply_write: self.records = [self.record(rid,data) if r['id']==rid else r for r in self.records]
            else:
                if self.apply_write: self.records = [r for r in self.records if r['id']!=path.rsplit('/',1)[1]]
            if self.warning: payload['warnings'] = ['fixture-secret: another provider is authoritative']
            self.cache[key] = (path,body,payload)
            if self.lost: raise TimeoutError('fixture-secret')
        return 200,{},json.dumps(payload).encode()

    def record(self,rid,data):
        return dict(id=rid,name=data['name']+'.example.com',type=data['type'],content=data['content'],
                    ttl=str(self.ttl or data['ttl']),notes=data['notes'],prio=None)

    def writes(self): return [c for c in self.calls if c[0]=='POST']


class PorkbunDnsTests(unittest.TestCase):
    def setUp(self):
        self.http,self.policy = Http(),Policy()
        self.connection = Connection('pb','owner','porkbun','saved-account','vault:pb:1',status='ready')
        self.client = PorkbunDns(self.connection,Secrets(),self.http)
        self.snapshot = RecordSnapshot('one.hosts.example.com','8.8.8.8',600)
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.ledger = OperationLedger(SqliteStateStore(Path(self.temp.name)/'state.sqlite',create=True),self.policy,lambda:self.now)
        self.ledger.put_connection('admin',self.connection,0)
        self.binding = ZoneBinding('binding','owner','pb','example.com','example.com','hosts.example.com',status='ready')
        self.ledger.put_binding('admin',self.binding,0)
        self.engine = DnsEngine(self.ledger,self.policy,Secrets(),self.http,jitter=lambda:1)

    def plan(self,revision=1,desired=None,delete=False):
        return self.engine.plan('admin','owner','binding',RESOURCE,None if delete else desired or self.snapshot,revision,delete=delete)

    def prepare(self,request='create',plan=None): return self.ledger.prepare('admin',request,plan or self.plan())
    def apply(self,row): return self.engine.apply('admin','owner',row['request_id'],row['revision'])

    def assertCode(self,code,call):
        with self.assertRaises(NetworkError) as ctx:call()
        self.assertEqual(ctx.exception.code,code)
        self.assertNotIn('fixture-secret',str(ctx.exception))
        self.assertNotIn('fixture-key',str(ctx.exception))
        return ctx.exception

    def test_full_engine_create_noop_update_delete(self):
        row=self.apply(self.prepare());self.assertEqual(row['state'],'succeeded')
        self.assertEqual(row['record_id'],'101');self.assertIsNone(self.plan(2))
        row=self.apply(self.prepare('update',self.plan(2,replace(self.snapshot,address='9.9.9.9'))))
        self.assertEqual(row['state'],'succeeded')
        row=self.apply(self.prepare('delete',self.plan(3,delete=True)))
        self.assertEqual(row['state'],'succeeded');self.assertEqual(self.http.records,[])
        self.assertEqual([w[1] for w in self.http.writes()],['/dns/create/example.com','/dns/edit/example.com/101','/dns/delete/example.com/101'])

    def test_header_auth_relative_name_notes_and_stable_idempotency_body(self):
        for _ in range(2):self.client.create_record('example.com',self.snapshot,marker=MARKER,idempotency_key=KEY)
        first,second=self.http.writes()
        self.assertEqual(first,second);self.assertEqual(len(self.http.records),1)
        payload=json.loads(first[3]);self.assertEqual(payload,dict(name='one.hosts',type='A',content='8.8.8.8',ttl=600,notes=MARKER))
        self.assertEqual(first[2]['Idempotency-Key'],KEY)
        self.assertEqual(first[2]['X-Secret-API-Key'],'fixture-secret')
        self.assertNotIn(b'fixture',first[3]);self.assertNotIn('fixture',first[1])

    def test_record_translation_numeric_id_ttl_and_notes(self):
        self.client.create_record('example.com',self.snapshot,marker=MARKER,idempotency_key=KEY)
        self.http.records[0]['id']=101
        row=self.client.list_records('example.com').items[0]
        self.assertEqual((row['id'],row['ttl'],row['comment'],row['proxied']),('101',600,MARKER,False))

    def test_unrelated_service_names_wildcards_and_unknown_types_preserved(self):
        unrelated=[dict(id='1',name='_acme-challenge.example.com',type='TXT',content='token',ttl='600',notes=None),
                   dict(id='2',name='*.example.com',type='FUTURE',content='opaque',ttl='600',notes=None)]
        self.http.records=copy.deepcopy(unrelated)
        self.assertEqual(self.apply(self.prepare())['state'],'succeeded')
        self.assertEqual(self.http.records[:2],unrelated)

    def test_apex_wildcard_outside_domain_and_low_ttl_rejected(self):
        for snapshot in (replace(self.snapshot,name='example.com'),replace(self.snapshot,name='one.evil-example.com'),replace(self.snapshot,ttl=300)):
            self.assertCode('validation',lambda:self.client.create_record('example.com',snapshot,marker=MARKER,idempotency_key=KEY))
        with self.assertRaises(ValueError):replace(self.snapshot,name='*.example.com')
        self.assertEqual(self.http.writes(),[])

    def test_zone_identity_is_domain_and_access_not_purchase(self):
        z=self.client.get_zone('example.com')
        self.assertEqual(z['id'],'example.com')
        self.assertEqual(self.client.list_zones().items[0]['status'],'discovered')
        self.assertIsNone(self.client.inspect_connection()['write_a'].authorized)

    def test_wrong_delegation_blocks_before_write(self):
        self.http.authority=False;self.assertCode('conflict',self.plan)
        self.assertEqual(self.http.writes(),[])

    def test_managed_backend_enabled_requires_porkbun_authority(self):
        self.http.cloudflare='enabled'
        self.assertEqual(self.apply(self.prepare())['state'],'succeeded')
        self.http.authority=False
        self.assertCode('conflict',self.plan)
        self.assertEqual(len(self.http.writes()),1)

    def test_accepted_warning_recovery_is_read_only(self):
        self.http.warning=True;row=self.apply(self.prepare())
        self.assertEqual(row['state'],'conflict')
        self.http.cloudflare='enabled'
        recovered=self.engine.recover_accepted('admin','owner',row['request_id'],row['revision'])
        self.assertEqual(recovered['state'],'succeeded');self.assertEqual(len(self.http.writes()),1)
        self.assertIsNone(self.plan())

    def test_accepted_warning_recovery_rejects_drift_and_foreign_authority(self):
        self.http.warning=True;row=self.apply(self.prepare())
        self.http.records[0]['content']='9.9.9.9'
        self.assertCode('conflict',lambda:self.engine.recover_accepted('admin','owner',row['request_id'],row['revision']))
        self.http.records[0]['content']='8.8.8.8';self.http.authority=False
        self.assertCode('conflict',lambda:self.engine.recover_accepted('admin','owner',row['request_id'],row['revision']))
        self.assertEqual(len(self.http.writes()),1)

    def test_missing_authority_check_is_not_ready(self):
        self.http.error=(200,{},json.dumps(dict(status='SUCCESS',domain='example.com',checks=[])).encode())
        self.assertCode('conflict',lambda:self.client.get_zone('example.com'))

    def test_write_warning_is_durable_conflict_even_if_record_matches(self):
        row=self.prepare();self.http.warning=True;row=self.apply(row)
        self.assertEqual(row['state'],'conflict');self.assertEqual(row['response_record_id'],'101')
        self.assertEqual(len(self.http.records),1)
        self.assertNotIn('fixture-secret',json.dumps(row))
        self.assertEqual(self.apply(row),row);self.assertEqual(len(self.http.writes()),1)

    def test_update_warning_remains_conflict(self):
        self.apply(self.prepare());row=self.prepare('update',self.plan(2,replace(self.snapshot,address='9.9.9.9')))
        self.http.warning=True;self.assertEqual(self.apply(row)['state'],'conflict')

    def test_delete_warning_remains_conflict(self):
        self.apply(self.prepare());row=self.prepare('delete',self.plan(2,delete=True))
        self.http.warning=True;row=self.apply(row)
        self.assertEqual(row['state'],'conflict');self.assertEqual(self.http.records,[])

    def test_lost_create_response_verified_without_replay(self):
        row=self.prepare();self.http.lost=True
        self.assertEqual(self.apply(row)['state'],'succeeded');self.assertEqual(len(self.http.writes()),1)

    def test_lost_update_and_delete_responses_verified(self):
        self.apply(self.prepare());self.http.lost=True
        row=self.apply(self.prepare('update',self.plan(2,replace(self.snapshot,address='9.9.9.9'))))
        self.assertEqual(row['state'],'succeeded')
        row=self.apply(self.prepare('delete',self.plan(3,delete=True)))
        self.assertEqual(row['state'],'succeeded');self.assertEqual(len(self.http.writes()),3)

    def test_unknown_create_no_replay_after_24_and_48_hours(self):
        row=self.prepare();key=row['step_key'];self.http.apply_write=False;self.http.lost=True
        row=self.apply(row);self.now+=25*3600;row=self.apply(row);self.now+=24*3600
        for _ in range(3):self.now+=60;row=self.apply(row)
        self.assertEqual(row['state'],'uncertain');self.assertEqual(len(self.http.writes()),1)
        self.assertEqual(self.http.writes()[0][2]['Idempotency-Key'],key)

    def test_manual_deletion_never_repaired(self):
        self.apply(self.prepare());self.http.records=[]
        self.assertCode('conflict',lambda:self.plan(2));self.assertEqual(len(self.http.writes()),1)

    def test_manual_notes_edit_is_not_repaired(self):
        self.apply(self.prepare());self.http.records[0]['notes']='manual'
        self.assertCode('conflict',lambda:self.plan(2));self.assertEqual(len(self.http.writes()),1)

    def test_preflight_rate_limit_retains_intent_and_due_time(self):
        row=self.prepare();self.http.error=(429,{'Retry-After':'120'},b'')
        row=self.apply(row);self.assertEqual(row['state'],'prepared')
        self.assertEqual(row['next_check_at'],1120);self.assertEqual(self.http.writes(),[])

    def test_missing_create_id_does_not_allow_replay(self):
        row=self.prepare()
        original=self.http.request
        def lost_id(method,url,**kw):
            status,headers,raw=original(method,url,**kw)
            if method=='POST': raw=b'{"status":"SUCCESS"}'
            return status,headers,raw
        self.http.request=lost_id
        self.assertEqual(self.apply(row)['state'],'succeeded')
        self.assertEqual(len(self.http.writes()),1)

    def test_account_ttl_clamp_is_detected_not_silently_accepted(self):
        row=self.prepare();self.http.ttl=900
        self.assertEqual(self.apply(row)['state'],'conflict')

    def test_http200_error_is_not_empty_inventory(self):
        self.http.error=(200,{},json.dumps(dict(status='ERROR',code='DOMAIN_NOT_ALLOWED',message='fixture-secret')).encode())
        self.assertCode('permission',lambda:self.client.list_records('example.com'))

    def test_unknown_errors_redacted_and_mutation_uncertain(self):
        self.http.error=(400,{},json.dumps(dict(status='ERROR',code='fixture-secret',message='fixture-secret')).encode())
        e=self.assertCode('uncertain',lambda:self.client.delete_record('example.com','101',idempotency_key=KEY))
        self.assertIsNone(e.provider_code)

    def test_rate_limit_and_server_error_categories(self):
        self.http.error=(429,{'Retry-After':'180'},b'fixture-secret')
        e=self.assertCode('rate-limit',lambda:self.client.list_records('example.com'));self.assertEqual(e.retry_after,180)
        self.http.error=(503,{},b'fixture-secret')
        self.assertCode('transient',lambda:self.client.list_records('example.com'))
        self.assertCode('uncertain',lambda:self.client.delete_record('example.com','101',idempotency_key=KEY))

    def test_empty_and_duplicate_record_lists(self):
        self.assertEqual(self.client.list_records('example.com').items,())
        row=dict(id='1',name='one.example.com',type='A',content='8.8.8.8',ttl='600')
        self.http.records=[row,row]
        self.assertCode('validation',lambda:self.client.list_records('example.com'))

    def test_wrong_record_lookup_and_bad_ids(self):
        self.assertCode('not-found',lambda:self.client.get_record('example.com','101'))
        self.assertCode('validation',lambda:self.client.delete_record('example.com','../other',idempotency_key=KEY))
        self.assertEqual(self.http.writes(),[])

    def test_no_registrar_funding_or_bulk_route(self):
        for path in ('/account/topup','/domain/create/example.com','/dns/editByNameType/example.com/A/one','/dns/deleteByNameType/example.com/A/one','/domain/updateNs/example.com'):
            self.assertCode('unsupported',lambda:self.client._request('POST',path,{},KEY))
        self.assertEqual(self.http.calls,[])

    def test_fixed_host_and_invalid_key_shapes(self):
        self.assertCode('validation',lambda:PorkbunTransport().request('GET','https://evil.example/',headers={},body=None,timeout=1))
        self.client.secrets.resolve=lambda *args:{'api_key':'fixture-key'}
        self.assertCode('authentication',lambda:self.client.list_records('example.com'))
        self.assertEqual(self.http.calls,[])

    def test_domain_pagination_and_invalid_inventory(self):
        rows=[{'domain':f'd{i}.example','apiAccess':'yes'} for i in range(1000)]
        self.http.error=(200,{},json.dumps(dict(status='SUCCESS',domains=rows)).encode())
        self.assertEqual(self.client.list_zones().next_cursor,'1000')
        rows[1]=rows[0]
        self.http.error=(200,{},json.dumps(dict(status='SUCCESS',domains=rows)).encode())
        self.assertCode('validation',lambda:self.client.list_zones())

    def test_missing_records_does_not_prove_absence(self):
        self.http.error=(200,{},b'{"status":"SUCCESS","cloudflare":"disabled"}')
        self.assertCode('validation',lambda:self.client.list_records('example.com'))


if __name__=='__main__':unittest.main()
