import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase
from zog.network_register.contracts import NetworkError, Page
from zog.network_register.state import save
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import digest
from zog.station_access.host_registry import test_dns_evidence as evidence_fixture
from zog.station_access.host_registry import dns_cutover as cutover, dns_shared as shared
from zog.station_access.host_registry.dns_reconcile import controller_lock, configure_assignment, reconcile
from zog.station_access.host_registry.models import Host, DnsAssignment, ProviderCredential


class Provider:
    def __init__(self, row, account):
        self.rows=[row];self.calls=[];self.account=account;self.error=None;self.on_list=None
    def get_zone(self,zone):return dict(id=zone,name='example.uk',account={'id':self.account},status='active')
    def list_records(self,zone,cursor=None):
        if self.on_list:
            callback,self.on_list=self.on_list,None;callback()
        return Page(tuple(copy.deepcopy(self.rows)),None)
    def update_record(self,zone,record_id,snapshot,*,marker,idempotency_key):
        self.calls.append(('update',record_id))
        row=dict(id=record_id,name=snapshot.name,type='A',content=snapshot.address,ttl=snapshot.ttl,proxied=False,comment=marker)
        self.rows=[row if r['id']==record_id else r for r in self.rows]
        if self.error:raise self.error
        return row
    def create_record(self,zone,snapshot,*,marker,idempotency_key):
        self.calls.append(('create','created'))
        row=dict(id='created',name=snapshot.name,type='A',content=snapshot.address,ttl=snapshot.ttl,proxied=False,comment=marker)
        self.rows.append(row)
        if self.error:raise self.error
        return row
    def delete_record(self,zone,record_id,*,idempotency_key):
        self.calls.append(('delete',record_id));self.rows=[r for r in self.rows if r['id']!=record_id]
        if self.error:raise self.error


