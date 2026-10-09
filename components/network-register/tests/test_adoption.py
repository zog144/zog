import copy
from dataclasses import asdict, replace
import unittest
from unittest.mock import patch
import test_engine
RESOURCE=test_engine.RESOURCE
from zog.network_register.adoption import RecordAdoption
from zog.network_register.contracts import NetworkError
from zog.network_register.ledger import digest


class AdoptionTests(unittest.TestCase):
    setUp=test_engine.EngineTests.setUp
    plan=test_engine.EngineTests.plan
    prepare=test_engine.EngineTests.prepare
    apply=test_engine.EngineTests.apply
    def item(self, *, absent=False):
        return dict(resource_id=RESOURCE,name=self.desired.name,record_id=None if absent else 'legacy-record',
                    snapshot=None if absent else asdict(replace(self.desired,ttl=60)),
                    marker=None if absent else 'Zog network-register owner '+'a'*64,desired_revision=1)
    def seed(self):
        item=self.item();snap=item['snapshot']
        self.provider.rows=[dict(id=item['record_id'],name=snap['name'],type='A',content=snap['address'],ttl=snap['ttl'],proxied=False,comment=item['marker'])]
    def adopt(self, items=None, request='review'):
        return RecordAdoption(self.engine).adopt('admin','owner','binding',request,items or [self.item()],connection_revision=1,binding_revision=1)
    def test_adoption_no_provider_write_then_update_exact_id(self):
        self.seed();receipt=self.adopt();self.assertEqual(receipt['state'],'adopted');self.assertFalse(self.provider.calls)
        op=self.apply(self.prepare('normalize'))
        self.assertEqual(op['state'],'succeeded');self.assertEqual(self.provider.calls,['update'])
        self.assertEqual(self.provider.rows[0]['id'],'legacy-record')
        self.assertEqual(self.provider.rows[0]['ttl'],300)
    def test_duplicate_adoption_idempotent_after_restart(self):
        self.seed();first=self.adopt();self.assertEqual(self.adopt(),first);self.assertFalse(self.provider.calls)
    def test_same_request_different_payload_refused(self):
        self.seed();self.adopt();item=self.item();item['desired_revision']=2
        with self.assertRaises(NetworkError):self.adopt([item])
    def test_absent_reservation_import_then_create(self):
        self.adopt([self.item(absent=True)])
        self.assertEqual(self.apply(self.prepare())['state'],'succeeded');self.assertEqual(self.provider.calls,['create'])
    def test_absent_with_remote_record_refused(self):
        self.seed()
        with self.assertRaises(NetworkError):self.adopt([self.item(absent=True)])
    def test_unknown_marker_refused(self):
        self.seed();item=self.item();item['marker']='foreign comment'
        with self.assertRaises(ValueError):self.adopt([item])
    def test_id_content_ttl_proxy_marker_drift_refused(self):
        for key,value in [('id','different'),('content','9.9.9.9'),('ttl',600),('proxied',True),('comment','changed')]:
            with self.subTest(key=key):
                self.seed();self.provider.rows[0][key]=value
                with self.assertRaises(NetworkError):self.adopt()
    def test_duplicate_name_and_alias_conflicts(self):
        for kind in ('A','CNAME','NS','DNAME'):
            with self.subTest(kind=kind):
                self.seed();self.provider.rows.append(dict(id='extra',type=kind,name=self.desired.name))
                with self.assertRaises(NetworkError):self.adopt()
    def test_ancestor_dname_conflict(self):
        for name in ('hosts.example.com','example.com'):
            self.seed();self.provider.rows.append(dict(id='alias',type='DNAME',name=name))
            with self.assertRaises(NetworkError):self.adopt()
    def test_different_scope_and_duplicate_resource_refused(self):
        self.seed()
        with self.assertRaises(NetworkError):self.adopt([self.item(),self.item()])
        item=self.item();item['name']='outside.other.com'
        with self.assertRaises(NetworkError):self.adopt([item])
    def test_revocation_during_read(self):
        self.seed();self.provider.on_list=lambda:setattr(self.auth,'enabled',False)
        with self.assertRaises(NetworkError):self.adopt()
        with self.store.transaction():self.assertFalse(self.store.all('record'))
    def test_gate_denied(self):
        self.seed();self.gate.denied=True
        with self.assertRaises(NetworkError):self.adopt()
    def test_atomic_rollback_on_receipt_failure(self):
        self.seed();original=self.store.write
        def fail(kind,*args):
            if kind=='adoption':raise OSError('disk full')
            return original(kind,*args)
        with patch.object(self.store,'write',side_effect=fail):
            with self.assertRaises(OSError):self.adopt()
        with self.store.transaction():
            self.assertFalse(self.store.all('record'));self.assertFalse(self.store.all('reservation'))
        self.adopt()
    def test_new_request_cannot_replace_owned_record(self):
        self.seed();self.adopt()
        with self.assertRaises(NetworkError):self.adopt(request='another')
    def test_batch_failure_adopts_nothing(self):
        self.seed();second=copy.deepcopy(self.item());second['resource_id']='22345678-1234-1234-1234-123456789abc';second['name']='two.hosts.example.com';second['snapshot']['name']=second['name'];second['record_id']='missing'
        with self.assertRaises(NetworkError):self.adopt([self.item(),second])
        with self.store.transaction():self.assertFalse(self.store.all('record'))
    def test_explicit_recheck_never_replays_dispatch(self):
        self.seed();self.adopt();op=self.prepare('lost')
        self.provider.error=NetworkError('uncertain')
        self.provider.hidden=True
        # Force a durable dispatched state as a crash would leave it.
        op=self.ledger.transition('admin','owner','lost',op['revision'],'dispatching')
        op=self.ledger.transition('admin','owner','lost',op['revision'],'uncertain')
        checked=self.engine.recheck('admin','owner','lost',op['revision'])
        self.assertEqual(checked['state'],'verifying');self.assertEqual(checked['read_attempts'],0)
        self.provider.hidden=False;self.apply(checked)
        self.assertFalse(self.provider.calls)
    def test_recheck_cas_and_authorization(self):
        self.seed();self.adopt();op=self.prepare('lost')
        op=self.ledger.transition('admin','owner','lost',op['revision'],'dispatching')
        op=self.ledger.transition('admin','owner','lost',op['revision'],'uncertain')
        with self.assertRaises(NetworkError):self.engine.recheck('admin','owner','lost',op['revision']-1)
        self.auth.enabled=False
        with self.assertRaises(NetworkError):self.engine.recheck('admin','owner','lost',op['revision'])
    def test_recheck_refuses_prepared_operation(self):
        self.seed();self.adopt();op=self.prepare('prepared')
        with self.assertRaises(NetworkError):self.engine.recheck('admin','owner','prepared',op['revision'])
