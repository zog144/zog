import base64
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from zog.station_access.host_registry.models import ProviderCredential, BeaconDestination, SecurityAudit
from zog.station_access.host_registry import setup_configuration as setup


class SetupTests(TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory();root=Path(self.root.name);root.chmod(0o700)
        self.key=root/'vault.json';self.key.write_text(json.dumps({'active':'one','keys':{'one':base64.b64encode(os.urandom(32)).decode()}}));self.key.chmod(0o600)
        self.config=root/'dns.json';self.config.write_text(json.dumps({'account_id':'a'*32,'token_file':'unused'}))
        self.override=override_settings(HOST_VAULT_CONFIGURATION=str(self.key),HOST_DNS_CONFIGURATION=str(self.config));self.override.enable()
        self.addCleanup(self.override.disable);self.addCleanup(self.root.cleanup)
        self.admin=get_user_model().objects.create_superuser('setup-admin','', 'password');self.client.force_login(self.admin)
    def post(self,path,data):return self.client.post('/api/setup/'+path+'/',json.dumps(data),content_type='application/json')
    def provider(self,**changes):return dict(revision=0,label='DNS account',provider='cloudflare',account_id='a'*32,secrets={'api_token':'private-provider-token'})|changes
    def destination(self,**changes):return dict(revision=0,label='Central',server='https://registry.example.test',enabled=True,ca_certificate='')|changes
    def test_admin_and_csrf_required(self):
        for path in ('registries','deployments'):
            self.client.logout();self.assertEqual(self.client.get('/api/setup/'+path+'/').status_code,401)
            user=get_user_model().objects.create_user('ordinary-'+path);self.client.force_login(user)
            self.assertEqual(self.post(path,{}).status_code,403)
            client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
            self.assertEqual(client.post('/api/setup/'+path+'/',{},content_type='application/json').status_code,403)
    def test_encryption_redaction_rotation_and_stale_save(self):
        response=self.post('registries',self.provider());self.assertEqual(response.status_code,200)
        self.assertEqual(response['Cache-Control'],'no-store');self.assertNotIn('private-provider-token',response.content.decode())
        row=ProviderCredential.objects.get();self.assertNotIn('private-provider-token',row.ciphertext)
        self.assertEqual(setup.decrypt_provider(row),{'api_token':'private-provider-token'})
        self.assertNotIn('private-provider-token',str(list(SecurityAudit.objects.values())))
        data=self.provider(id=str(row.pk),revision=1,secrets={'api_token':'replacement-token'})
        self.assertEqual(self.post('registries',data).status_code,200)
        self.assertEqual(self.post('registries',data).status_code,409)
        row.refresh_from_db();self.assertEqual(setup.decrypt_provider(row)['api_token'],'replacement-token')
        row.account_id='b'*32
        with self.assertRaises(Exception):setup.decrypt_provider(row)
    def test_metadata_edit_preserves_secret_and_missing_vault_fails_closed(self):
        self.post('registries',self.provider());row=ProviderCredential.objects.get()
        data=self.provider(id=str(row.pk),revision=1,label='New label');data.pop('secrets')
        self.assertEqual(self.post('registries',data).status_code,200);row.refresh_from_db();self.assertEqual(setup.decrypt_provider(row)['api_token'],'private-provider-token')
        self.key.unlink();response=self.post('registries',self.provider());self.assertEqual(response.status_code,503);self.assertNotIn('private-provider-token',response.content.decode())
    def test_select_cloudflare_and_reconciler_uses_decrypted_key(self):
        self.post('registries',self.provider());row=ProviderCredential.objects.get()
        result=self.post('registries',dict(action='select-dns',credential_id=str(row.pk),revision=0));self.assertEqual(result.status_code,200)
        self.assertEqual(setup.cloudflare_credentials({'account_id':'a'*32}),('a'*32,'private-provider-token'))
        with self.assertRaises(ValueError):setup.cloudflare_credentials({'account_id':'b'*32})
        self.assertEqual(self.post('registries',dict(action='select-dns',credential_id='',revision=0)).status_code,409)
        self.assertEqual(self.post('registries',dict(action='select-dns',credential_id='',revision=1)).status_code,200)
        with patch('zog.network_register.client.credentials',return_value=('a'*32,'file-token')):
            self.assertEqual(setup.cloudflare_credentials({'token_file':'legacy'})[1],'file-token')
    def test_porkbun_stored_but_not_claimed_supported(self):
        response=self.post('registries',self.provider(provider='porkbun',account_id='',secrets={'api_key':'key-value','secret_key':'secret-value'}))
        self.assertEqual(response.status_code,200);self.assertFalse(response.json()['registries'][0]['supported'])
        row=ProviderCredential.objects.get();self.assertEqual(setup.decrypt_provider(row)['secret_key'],'secret-value')
        self.assertEqual(self.post('registries',dict(action='select-dns',credential_id=str(row.pk),revision=0)).status_code,400)
    def test_destination_normalization_no_network_and_history(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('No outbound verification in save')):
            self.assertEqual(self.post('deployments',self.destination(server='https://REGISTRY.example.test:443/')).status_code,200)
        row=BeaconDestination.objects.get();self.assertEqual(row.server,'https://registry.example.test')
        self.assertEqual(self.post('deployments',self.destination()).status_code,409)
        self.assertEqual(self.post('deployments',self.destination(id=str(row.pk),revision=1,enabled=False)).status_code,200)
        self.assertEqual(self.post('deployments',self.destination(id=str(row.pk),revision=1)).status_code,409)
        self.assertEqual(self.post('deployments',self.destination(id=str(row.pk),revision=2,server='https://other.test')).status_code,400)
        response=self.client.get('/api/setup/deployments/?download=1');self.assertEqual(response['Cache-Control'],'no-store')
        self.assertIn('attachment',response['Content-Disposition']);self.assertFalse(response.json()['destinations'][0]['enabled'])
        self.assertEqual(SecurityAudit.objects.filter(action='save-beacon-destination').count(),2)
    def test_invalid_origins_ca_and_capacity(self):
        for server in ['http://example.test','https://user:pass@example.test','https://example.test/path','https://example.test?token=secret','https://example.test:99999','https://example.test/#x']:
            self.assertEqual(self.post('deployments',self.destination(server=server)).status_code,400)
        for pem in ['-----BEGIN '+ 'PRIVATE KEY-----','not a certificate']:
            self.assertEqual(self.post('deployments',self.destination(ca_certificate=pem)).status_code,400)
        for i in range(16):BeaconDestination.objects.create(label=str(i),server=f'https://r{i}.test')
        self.assertEqual(self.post('deployments',self.destination()).status_code,400)