class CutoverTests(TestCase):
    def setUp(self):
        evidence_fixture.DnsEvidenceTests.setUp(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'network-register').mkdir()
        self.config=dict(domain='example.uk',suffix='hosts.example.uk',account_id='a'*32,state_directory=str(self.root),auto_publish_enrolled=True)
        save(self.root/'controller.json',cutover.legacy_binding(self.config))
        marker='Zog network-register owner '+hashlib.sha256(json.dumps(['a'*32,'zone',self.assignment.name,self.assignment.owner_id]).encode()).hexdigest()
        record=dict(id='legacy-record',name=self.assignment.name,type='A',content='8.8.8.8',ttl=60,proxied=False,comment=marker)
        self.provider=Provider(record,'a'*32)
        self.legacy_path=self.root/'network-register'/('assignment-'+self.assignment.name+'.json')
        save(self.legacy_path,dict(schema=1,account_id='a'*32,domain='example.uk',zone_id='zone',name=self.assignment.name,
             owner_id=self.assignment.owner_id,record_id='legacy-record',record=record,desired={k:v for k,v in record.items() if k!='id'},phase='present'))
        self.assignment.record_id='legacy-record';self.assignment.applied_revision=1;self.assignment.status='synchronized';self.assignment.save()
        self.kw=dict(collector=self.collector,provider_factory=lambda _:self.provider)
    def review(self):return cutover.review(self.config,self.data,**self.kw)
    def commit(self,review=None):
        self.reviewed=review or self.review();return cutover.commit(self.config,self.reviewed['review_id'],**self.kw)
    def run_worker(self):
        with controller_lock(self.config,modes=('shared',)) as root:return shared.reconcile_locked(self.config,root,**self.kw)
    def local_records(self):
        store=SqliteStateStore(self.root/('dns-ledger-'+self.reviewed['review_id']+'.sqlite3'))
        with store.transaction():return store.all('record')
    def test_review_is_read_only_and_commit_adopts_without_mutation(self):
        old=self.legacy_path.read_bytes();review=self.review()
        self.assertEqual(cutover.controller_state(self.config)['writer'],'legacy')
        self.assertEqual(review['records'][0]['item']['record_id'],'legacy-record')
        self.commit(review);self.assertFalse(self.provider.calls);self.assertEqual(self.legacy_path.read_bytes(),old)
        self.assertEqual(self.local_records()[0]['record_id'],'legacy-record')
        self.assertEqual(cutover.commit(self.config,review['review_id'],**self.kw)['writer'],'shared')
    def test_worker_normalizes_once_then_noop_then_explicit_unpublish(self):
        self.commit();self.assertEqual(self.run_worker(),{'synchronized':1})
        self.assertEqual(self.provider.calls,[('update','legacy-record')]);self.assertEqual(self.provider.rows[0]['ttl'],300)
        self.run_worker();self.assertEqual(len(self.provider.calls),1)
        configure_assignment(self.host,self.config,False)
        self.assertEqual(self.run_worker(),{'unpublished':1});self.assertEqual(self.provider.calls[-1],('delete','legacy-record'))
    def test_stopped_or_stale_host_freezes_without_deleting(self):
        self.commit();self.run_worker()
        observation=copy.deepcopy(self.host.aws_observation);observation['state']='stopped'
        Host.objects.filter(pk=self.host.pk).update(aws_observation=observation)
        self.assertEqual(self.run_worker(),{'waiting_verification':1});self.assertEqual(len(self.provider.calls),1)
    def test_fresh_address_change_updates_same_id(self):
        self.commit();self.run_worker()
        observation=copy.deepcopy(self.host.aws_observation);observation['public_ip']='9.9.9.9'
        signed=copy.deepcopy(self.host.signed_dns_report);signed['public_ip']='9.9.9.9'
        Host.objects.filter(pk=self.host.pk).update(aws_observation=observation,signed_dns_report=signed)
        self.run_worker();self.assertEqual(self.provider.calls[-1],('update','legacy-record'))
        self.assertEqual(self.provider.rows[0]['content'],'9.9.9.9')
    def test_provider_drift_between_review_and_commit_does_not_freeze(self):
        review=self.review();self.provider.rows[0]['content']='9.9.9.9'
        with self.assertRaises(NetworkError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['writer'],'legacy');self.assertFalse(self.provider.calls)
    def test_legacy_intent_changes_require_new_review(self):
        review=self.review();DnsAssignment.objects.filter(pk=self.host.pk).update(enabled=False,revision=2)
        with self.assertRaises(NetworkError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['writer'],'legacy')
    def test_changed_credential_and_tampered_review_rejected(self):
        review=self.review();ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=2)
        with self.assertRaises(NetworkError):self.commit(review)
        ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=1)
        path=self.root/('dns-review-'+review['review_id']+'.json');value=json.loads(path.read_text());value['selection']['zone_id']='other';save(path,value)
        with self.assertRaises(NetworkError):self.commit(review)
    def test_legacy_applying_or_orphan_state_blocks_review(self):
        value=json.loads(self.legacy_path.read_text());value['phase']='applying';save(self.legacy_path,value)
        with self.assertRaises(NetworkError):self.review()
        value['phase']='present';save(self.legacy_path,value);save(self.root/'network-register/assignment-orphan.example.uk.json',{})
        with self.assertRaises(NetworkError):self.review()
    def test_missing_provider_record_never_recreated_during_cutover(self):
        self.provider.rows=[]
        with self.assertRaises(NetworkError):self.review()
        self.assertFalse(self.provider.calls)
    def test_absent_assignment_reserved_then_explicit_publish_creates(self):
        self.provider.rows=[];value=json.loads(self.legacy_path.read_text());value.update(phase='absent',record_id=None,record=None,desired=None);save(self.legacy_path,value)
        DnsAssignment.objects.filter(pk=self.host.pk).update(record_id='',enabled=False,desired_action='absent',desired_address='')
        self.commit();self.assertEqual(self.local_records(),[{'deleted':True}]);self.run_worker();self.assertFalse(self.provider.calls)
        configure_assignment(self.host,self.config,True);self.run_worker();self.assertEqual(self.provider.calls,[('create','created')])
    def test_old_and_new_entry_points_share_lock_and_legacy_cannot_run(self):
        self.commit()
        with self.assertRaises(ValueError):reconcile(self.config,dns=object())
        with controller_lock(self.config,modes=('shared',)):
            with self.assertRaises(BlockingIOError):self.run_worker()
        self.assertFalse(self.provider.calls)
    def test_pause_resume_preserves_state_and_never_switches_back(self):
        self.commit();cutover.pause(self.config)
        with self.assertRaises(ValueError):self.run_worker()
        self.assertEqual(shared.status(self.config)['writer'],'paused')
        cutover.resume(self.config,**self.kw);self.assertEqual(cutover.controller_state(self.config)['writer'],'shared')
        self.assertFalse(self.provider.calls)
    def test_crash_after_freeze_resumes_same_review(self):
        review=self.review();original=cutover.save
        def fail(path,value):
            original(path,value)
            if path.name=='controller.json' and value.get('stage')=='frozen':raise OSError('crash')
        with patch.object(cutover,'save',side_effect=fail):
            with self.assertRaises(OSError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['writer'],'frozen')
        with self.assertRaises(ValueError):reconcile(self.config,dns=object())
        self.commit(review);self.assertFalse(self.provider.calls)
    def test_crash_after_adoption_resumes_without_duplicate_records(self):
        review=self.review();original=cutover.save
        def fail(path,value):
            original(path,value)
            if path.name=='controller.json' and value.get('stage')=='adopted':raise OSError('crash')
        with patch.object(cutover,'save',side_effect=fail):
            with self.assertRaises(OSError):self.commit(review)
        self.commit(review);self.assertEqual(len(self.local_records()),1);self.assertFalse(self.provider.calls)
    def test_lost_ledger_is_not_recreated(self):
        self.commit();path=self.root/('dns-ledger-'+self.reviewed['review_id']+'.sqlite3');path.unlink()
        with self.assertRaises(NetworkError):self.run_worker()
        self.assertFalse(path.exists());self.assertFalse(self.provider.calls)
    def test_lost_dispatch_response_recovery_reads_only(self):
        self.commit();self.provider.error=RuntimeError('crash after provider applied')
        with self.assertRaises(RuntimeError):self.run_worker()
        self.assertEqual(shared.status(self.config)['operations'][0]['state'],'dispatching')
        self.provider.error=None;self.run_worker();self.assertEqual(self.provider.calls,[('update','legacy-record')])
        self.assertEqual(shared.status(self.config)['operations'][0]['state'],'succeeded')
    def test_provider_conflict_after_cutover_blocks_preserving_foreign_change(self):
        self.commit();self.provider.rows[0]['content']='9.9.9.9'
        self.assertEqual(self.run_worker(),{'conflict':1});self.assertFalse(self.provider.calls)
    def test_missing_controller_state_cannot_default_to_legacy(self):
        self.commit();(self.root/'controller.json').unlink()
        with self.assertRaises(FileNotFoundError):reconcile(self.config,dns=object())
    def test_different_review_cannot_replace_frozen_selection(self):
        first=self.review();second=self.review();original=cutover.save
        def fail(path,value):
            original(path,value)
            if path.name=='controller.json' and value.get('stage')=='frozen':raise OSError()
        with patch.object(cutover,'save',side_effect=fail):
            with self.assertRaises(OSError):self.commit(first)
        with self.assertRaises(NetworkError):self.commit(second)
    def test_stale_prepared_plan_is_cancelled_before_new_intent(self):
        self.commit()
        selected,source,engine=shared.open_runtime(self.config,self.root,**self.kw)
        row,desired=shared.refresh_intent(source,engine.gate,str(self.host.pk))
        plan=engine.plan(selected.connection.owner_id,selected.connection.owner_id,selected.binding.id,str(self.host.pk),desired,row.revision)
        engine.ledger.prepare(selected.connection.owner_id,'old-intent',plan)
        configure_assignment(self.host,self.config,False)
        self.run_worker();ops=shared.status(self.config)['operations']
        self.assertEqual(next(o['state'] for o in ops if o['request_id']=='old-intent'),'cancelled')
        self.assertEqual(self.provider.calls,[('delete','legacy-record')])

    def test_crash_after_database_creation_resumes_forward(self):
        review=self.review();original=cutover.SqliteStateStore
        def fail(path,**kwargs):
            value=original(path,**kwargs)
            if kwargs.get('create'):raise OSError('crash after database creation')
            return value
        with patch.object(cutover,'SqliteStateStore',side_effect=fail):
            with self.assertRaises(OSError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['stage'],'initializing')
        self.commit(review);self.assertFalse(self.provider.calls)
    def test_initializing_with_missing_database_refuses_recreation(self):
        review=self.review()
        with patch.object(cutover,'SqliteStateStore',side_effect=OSError('crash before database creation')):
            with self.assertRaises(OSError):self.commit(review)
        with self.assertRaises(NetworkError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['writer'],'frozen')
    def test_crash_after_activation_keeps_shared_and_retry_is_idempotent(self):
        review=self.review();original=cutover.save
        def fail(path,value):
            original(path,value)
            if path.name=='controller.json' and value.get('writer')=='shared':raise OSError('lost completion')
        with patch.object(cutover,'save',side_effect=fail):
            with self.assertRaises(OSError):self.commit(review)
        self.commit(review);self.assertEqual(cutover.controller_state(self.config)['writer'],'shared')
        self.assertFalse(self.provider.calls)
    def test_final_activation_failure_retains_frozen_adoption(self):
        review=self.review();original=cutover.save
        def fail(path,value):
            if path.name=='controller.json' and value.get('writer')=='shared':raise OSError('full disk')
            original(path,value)
        with patch.object(cutover,'save',side_effect=fail):
            with self.assertRaises(OSError):self.commit(review)
        self.assertEqual(cutover.controller_state(self.config)['writer'],'frozen')
        self.assertEqual(len(self.local_records()),1);self.commit(review)
    def test_targeted_run_refuses_unreviewed_host(self):
        self.commit()
        with controller_lock(self.config,modes=('shared',)) as root:
            with self.assertRaises(NetworkError):shared.reconcile_locked(self.config,root,resource_ids=['11111111-1111-4111-8111-111111111111'],**self.kw)
            self.assertEqual(shared.reconcile_locked(self.config,root,resource_ids=[str(self.host.pk)],**self.kw),{'synchronized':1})
        self.assertEqual(self.provider.calls,[('update','legacy-record')])
    def test_revoked_admin_blocks_commit_pause_and_recovery(self):
        review=self.review();self.admin.is_active=False;self.admin.save()
        with self.assertRaises(NetworkError):self.commit(review)
        self.admin.is_active=True;self.admin.save();self.commit(review)
        self.admin.is_active=False;self.admin.save()
        with self.assertRaises(NetworkError):cutover.pause(self.config)
        with self.assertRaises(NetworkError):self.run_worker()
        self.assertFalse(self.provider.calls)
