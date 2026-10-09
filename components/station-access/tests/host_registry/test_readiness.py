import base64
import json
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.utils import timezone
from zog.network_register.client import CloudflareError
from zog.station_access.host_registry import setup_configuration as setup, provider_checks
from zog.station_access.host_registry.models import ProviderCredential, ProviderAccessCheck, SecurityAudit, InventoryScan, BeaconDestination, SecurityGate


class SetupFixture:
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); root = Path(self.root.name); root.chmod(0o700)
        key = root/'vault.json';key.write_text(json.dumps({'active':'one','keys':{'one':base64.b64encode(os.urandom(32)).decode()}}));key.chmod(0o600)
        self.override = override_settings(HOST_VAULT_CONFIGURATION=str(key), HOST_DNS_CONFIGURATION='',HOST_IDENTITY_ORIGIN='',HOST_ARCHIVE_CONFIGURATION='',STATION_ACCESS_ZOG_PROJECT_DIRECTORY='')
        self.override.enable();self.addCleanup(self.override.disable);self.addCleanup(self.root.cleanup)
        SecurityGate.objects.get_or_create(pk=1)
        self.admin=get_user_model().objects.create_superuser('check-admin','','password');self.client.force_login(self.admin)
        self.token='fixture-private-provider-token'
        setup.save_provider('fixture',dict(revision=0,label='Cloudflare',provider='cloudflare',account_id='a'*32,secrets={'api_token':self.token}))
        self.credential=ProviderCredential.objects.get()
    def check(self,revision=1):return self.client.post(f'/api/setup/registries/{self.credential.pk}/check/',json.dumps({'revision':revision}),content_type='application/json')
    def payload(self,account=None):return {'result':[{'id':'b'*32,'name':'example.test','account':{'id':account or 'a'*32},'status':'active'}],'result_info':{'total_pages':1}}


