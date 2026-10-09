import unittest
from dataclasses import replace
from unittest.mock import patch
import test_engine as f
from zog.network_register.reservations import NameReservations
from zog.network_register.ledger import digest
from zog.network_register.contracts import NetworkError

class ReservationTests(unittest.TestCase):
    setUp=f.EngineTests.setUp
    plan=f.EngineTests.plan
    prepare=f.EngineTests.prepare
    apply=f.EngineTests.apply
    assertCode=f.EngineTests.assertCode
    def change(self, action='reserve', request='reserve', resource=f.RESOURCE):
        return NameReservations(self.engine).change('admin','owner','binding',resource,
            self.desired.name,action,request,connection_revision=1,binding_revision=1)
    def unpublished(self):
        self.apply(self.prepare())
        self.apply(self.prepare('delete',self.plan(rev=2,delete=True)))
    def test_read_only_idempotent_authorized(self):
        self.assertEqual(self.change(),self.change())
        self.assertEqual(self.provider.calls,[])
        self.assertCode('conflict',lambda:self.change(request='other'))
        self.assertCode('conflict',lambda:self.change('release'))
        self.auth.enabled=False
        self.assertCode('permission',self.change)
    def test_release_reuse_fences_old_plan_retains_history(self):
        self.unpublished();stale=self.plan(rev=3)
        receipt=self.change('release','release')
        self.assertCode('conflict',lambda:self.prepare('stale',stale))
        new=self.change(request='reuse')
        self.assertGreater(new['revision_floor'],3)
        self.assertCode('conflict',lambda:self.prepare('stale-again',stale))
        self.apply(self.prepare('new',self.plan(rev=new['revision_floor'])))
        self.assertEqual(receipt,self.change('release','release'))
        with self.store.transaction():
            self.assertEqual(len(self.store.all('reservation')),1)
            self.assertEqual(len(self.store.all('operation')),3)
            self.assertEqual(len(self.store.all('name-receipt')),2)
    def test_transfer_requires_release(self):
        other='22345678-1234-1234-1234-123456789abc'
        self.unpublished()
        self.assertCode('conflict',lambda:self.change(resource=other))
        self.change('release','release');self.change(resource=other)
        self.assertEqual(self.provider.calls,['create','delete'])
    def test_live_and_pending_block(self):
        self.apply(self.prepare())
        self.assertCode('conflict',lambda:self.change('release','release'))
        self.prepare('delete',self.plan(rev=2,delete=True))
        self.assertCode('conflict',lambda:self.change('release','release'))
    def test_missing_tombstone_blocks(self):
        self.assertCode('conflict',lambda:self.change('release','release'))
        self.change()
        self.change('release','release')
    def test_foreign_and_delegation_block(self):
        for name,kind in [(self.desired.name,'A'),('hosts.example.com','NS')]:
            self.provider.rows=[dict(id='foreign',name=name,type=kind,content='8.8.8.8',ttl=300)]
            self.assertCode('conflict',self.change)
    def test_recheck_owner_and_revision(self):
        self.provider.on_list=lambda:setattr(self.auth,'enabled',False)
        self.assertCode('permission',self.change);self.auth.enabled=True
        self.provider.on_list=lambda:self.ledger.put_connection('admin',replace(self.connection,revision=2),1)
        self.assertCode('conflict',self.change)
        with self.store.transaction():self.assertEqual(self.store.all('reservation'),[])
    def test_receipt_failure_rolls_back(self):
        self.unpublished();original=self.store.write
        def fail(kind,key,value):
            if kind=='name-receipt':raise NetworkError('storage')
            return original(kind,key,value)
        with patch.object(self.store,'write',side_effect=fail):
            self.assertCode('storage',lambda:self.change('release','release'))
        with self.store.transaction():
            self.assertEqual(len(self.store.all('reservation')),1)
            self.assertIsNone(self.store.read('allocation',digest(['binding',f.RESOURCE])))
        self.change('release','release')
    def test_preview_no_effect(self):
        result=NameReservations(self.engine).check('admin','owner','binding',f.RESOURCE,
            self.desired.name,'reserve',connection_revision=1,binding_revision=1)
        self.assertEqual(result['revision_floor'],1)
        with self.store.transaction():self.assertEqual(self.store.all('reservation'),[])
