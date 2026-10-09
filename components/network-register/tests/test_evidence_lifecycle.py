from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zog.network_register.contracts import NetworkError, Page
from zog.network_register.models import Connection, ZoneBinding, RecordSnapshot, Plan
from zog.network_register.evidence import AuthorityEvidence, AuthoritativeAnswer, CloudIdentity, HostEvidence, EvidenceGate
from zog.network_register.lifecycle import ConnectionLifecycle, ReadOnlyConnectionValidator
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger

RESOURCE='12345678-1234-1234-1234-123456789abc'
NS=('ns1.example.net','ns2.example.net')


class Auth:
    allowed=True
    def authorize(self,*args):return self.allowed


class Source:
    def __init__(self,now):
        self.now=now;self.transform=lambda e:e
        identity=CloudIdentity('aws-account','us-east-1','i-123')
        self.host_value=HostEvidence('owner','binding',RESOURCE,1,RecordSnapshot('one.hosts.example.com','8.8.8.8',600),
            True,True,identity,identity,identity,'8.8.8.8','8.8.8.8','running',now,now)

    def authority(self,c,b):
        return self.transform(AuthorityEvidence(c.owner_id,c.id,c.revision,c.credential_ref,b.id,b.revision,
            b.zone_id,b.zone_name,b.prefix,tuple(reversed(NS)),self.now,
            tuple(AuthoritativeAnswer(n,b.zone_name,True,self.now,True) for n in NS)))

    def host(self,*args):return self.host_value


