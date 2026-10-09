import json
from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from zog.station_access.host_registry.models import Host, InventoryScan
from zog.station_access.host_registry.services import enroll
from zog.station_access.host_registry.inventory import commit_region, scan_inventory

class RegistryTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('registry-admin',password='synthetic-test-password')
        self.host,self.token=enroll(account_id='123456789012',region='us-east-1',instance_id='i-0123456789abcdef0',label='Original')
        Host.objects.filter(pk=self.host.pk).update(legacy_until=timezone.now()+timedelta(hours=1))
        self.host.refresh_from_db()
        self.payload={'version':1,'hostname':'test-host','public_dns':'example.test','cloud':{'account_id':self.host.account_id,'region':self.host.region,'instance_id':self.host.instance_id}}
    def heartbeat(self,**changes):
        return self.client.post(f'/api/hosts/{self.host.id}/heartbeat/',json.dumps(self.payload|changes),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.token)
    def inventory(self,instances):
        scan,_=InventoryScan.objects.get_or_create(scope='123456789012/us-east-1')
        commit_region('123456789012','us-east-1',instances,scan)
    def instance(self,**changes):
        return {'InstanceId':self.host.instance_id,'State':{'Name':'running'},'PublicDnsName':'current.example.test','Tags':[{'Key':'Project','Value':'Zog'},{'Key':'Name','Value':'AWS label'}]}|changes
    def test_tokens_are_bound_to_one_host(self):
        other,_=enroll(label='other')
        response=self.client.post(f'/api/hosts/{other.id}/heartbeat/',json.dumps({'version':1}),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+self.token)
        self.assertEqual(response.status_code,401)
        self.assertEqual(self.heartbeat().status_code,200)
    def test_revocation_and_rotation(self):
        self.host.token_revoked=True;self.host.save()
        self.assertEqual(self.heartbeat().status_code,401)
        _,new_token=enroll(host_id=self.host.pk)
        self.assertEqual(self.heartbeat().status_code,401)
        self.token=new_token
        self.assertEqual(self.heartbeat().status_code,200)
    def test_heartbeat_cannot_write_label_or_cloud_identity(self):
        self.assertEqual(self.heartbeat(label='overwrite').status_code,400)
        self.assertEqual(self.heartbeat(cloud={}).status_code,400)
        self.assertEqual(self.heartbeat(public_dns='javascript:alert(1)').status_code,400)
    def test_labels_survive_heartbeats_and_inventory(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f'/api/hosts/{self.host.id}/label/',json.dumps({'label':'My compiler host'}),content_type='application/json').status_code,200)
        self.assertEqual(self.heartbeat().status_code,200)
        self.inventory([self.instance()])
        self.host.refresh_from_db();self.assertEqual(self.host.label,'My compiler host')
        self.assertEqual(Host.objects.count(),1)
    def test_instance_restart_changes_address_not_identity(self):
        self.inventory([self.instance()]);self.inventory([self.instance(PublicDnsName='new.example.test')])
        self.host.refresh_from_db()
        self.assertEqual(self.host.aws_observation['public_dns'],'new.example.test')
        self.assertEqual(Host.objects.count(),1)
        self.inventory([self.instance(State={'Name':'stopped'},PublicDnsName='')])
        self.host.refresh_from_db();self.assertEqual(self.host.aws_observation['public_dns'],'')
    def test_missing_host_is_not_invented_termination(self):
        self.inventory([self.instance()]);self.inventory([])
        self.client.force_login(self.admin)
        result=self.client.get('/api/hosts/').json()['hosts'][0]
        self.assertEqual(result['aws_state'],'unknown')
        self.assertEqual(result['aws']['state'],'running')
        self.assertIsNotNone(result['aws_missing_since'])
    def test_stale_observations_and_no_tokens_in_api(self):
        self.inventory([self.instance()]);self.heartbeat()
        Host.objects.filter(pk=self.host.pk).update(last_received=timezone.now()-timedelta(minutes=4),aws_checked_at=timezone.now()-timedelta(minutes=11))
        self.client.force_login(self.admin)
        response=self.client.get('/api/hosts/')
        host=response.json()['hosts'][0]
        self.assertEqual(host['heartbeat'],'overdue');self.assertEqual(host['aws_state'],'unknown')
        self.assertNotIn(self.token,response.content.decode());self.assertNotIn('token_digest',response.content.decode())
    def test_browser_access_requires_admin_and_csrf(self):
        self.assertEqual(self.client.get('/api/hosts/').status_code,401)
        ordinary=get_user_model().objects.create_user('ordinary')
        self.client.force_login(ordinary);self.assertEqual(self.client.get('/api/hosts/').status_code,403)
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(f'/api/hosts/{self.host.id}/label/',json.dumps({'label':'changed'}),content_type='application/json').status_code,403)
    def test_region_failure_does_not_erase_observations(self):
        self.inventory([self.instance()])
        session=Mock();session.client.return_value.get_caller_identity.return_value={'Account':'123456789012'}
        session.client.return_value.describe_regions.return_value={'Regions':[{'RegionName':'us-east-1'}]}
        def pages():
            yield {'Reservations':[{'Instances':[]}]}
            raise TimeoutError('test')
        session.client.return_value.get_paginator.return_value.paginate.side_effect=pages
        self.assertFalse(scan_inventory(session))
        self.host.refresh_from_db();self.assertEqual(self.host.aws_observation['state'],'running');self.assertIsNone(self.host.aws_missing_since)
        self.assertEqual(InventoryScan.objects.get(scope='123456789012/us-east-1').error,'TimeoutError')
    def test_all_regions_and_untagged_instances(self):
        session=Mock();session.client.return_value.get_caller_identity.return_value={'Account':'123456789012'}
        session.client.return_value.describe_regions.return_value={'Regions':[{'RegionName':'us-east-1'},{'RegionName':'eu-west-1'}]}
        session.client.return_value.get_paginator.return_value.paginate.return_value=[{'Reservations':[{'Instances':[self.instance(Tags=[])]}]}]
        self.assertTrue(scan_inventory(session))
        self.client.force_login(self.admin);result=self.client.get('/api/hosts/').json()
        self.assertEqual(len(result['hosts']),2);self.assertFalse(any(h['zog_tagged'] for h in result['hosts']))

    def test_real_sdk_timeout_records_failure_and_continues(self):
        from botocore.exceptions import ReadTimeoutError
        session=Mock()
        session.client.return_value.get_caller_identity.return_value={"Account":"123456789012"}
        session.client.return_value.describe_regions.return_value={"Regions":[{"RegionName":"eu-north-1"},{"RegionName":"us-east-1"}]}
        session.client.return_value.get_paginator.return_value.paginate.side_effect=[ReadTimeoutError(endpoint_url="https://example.test"),[{"Reservations":[{"Instances":[self.instance()]}]}]]
        self.assertFalse(scan_inventory(session))
        self.assertEqual(InventoryScan.objects.get(scope="123456789012/eu-north-1").error,"ReadTimeoutError")
        self.assertIsNotNone(InventoryScan.objects.get(scope="123456789012/us-east-1").last_success)

    def test_unobserved_inventory_uses_reported_address_and_unknown_tags(self):
        self.heartbeat()
        self.client.force_login(self.admin)
        result=self.client.get('/api/hosts/').json()
        self.assertEqual(result['inventory_status'],'unavailable')
        host=result['hosts'][0]
        self.assertEqual(host['public_address'],'example.test')
        self.assertEqual(host['address_source'],'heartbeat')
        self.assertEqual(host['tag_status'],'unknown')
        self.assertFalse(host['address_stale'])

    def test_inventory_cleared_address_does_not_resurrect_daemon_address(self):
        self.heartbeat()
        self.inventory([self.instance(State={'Name':'stopped'},PublicDnsName='',Tags=[])])
        self.client.force_login(self.admin)
        host=self.client.get('/api/hosts/').json()['hosts'][0]
        self.assertEqual(host['public_address'],'')
        self.assertEqual(host['address_source'],'aws')
        self.assertEqual(host['tag_status'],'untagged')
        Host.objects.filter(pk=self.host.pk).update(aws_checked_at=timezone.now()-timedelta(minutes=11))
        host=self.client.get('/api/hosts/').json()['hosts'][0]
        self.assertEqual(host['tag_status'],'unknown')
        self.assertTrue(host['address_stale'])

    def test_coverage_distinguishes_complete_partial_and_unavailable(self):
        from zog.station_access.host_registry.views import inventory_status
        now=timezone.now()
        discovery={'scope':'region-discovery','last_success':now-timedelta(seconds=10),'error':''}
        region={'scope':'123/us-east-1','last_success':now,'error':''}
        self.assertEqual(inventory_status([discovery,region],now),'complete')
        self.assertEqual(inventory_status([dict(discovery,error='UnauthorizedOperation'),region],now),'partial')
        self.assertEqual(inventory_status([discovery,dict(region,last_success=None,error='UnauthorizedOperation')],now),'unavailable')
        self.assertEqual(inventory_status([discovery,dict(region,last_success=now-timedelta(minutes=11))],now),'unavailable')
