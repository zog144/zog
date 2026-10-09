import copy
import json
import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client as HttpClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from zog.network_register.client import CloudflareError
from zog.network_register.dns import DnsRecords
from zog.station_access.host_registry.models import Host, InventoryScan, DnsAssignment, HostIdentity
from zog.station_access.host_registry.services import enroll
from zog.station_access.host_registry.dns_reconcile import reconcile, configure_assignment, controller_lock

class Provider:
    account='a'*32
    def __init__(self):
        self.rows=[];self.calls=[];self.lose_response=False
    def pages(self,path,query):
        if path=='/zones':return [{'id':'zone','name':'example.uk','account':{'id':self.account}}]
        return copy.deepcopy([r for r in self.rows if r['name']==query['name']])
    def result(self,method,path,body=None):
        self.calls.append(method)
        if method=='DELETE':
            self.rows=[r for r in self.rows if r['id']!=path.split('/')[-1]]
            result={'id':path.split('/')[-1]}
        elif method=='PATCH':
            result=dict(body,id=path.split('/')[-1]);self.rows=[r for r in self.rows if r['id']!=result['id']]+[result]
        else:
            result=dict(body,id='record-'+str(len(self.calls)));self.rows.append(result)
        if self.lose_response:
            self.lose_response=False
            raise CloudflareError('Transport failure; outcome may be unknown')
        return copy.deepcopy(result)

class DnsTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'domain':'example.uk','suffix':'hosts.example.uk','account_id':'a'*32,'state_directory':str(self.root),'auto_publish_enrolled':True}
        (self.root/'controller.json').write_text(json.dumps({'schema':1,**{k:self.config[k] for k in ['domain','suffix','account_id']}}))
        (self.root/'network-register').mkdir()
        self.provider=Provider();self.dns=DnsRecords(self.provider,'example.uk',self.root/'network-register')
        self.host,self.token=enroll(account_id='123456789012',region='us-east-1',instance_id='i-0123456789abcdef0',label='Compiler 01')
        HostIdentity.objects.create(host=self.host,fingerprint='a'*64,public_key='test-fixture',approved_by='test',approved_at=timezone.now())
        self.observe()
        self.admin=get_user_model().objects.create_superuser('dns-admin',password='synthetic-test-only')
    def observe(self,state='running',address='8.8.4.4'):
        now=timezone.now()
        for scope in ['region-discovery','123456789012/us-east-1']:
            InventoryScan.objects.update_or_create(scope=scope,defaults={'last_success':now,'error':''})
        Host.objects.filter(pk=self.host.pk).update(aws_checked_at=now,aws_missing_since=None,aws_observation={'state':state,'public_ip':address},last_received=now,signed_last_received=now,report={'public_ip':address,'cloud':{'account_id':self.host.account_id,'region':self.host.region,'instance_id':self.host.instance_id}})
        self.host.refresh_from_db()
    def run_worker(self):return reconcile(self.config,self.dns)
    def assignment(self):return DnsAssignment.objects.get(host=self.host)
    def test_publish_noop_label_change_stop_restart_retains_name(self):
        self.assertEqual(self.run_worker(),{'created':1})
        first=self.assignment();self.assertEqual(first.name,'compiler-01.hosts.example.uk')
        self.assertEqual(self.run_worker(),{'unchanged':1});self.assertEqual(self.provider.calls,['POST'])
        Host.objects.filter(pk=self.host.pk).update(label='New friendly label')
        self.observe('stopped','');self.assertEqual(self.run_worker(),{'deleted':1})
        self.assertEqual(self.assignment().name,first.name)
        self.observe(address='8.8.8.8');self.assertEqual(self.run_worker(),{'created':1})
        self.assertEqual(self.assignment().owner_id,first.owner_id)
        self.assertEqual(self.assignment().observed_address,'8.8.8.8')
    def test_scan_failure_missed_heartbeat_and_missing_inventory_never_delete(self):
        self.run_worker()
        InventoryScan.objects.filter(scope='123456789012/us-east-1').update(error='UnauthorizedOperation')
        self.assertEqual(self.run_worker(),{'waiting':1})
        self.observe();Host.objects.filter(pk=self.host.pk).update(signed_last_received=timezone.now()-timedelta(minutes=4))
        self.assertEqual(self.run_worker(),{'waiting':1})
        self.observe();Host.objects.filter(pk=self.host.pk).update(aws_missing_since=timezone.now())
        self.assertEqual(self.run_worker(),{'waiting':1})
        self.assertEqual(self.provider.calls,['POST'])
    def test_private_mismatched_and_unenrolled_hosts_not_published(self):
        self.observe(address='10.0.0.1');self.assertEqual(self.run_worker(),{})
        self.observe();Host.objects.filter(pk=self.host.pk).update(report={'public_ip':'8.8.8.8'})
        self.assertEqual(self.run_worker(),{})
        self.observe();HostIdentity.objects.filter(host=self.host).delete()
        self.assertEqual(self.run_worker(),{});self.assertEqual(self.provider.calls,[])
    def test_explicit_unpublish_survives_auto_assignment_even_with_failed_inventory(self):
        self.run_worker();configure_assignment(self.host,self.config,False)
        InventoryScan.objects.update(error='AccessDenied')
        self.assertEqual(self.run_worker(),{'deleted':1})
        self.observe();self.assertEqual(self.run_worker(),{'absent':1})
        self.assertFalse(self.assignment().enabled)
    def test_conflicting_record_is_preserved_and_backed_off(self):
        self.provider.rows=[{'id':'foreign','type':'A','name':'compiler-01.hosts.example.uk','content':'8.8.8.8'}]
        self.assertEqual(self.run_worker(),{'conflict':1})
        self.assertEqual(self.run_worker(),{'backoff':1})
        self.assertEqual(self.provider.calls,[]);self.assertEqual(self.provider.rows[0]['id'],'foreign')
    def test_lost_create_response_recovers_without_duplicate(self):
        self.provider.lose_response=True
        self.assertEqual(self.run_worker(),{'provider_error':1})
        self.assertEqual(self.run_worker(),{'backoff':1})
        DnsAssignment.objects.update(next_attempt=None)
        self.assertEqual(self.run_worker(),{'unchanged':1})
        self.assertEqual(self.provider.calls,['POST'])
    def test_new_stop_supersedes_backoff_after_lost_create(self):
        self.provider.lose_response=True;self.run_worker();self.observe('terminated','')
        self.assertEqual(self.run_worker(),{'deleted':1})
        self.assertEqual(self.provider.calls,['POST','DELETE'])
    def test_storage_error_stops_worker_and_same_state_recovers(self):
        from zog.network_register.state import save
        calls=[]
        def fail_result(path,value):
            calls.append(1)
            if len(calls)==2:raise OSError('full')
            return save(path,value)
        with patch('zog.network_register.dns.save',side_effect=fail_result):
            with self.assertRaises(OSError):self.run_worker()
        self.assertEqual(self.assignment().status,'storage_error')
        DnsAssignment.objects.update(next_attempt=None)
        self.assertEqual(self.run_worker(),{'unchanged':1})
        self.assertEqual(self.provider.calls,['POST'])
    def test_missing_state_refuses_reinitialization(self):
        (self.root/'controller.json').unlink()
        with self.assertRaises(OSError):self.run_worker()
        self.assertEqual(self.provider.calls,[])
    def test_serialization_blocks_concurrent_desired_change(self):
        with controller_lock(self.config):
            with self.assertRaises(BlockingIOError):configure_assignment(self.host,self.config,True)
        self.assertEqual(DnsAssignment.objects.count(),0)
    def test_name_collisions_and_explicit_rename_rejected(self):
        self.run_worker()
        other,_=enroll(account_id='123456789012',region='us-east-1',instance_id='i-other',label='Compiler 01')
        second=configure_assignment(other,self.config,True)
        self.assertNotEqual(second.name,self.assignment().name)
        with self.assertRaises(ValueError):configure_assignment(self.host,self.config,True,'renamed')
    def test_dns_endpoint_requires_admin_csrf_and_never_leaks_config(self):
        path=f'/api/hosts/{self.host.id}/dns/'
        configpath=self.root/'config.json';configpath.write_text(json.dumps(self.config))
        with self.settings(HOST_DNS_CONFIGURATION=str(configpath)):
            self.assertEqual(self.client.post(path,'{}',content_type='application/json').status_code,401)
            client=HttpClient(enforce_csrf_checks=True);client.force_login(self.admin)
            self.assertEqual(client.post(path,'{}',content_type='application/json').status_code,403)
            self.client.force_login(self.admin)
            response=self.client.post(path,json.dumps({'enabled':True,'label':'chosen-name'}),content_type='application/json')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['dns']['name'],'chosen-name.hosts.example.uk')
            payload=self.client.get('/api/hosts/').json()
            self.assertNotIn('state_directory',payload['dns']);self.assertNotIn('account_id',payload['dns'])
            self.assertEqual(payload['hosts'][0]['dns']['status'],'pending')
    def test_registry_intent_save_failure_prevents_provider_mutation(self):
        from django.db import OperationalError
        real_save=DnsAssignment.save
        def save(instance,*args,**kwargs):
            if instance.status=='applying':raise OperationalError('storage unavailable')
            return real_save(instance,*args,**kwargs)
        with patch.object(DnsAssignment,'save',save):
            with self.assertRaises(OperationalError):self.run_worker()
        self.assertEqual(self.provider.calls,[])
    def test_registry_result_save_failure_recovers_same_provider_record(self):
        from django.db import OperationalError
        real_save=DnsAssignment.save
        def save(instance,*args,**kwargs):
            if instance.status=='synchronized':raise OperationalError('storage unavailable')
            return real_save(instance,*args,**kwargs)
        with patch.object(DnsAssignment,'save',save):
            with self.assertRaises(OperationalError):self.run_worker()
        self.assertEqual(self.run_worker(),{'unchanged':1})
        self.assertEqual(self.provider.calls,['POST'])
    def test_legacy_transition_holds_owned_record_then_revocation_removes_it(self):
        self.run_worker()
        HostIdentity.objects.filter(host=self.host).delete()
        self.assertEqual(self.run_worker(),{'waiting':1});self.assertEqual(len(self.provider.rows),1)
        HostIdentity.objects.create(host=self.host,fingerprint='b'*64,public_key='fixture',approved_by='test',approved_at=timezone.now(),status='revoked')
        self.assertEqual(self.run_worker(),{'deleted':1});self.assertEqual(self.assignment().name,'compiler-01.hosts.example.uk')