class Provider:
    def __init__(self,c):self.c=c;self.reads=[]
    def get_zone(self,z):
        self.reads.append(('zone',z))
        return dict(id=z,name='example.com',account={'id':self.c.account_ref},status='active')
    def list_records(self,z,cursor=None):
        self.reads.append(('records',z));return Page(())


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=1000;self.source=Source(self.now)
        self.c=Connection('connection','owner','porkbun','account','vault:1',status='ready')
        self.b=ZoneBinding('binding','owner','connection','example.com','example.com','hosts.example.com',status='ready',nameservers=NS)
        self.gate=EvidenceGate(self.source,lambda:self.now)

    def check(self,action='publish',desired=None,rev=1):
        self.gate.check(self.c,self.b,RESOURCE,desired if desired is not None else self.source.host_value.desired,action,rev)

    def assertCode(self,code,call):
        with self.assertRaises(NetworkError) as ctx:call()
        self.assertEqual(ctx.exception.code,code)

    def test_matching_authority_and_host(self):self.assertIsNone(self.check())

    def test_nameserver_order_and_case_normalized(self):
        b=replace(self.b,nameservers=('NS2.EXAMPLE.NET.','ns1.example.net'))
        self.assertEqual(b.nameservers,NS);self.gate.authority(self.c,b)

    def test_missing_pin_and_changed_parent_delegation(self):
        self.assertCode('conflict',lambda:self.gate.authority(self.c,replace(self.b,nameservers=())))
        self.source.transform=lambda e:replace(e,delegated_nameservers=('foreign.example.net',))
        self.assertCode('conflict',self.check)

    def test_unknown_or_duplicate_nameserver_evidence(self):
        self.source.transform=lambda e:replace(e,answers=e.answers[:1])
        self.assertCode('conflict',self.check)
        self.source.transform=lambda e:replace(e,answers=(e.answers[0],e.answers[0]))
        self.assertCode('conflict',self.check)

    def test_non_authoritative_soa_wrong_zone_and_shadowed_prefix(self):
        for change in ({'authoritative':False},{'soa_zone':'other.com'},{'prefix_unshadowed':False}):
            with self.subTest(change=change):
                self.source.transform=lambda e:replace(e,answers=(replace(e.answers[0],**change),e.answers[1]))
                self.assertCode('permission',self.check)

    def test_stale_and_future_dns_observations(self):
        for stamp in (699,1001):
            self.source.transform=lambda e:replace(e,delegation_observed_at=stamp)
            self.assertCode('permission',self.check)
            self.source.transform=lambda e:replace(e,answers=(replace(e.answers[0],observed_at=stamp),e.answers[1]))
            self.assertCode('permission',self.check)

    def test_scope_and_revision_mismatch_rejected(self):
        for change in ({'owner_id':'other'},{'connection_revision':2},{'credential_ref':'vault:old'},
                       {'binding_revision':2},{'zone_id':'other'},{'prefix':'other.example.com'}):
            with self.subTest(change=change):
                self.source.transform=lambda e:replace(e,**change)
                self.assertCode('conflict',self.check)

    def test_unenrolled_stopped_disabled_and_address_mismatch(self):
        original=self.source.host_value
        for change in ({'enrolled':False},{'inventory_state':'stopped'},{'publish_enabled':False},
                       {'signed_address':'9.9.9.9'},{'inventory_address':'9.9.9.9'}):
            self.source.host_value=replace(original,**change);self.assertCode('permission',self.check)

    def test_identity_mismatch_rejected(self):
        original=self.source.host_value
        for key in ('signed_identity','inventory_identity'):
            self.source.host_value=replace(original,**{key:replace(original.enrolled_identity,instance_id='i-other')})
            self.assertCode('permission',self.check)

    def test_stale_and_future_host_observations(self):
        original=self.source.host_value
        for key in ('signed_observed_at','inventory_observed_at'):
            for stamp in (699,1001):
                self.source.host_value=replace(original,**{key:stamp});self.assertCode('permission',self.check)

    def test_exact_five_minute_boundary(self):
        self.source.now=700
        self.source.host_value=replace(self.source.host_value,signed_observed_at=700,inventory_observed_at=700)
        self.check()

    def test_desired_revision_and_snapshot_must_match(self):
        self.assertCode('conflict',lambda:self.check(rev=2))
        self.assertCode('conflict',lambda:self.check(desired=replace(self.source.host_value.desired,address='9.9.9.9')))

    def test_explicit_unpublish_does_not_need_live_host(self):
        self.source.host_value=replace(self.source.host_value,desired=None,publish_enabled=False,explicit_unpublish=True,
            enrolled=False,inventory_state='terminated',signed_observed_at=0,inventory_observed_at=0)
        self.check(action='unpublish')

    def test_stale_host_is_not_unpublish_intent(self):
        self.source.host_value=replace(self.source.host_value,desired=None,publish_enabled=False,signed_observed_at=0)
        self.assertCode('permission',lambda:self.check(action='unpublish'))

    def test_inspect_needs_dns_but_not_host_evidence(self):
        self.source.host=lambda *args:(_ for _ in ()).throw(AssertionError('unexpected host read'))
        self.gate.check(self.c,self.b,RESOURCE,None,'inspect',None)

    def test_disconnected_and_blocked_cannot_publish(self):
        self.assertCode('permission',lambda:self.gate.check(replace(self.c,status='disconnected'),self.b,RESOURCE,None,'inspect',None))
        self.assertCode('permission',lambda:self.gate.check(self.c,replace(self.b,status='blocked'),RESOURCE,self.source.host_value.desired,'publish',1))

    def test_dns_evidence_expiring_during_host_lookup_blocks(self):
        original=self.source.host
        def delayed(*args):
            self.now=1301
            return replace(original(*args),signed_observed_at=1301,inventory_observed_at=1301)
        self.source.host=delayed
        self.assertCode('permission',self.check)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite';self.store=SqliteStateStore(self.path,create=True)
        self.auth=Auth();self.now=1000;self.ledger=OperationLedger(self.store,self.auth,lambda:self.now)
        self.c=Connection('connection','owner','porkbun','account','vault:1',status='unverified')
        self.b=ZoneBinding('binding','owner','connection','example.com','example.com','hosts.example.com',nameservers=NS)
        self.ledger.put_connection('admin',self.c,0);self.ledger.put_binding('admin',self.b,0)
        self.source=Source(self.now);self.gate=EvidenceGate(self.source,lambda:self.now)
        self.providers=[]
        def factory(c):
            p=Provider(c);self.providers.append(p);return p
        self.validator=ReadOnlyConnectionValidator(self.gate,provider_factory=factory)
        self.lifecycle=ConnectionLifecycle(self.ledger,self.validator)

    def connection(self):
        with self.store.transaction():return self.ledger._connection('connection')

    def assertCode(self,code,call):
        with self.assertRaises(NetworkError) as ctx:call()
        self.assertEqual(ctx.exception.code,code)

    def activate(self):return self.lifecycle.activate('admin','owner','connection',1)

    def prepared(self):
        c,b,_=self.ledger.context('admin','owner','binding',RESOURCE)
        p=Plan('owner','binding',RESOURCE,c.revision,b.revision,1,'create',None,self.source.host_value.desired)
        return self.ledger.prepare('admin','request',p)

    def test_activation_reads_exact_target_and_marks_ready(self):
        c=self.activate();self.assertEqual(c.status,'ready');self.assertEqual(c.revision,2)
        self.assertEqual(self.providers[0].reads,[('zone','example.com'),('records','example.com')])
        b=self.ledger.context('admin','owner','binding',RESOURCE)[1]
        self.assertEqual((b.status,b.revision),('ready',2))
        self.gate.check(c,b,RESOURCE,self.source.host_value.desired,'publish',1)

    def test_failed_activation_remains_unverified(self):
        self.source.transform=lambda e:replace(e,delegated_nameservers=('foreign.example.net',))
        self.assertCode('conflict',self.activate);self.assertEqual(self.connection(),self.c)

    def test_rotation_validates_replacement_and_cancels_old_prepared(self):
        self.activate();self.prepared()
        c=self.lifecycle.rotate('admin','owner','connection','vault:2',2)
        self.assertEqual((c.credential_ref,c.revision),('vault:2',3))
        self.assertEqual(self.providers[-1].c.credential_ref,'vault:2')
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'cancelled')

    def test_failed_rotation_keeps_old_key_and_operation(self):
        self.activate();self.prepared()
        self.validator.validate=lambda *a:(_ for _ in ()).throw(NetworkError('permission'))
        self.assertCode('permission',lambda:self.lifecycle.rotate('admin','owner','connection','vault:2',2))
        self.assertEqual(self.connection().credential_ref,'vault:1')
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'prepared')

    def test_inflight_unknown_operation_prevents_rotation(self):
        self.activate();r=self.prepared();self.ledger.transition('admin','owner','request',r['revision'],'dispatching')
        self.assertCode('conflict',lambda:self.lifecycle.rotate('admin','owner','connection','vault:2',2))

    def test_revoke_during_candidate_validation_wins(self):
        self.activate()
        original=self.validator.validate
        def revoke(*a):
            receipt=original(*a)
            self.lifecycle.suspend('admin','owner','connection',2)
            return receipt
        self.validator.validate=revoke
        self.assertCode('conflict',lambda:self.lifecycle.rotate('admin','owner','connection','vault:2',2))
        self.assertEqual(self.connection().status,'revoked');self.assertEqual(self.connection().credential_ref,'vault:1')

    def test_binding_change_during_validation_prevents_switch(self):
        self.activate()
        original=self.validator.validate
        def changed(*a):
            receipt=original(*a)
            b=self.ledger.context('admin','owner','binding',RESOURCE)[1]
            self.ledger.put_binding('admin',replace(b,nameservers=('other.example.net',),revision=b.revision+1),b.revision)
            return receipt
        self.validator.validate=changed
        self.assertCode('conflict',lambda:self.lifecycle.rotate('admin','owner','connection','vault:2',2))
        self.assertEqual(self.connection().credential_ref,'vault:1')

    def test_revoke_does_not_wait_for_worker_or_erase_dispatched_intent(self):
        self.activate();r=self.prepared();self.ledger.transition('admin','owner','request',r['revision'],'dispatching')
        with self.store.worker_lock():self.lifecycle.suspend('admin','owner','connection',2)
        self.assertEqual(self.connection().status,'revoked')
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'dispatching')

    def test_disconnect_detaches_without_provider_actions_or_fallback(self):
        self.activate();self.prepared();count=len(self.providers)
        c=self.lifecycle.suspend('admin','owner','connection',2,disconnect=True)
        self.assertEqual(c.status,'disconnected');self.assertEqual(c.credential_ref,'vault:1')
        self.assertEqual(len(self.providers),count)
        self.assertEqual(self.ledger.context('admin','owner','binding',RESOURCE)[1].status,'detached')
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'cancelled')

    def test_storage_failure_rolls_back_rotation_and_cancellation(self):
        self.activate();self.prepared();original=self.store.write
        def fail(kind,key,value):
            if kind=='lifecycle-event':raise OSError('disk full')
            return original(kind,key,value)
        with patch.object(self.store,'write',side_effect=fail):
            with self.assertRaises(OSError):self.lifecycle.rotate('admin','owner','connection','vault:2',2)
        self.assertEqual(self.connection().credential_ref,'vault:1')
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'prepared')

    def test_stale_revision_wrong_owner_and_denied_actor(self):
        self.activate()
        self.assertCode('conflict',lambda:self.lifecycle.suspend('admin','owner','connection',1))
        self.assertCode('permission',lambda:self.lifecycle.suspend('admin','other','connection',2))
        self.auth.allowed=False
        self.assertCode('permission',lambda:self.lifecycle.suspend('admin','owner','connection',2))

    def test_too_slow_validation_cannot_activate(self):
        original=self.validator.validate
        def delayed(*args):
            receipt=original(*args);self.now=1301;return receipt
        self.validator.validate=delayed
        self.assertCode('permission',self.activate);self.assertEqual(self.connection(),self.c)

    def test_evidence_expiry_is_not_replaced_by_validation_start_time(self):
        self.source.now=701
        original=self.validator.validate
        def delayed(*args):
            receipt=original(*args);self.now=1002;return receipt
        self.validator.validate=delayed
        self.assertCode('permission',self.activate);self.assertEqual(self.connection(),self.c)

    def test_candidate_validation_false_is_not_authorization(self):
        self.validator.validate=lambda *a:False
        self.assertCode('permission',self.activate)

    def test_no_bound_targets_or_nameserver_pin_cannot_activate(self):
        self.ledger.put_binding('admin',replace(self.b,nameservers=(),revision=2),1)
        self.assertCode('permission',self.activate)

    def test_every_binding_must_validate_before_rotation(self):
        self.activate()
        b=replace(self.b,id='second',prefix='other.example.com',status='ready')
        self.ledger.put_binding('admin',b,0)
        old=self.source.authority
        def second(c,b):
            if b.id=='second':raise NetworkError('permission')
            return old(c,b)
        self.source.authority=second
        self.assertCode('permission',lambda:self.lifecycle.rotate('admin','owner','connection','vault:2',2))
        self.assertEqual(self.connection().credential_ref,'vault:1')

    def test_reopen_preserves_disconnect_and_audit(self):
        self.activate();self.lifecycle.suspend('admin','owner','connection',2,disconnect=True)
        reopened=SqliteStateStore(self.path)
        with reopened.transaction():
            self.assertEqual(reopened.read('connection','connection')['status'],'disconnected')
            events=reopened.all('lifecycle-event')
        self.assertEqual({e['action'] for e in events},{'activate','disconnect'})
        self.assertTrue(all('credential_ref' not in e for e in events))

    def test_real_engine_stops_when_host_evidence_expires_after_prepare(self):
        from zog.network_register.engine import DnsEngine
        self.activate()
        engine=DnsEngine(self.ledger,self.gate,provider_factory=self.validator.factory)
        plan=engine.plan('admin','owner','binding',RESOURCE,self.source.host_value.desired,1)
        row=self.ledger.prepare('admin','request',plan)
        self.now=1301;self.source.now=1301  # DNS refreshed; signed host report is stale.
        self.assertCode('permission',lambda:engine.apply('admin','owner','request',row['revision']))
        self.assertEqual(self.ledger.inspect_operation('admin','owner','request')['state'],'prepared')

    def test_bad_validation_receipt_cannot_switch_scope(self):
        original=self.validator.validate
        self.validator.validate=lambda *a:replace(original(*a),credential_ref='vault:other')
        self.assertCode('permission',self.activate)
        self.assertEqual(self.connection(),self.c)


if __name__=='__main__':unittest.main()