class ProviderCheckTests(SetupFixture,TestCase):
    def test_read_only_check_and_metadata_no_secrets(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value=self.payload()) as call:
            result=self.check();self.assertEqual(result.status_code,200)
            call.assert_called_once_with('GET','/zones',query={'account.id':'a'*32,'page':1,'per_page':50})
        value=result.json()['access_check'];self.assertEqual(value['status'],'passed');self.assertTrue(value['fresh'])
        self.assertEqual(value['domains'][0]['name'],'example.test');self.assertIn('does not verify DNS-write',value['message'])
        metadata=self.client.get('/api/setup/registries/');self.assertEqual(metadata['Cache-Control'],'no-store')
        self.assertNotIn(self.token,metadata.content.decode());self.assertNotIn(self.token,str(list(SecurityAudit.objects.values())))
        self.assertNotIn(self.token,str(list(ProviderAccessCheck.objects.values())))
    def test_authentication_csrf_method_and_revision(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request') as network:
            self.client.logout();self.assertEqual(self.check().status_code,401)
            user=get_user_model().objects.create_user('ordinary');self.client.force_login(user);self.assertEqual(self.check().status_code,403)
            self.client.force_login(self.admin);self.assertEqual(self.check(0).status_code,409)
            self.assertEqual(self.client.get(f'/api/setup/registries/{self.credential.pk}/check/').status_code,405)
            client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
            self.assertEqual(client.post(f'/api/setup/registries/{self.credential.pk}/check/',json.dumps({'revision':1}),content_type='application/json').status_code,403)
            network.assert_not_called()
        self.assertEqual(ProviderAccessCheck.objects.count(),0)
    def test_failed_check_redacts_provider_errors(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',side_effect=CloudflareError(self.token+' untrusted provider response')):
            result=self.check()
        self.assertEqual(result.status_code,200);value=result.json()['access_check'];self.assertEqual(value['status'],'failed');self.assertFalse(value['fresh'])
        self.assertNotIn(self.token,result.content.decode());self.assertNotIn('untrusted',str(list(ProviderAccessCheck.objects.values())))
        self.assertEqual(ProviderAccessCheck.objects.get().error_code,'provider_unavailable')
    def test_cross_account_response_is_rejected(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value=self.payload('c'*32)):
            value=self.check().json()['access_check']
        self.assertEqual(value['status'],'failed');self.assertEqual(value['domains'],[])
    def test_empty_listing_is_not_account_authorization_proof(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value={'result':[]}):value=self.check().json()['access_check']
        self.assertEqual(value['status'],'no_domains');self.assertIn('not confirmed',value['message'])
    def test_only_one_page_requested_and_pagination_exposed(self):
        payload=self.payload();payload['result_info']['total_pages']=3
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value=payload) as call:
            value=self.check().json()['access_check'];self.assertTrue(value['more_available']);self.assertEqual(call.call_count,1)
    def test_cooldown_is_durable_and_abandoned_attempt_can_retry(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value=self.payload()) as call:
            self.check();result=self.check();self.assertEqual(result.status_code,429);self.assertEqual(result['Retry-After'],'60');self.assertEqual(call.call_count,1)
            ProviderAccessCheck.objects.update(status='checking',started_at=timezone.now()-timedelta(seconds=61),finished_at=None)
            self.assertEqual(provider_checks.serialize(self.credential)['status'],'interrupted')
            self.assertEqual(self.check().status_code,200);self.assertEqual(call.call_count,2)
    def test_global_check_lease_blocks_concurrent_accounts(self):
        other=ProviderCredential.objects.create(label='Other',provider='cloudflare',account_id='c'*32,ciphertext='unused',key_id='one',revision=1)
        ProviderAccessCheck.objects.create(credential=other,credential_revision=1,started_at=timezone.now(),status='checking')
        with patch('zog.station_access.host_registry.provider_checks.Client.request') as call:self.assertEqual(self.check().status_code,429);call.assert_not_called()
    def test_credentials_changed_during_request_discard_result(self):
        def replacement(*args,**kwargs):
            setup.save_provider('other-admin',dict(id=str(self.credential.pk),revision=1,label='Cloudflare',provider='cloudflare',account_id='a'*32,secrets={'api_token':'replacement-fixture'}))
            return self.payload()
        with patch('zog.station_access.host_registry.provider_checks.Client.request',side_effect=replacement):self.assertEqual(self.check().status_code,409)
        row=ProviderAccessCheck.objects.get();self.assertEqual(row.status,'outdated');self.assertEqual(row.domains,[])
        self.credential.refresh_from_db();self.assertEqual(provider_checks.serialize(self.credential)['status'],'outdated')
    def test_late_request_cannot_overwrite_newer_attempt(self):
        newer=uuid.uuid4()
        def supersede(*args,**kwargs):
            ProviderAccessCheck.objects.update(attempt_id=newer,status='no_domains',finished_at=timezone.now())
            return self.payload()
        with patch('zog.station_access.host_registry.provider_checks.Client.request',side_effect=supersede):self.assertEqual(self.check().status_code,409)
        self.assertEqual(ProviderAccessCheck.objects.get().attempt_id,newer);self.assertEqual(ProviderAccessCheck.objects.get().status,'no_domains')
    def test_freshness_and_clock_skew(self):
        with patch('zog.station_access.host_registry.provider_checks.Client.request',return_value=self.payload()):self.check()
        for stamp in [timezone.now()-timedelta(seconds=901),timezone.now()+timedelta(seconds=1)]:
            ProviderAccessCheck.objects.update(finished_at=stamp);self.assertFalse(provider_checks.serialize(self.credential)['fresh'])
    def test_porkbun_check_uses_saved_pair_and_sanitizes_error(self):
        setup.save_provider('fixture',dict(revision=0,label='Porkbun',provider='porkbun',secrets={'api_key':'public-fixture','secret_key':'secret-fixture'}))
        row=ProviderCredential.objects.get(provider='porkbun')
        url=f'/api/setup/registries/{row.pk}/check/'
        with patch('zog.station_access.host_registry.provider_checks.PorkbunClient') as provider:
            provider.return_value.list_domains.return_value={'domains':[{'id':'example.com','name':'example.com','status':'listed'}],'more_available':False}
            response=self.client.post(url,json.dumps({'revision':1}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        provider.assert_called_once_with('public-fixture','secret-fixture')
        self.assertEqual(response.json()['access_check']['status'],'passed')
        metadata=self.client.get('/api/setup/registries/').json()
        saved=next(r for r in metadata['registries'] if r['provider']=='porkbun')
        self.assertTrue(saved['can_check']);self.assertFalse(saved['supported'])
        self.assertNotIn('secret-fixture',json.dumps(metadata))
        ProviderAccessCheck.objects.filter(credential=row).delete()
        from zog.network_register.porkbun import PorkbunError
        with patch('zog.station_access.host_registry.provider_checks.PorkbunClient.list_domains',side_effect=PorkbunError('secret-fixture')):
            response=self.client.post(url,json.dumps({'revision':1}),content_type='application/json')
        self.assertEqual(response.json()['access_check']['status'],'failed')
        self.assertNotIn('secret-fixture',response.content.decode())

    def test_vault_failure_does_not_contact_provider(self):
        with override_settings(HOST_VAULT_CONFIGURATION='/missing-vault'),patch('zog.station_access.host_registry.provider_checks.Client.request') as call:
            value=self.check().json()['access_check'];self.assertEqual(value['status'],'failed');self.assertIn('vault',value['message']);call.assert_not_called()


class ProviderTransactionTests(SetupFixture,TransactionTestCase):
    def test_no_transaction_spans_provider_request(self):
        def read(*args,**kwargs):
            self.assertFalse(connection.in_atomic_block)
            return self.payload()
        with patch('zog.station_access.host_registry.provider_checks.Client.request',side_effect=read):self.assertEqual(self.check().status_code,200)


class ReadinessTests(SetupFixture,TestCase):
    def checks(self):
        result=self.client.get('/api/setup/readiness/');self.assertEqual(result.status_code,200)
        self.assertEqual(result['Cache-Control'],'no-store');self.assertTrue(result.json()['read_only'])
        return {c['id']:c for c in result.json()['checks']}
    def test_read_only_snapshot_no_provider_controller_or_database_changes(self):
        audits=SecurityAudit.objects.count();gate=SecurityGate.objects.get(pk=1).revision
        with patch('zog.station_access.host_registry.provider_checks.Client.request',side_effect=AssertionError('network forbidden')),patch('zog.station_access.box_control.port.get_gateway',side_effect=AssertionError('controller forbidden')),patch('subprocess.run',side_effect=AssertionError('process forbidden')):
            value=self.checks()
        self.assertEqual(value['vault']['status'],'configured');self.assertEqual(value['destinations']['status'],'not_configured')
        self.assertEqual(value['workspaces']['status'],'blocked');self.assertEqual(value['recovery']['status'],'not_checked')
        self.assertEqual(ProviderAccessCheck.objects.count(),0);self.assertEqual(SecurityAudit.objects.count(),audits);self.assertEqual(SecurityGate.objects.get(pk=1).revision,gate)
        self.assertNotIn(self.token,str(value))
    def test_saved_destinations_do_not_imply_installation(self):
        BeaconDestination.objects.create(label='Central',server='https://registry.test')
        value=self.checks()['destinations'];self.assertEqual(value['status'],'configured');self.assertIn('does not prove',value['detail'])
    def test_inventory_fresh_failed_stale_and_future(self):
        now=timezone.now();discovery=InventoryScan.objects.create(scope='region-discovery',last_success=now)
        region=InventoryScan.objects.create(scope='account/region',last_success=now)
        self.assertEqual(self.checks()['inventory']['status'],'observed')
        region.error='raw exception containing '+self.token;region.save();value=self.checks()['inventory'];self.assertEqual(value['status'],'needs_attention');self.assertNotIn(self.token,str(value))
        region.error='';region.save()
        for stamp in [now-timedelta(seconds=601),now+timedelta(hours=1)]:
            discovery.last_success=stamp;discovery.save();self.assertEqual(self.checks()['inventory']['status'],'needs_attention')
    def test_bad_vault_and_dns_fail_closed_without_file_creation(self):
        config=Path(self.root.name)/'dns.json';state=Path(self.root.name)/'dns-state'
        config.write_text(json.dumps({'domain':'example.test','suffix':'hosts.example.test','state_directory':str(state),'account_id':'a'*32,'token_file':'missing'}))
        with override_settings(HOST_VAULT_CONFIGURATION='/missing',HOST_DNS_CONFIGURATION=str(config)):
            value=self.checks();self.assertEqual(value['vault']['status'],'needs_attention');self.assertEqual(value['dns-controller']['status'],'needs_attention')
        self.assertFalse(state.exists())
    def test_public_settings_are_configuration_not_certificate_proof(self):
        with override_settings(HOST_IDENTITY_ORIGIN='https://registry.test',ALLOWED_HOSTS=['registry.test','testserver'],DEBUG=False,SESSION_COOKIE_SECURE=True):
            value=self.checks()['https'];self.assertEqual(value['status'],'configured');self.assertIn('not checked',value['detail'])
        with override_settings(HOST_IDENTITY_ORIGIN='https://registry.test',ALLOWED_HOSTS=['*'],DEBUG=False,SESSION_COOKIE_SECURE=True):self.assertEqual(self.checks()['https']['status'],'needs_attention')
    def test_readiness_requires_administrator(self):
        self.client.logout();self.assertEqual(self.client.get('/api/setup/readiness/').status_code,401)
        self.client.force_login(get_user_model().objects.create_user('reader'));self.assertEqual(self.client.get('/api/setup/readiness/').status_code,403)
