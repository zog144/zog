import json
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.utils import timezone
from zog.station_access.host_registry import cloud_configuration as cloud, test_setup
from zog.station_access.host_registry.models import CloudCredential, SecurityAudit


class CloudTests(TestCase):
    setUp = test_setup.SetupTests.setUp
    post = test_setup.SetupTests.post

    def data(self, **changes):
        return dict(revision=0,label='AWS development',account_id='123456789012',mode='keys',region='us-east-1',enabled=True,
                    secrets={'access_key_id':'AKIA'+'X'*16,'secret_access_key':'fixture-private-secret'}) | changes

    def create(self, **changes):
        result=self.post('clouds',self.data(**changes));self.assertEqual(result.status_code,200,result.content)
        return CloudCredential.objects.get()

    def check(self,row,revision=None):
        return self.post(f'clouds/{row.pk}/check',{'revision':revision or row.revision})

    def test_permissions_csrf_and_no_store(self):
        row=self.create()
        for path in ['clouds',f'clouds/{row.pk}/check']:
            self.client.logout();self.assertEqual(self.post(path,{}).status_code,401)
            user=get_user_model().objects.create_user('ordinary-'+path);self.client.force_login(user)
            self.assertEqual(self.post(path,{}).status_code,403)
            secured=Client(enforce_csrf_checks=True);secured.force_login(self.admin)
            self.assertEqual(secured.post('/api/setup/'+path+'/',{},content_type='application/json').status_code,403)
        self.client.force_login(self.admin)
        result=self.client.get('/api/setup/clouds/');self.assertEqual(result['Cache-Control'],'no-store')

    def test_encryption_redaction_preservation_and_revision(self):
        with patch.object(cloud,'caller_account',side_effect=AssertionError('No network on save')):
            row=self.create()
        self.assertNotIn('fixture-private-secret',row.ciphertext)
        self.assertEqual(cloud.decrypt(row)['secret_access_key'],'fixture-private-secret')
        data=self.data(id=str(row.pk),revision=1,label='Renamed');data.pop('secrets')
        self.assertEqual(self.post('clouds',data).status_code,200)
        self.assertEqual(self.post('clouds',data).status_code,409)
        row.refresh_from_db();self.assertEqual(cloud.decrypt(row)['secret_access_key'],'fixture-private-secret')
        output=self.client.get('/api/setup/clouds/').content.decode()+str(list(SecurityAudit.objects.values()))
        for value in ['fixture-private-secret','AKIA'+'X'*16]:self.assertNotIn(value,output)
        row.region='eu-west-1'
        with self.assertRaises(Exception):cloud.decrypt(row)

    def test_default_chain_needs_no_vault_and_no_outbound_on_get(self):
        self.key.unlink()
        row=self.create(mode='default',secrets=None)
        self.assertEqual(row.ciphertext,'')
        with patch.object(cloud,'caller_account',side_effect=AssertionError('No implicit check')):
            self.assertEqual(self.client.get('/api/setup/clouds/').status_code,200)
        self.assertEqual(self.post('clouds',self.data()).status_code,503)

    def test_expiry_validation_and_expired_check(self):
        values=self.data()['secrets']|{'session_token':'fixture-session-token'}
        for expiry in [None,'bad','2020-01-01T00:00:00Z','2099-01-01T00:00:00']:
            self.assertEqual(self.post('clouds',self.data(secrets=values,expires_at=expiry)).status_code,400)
        row=self.create(secrets=values,expires_at=(timezone.now()+timedelta(hours=1)).isoformat())
        row.expires_at=timezone.now()-timedelta(seconds=1);row.save()
        with patch.object(cloud,'caller_account') as call:
            self.assertEqual(self.check(row).status_code,400);call.assert_not_called()
        self.assertTrue(cloud.metadata(row)['expired'])

    def test_identity_match_and_throttle(self):
        row=self.create()
        with patch.object(cloud,'caller_account',return_value=row.account_id) as call:
            result=self.check(row);self.assertEqual(result.status_code,200);self.assertTrue(result.json()['check']['fresh'])
            self.assertEqual(self.check(row).status_code,429);self.assertEqual(call.call_count,1)
        row.refresh_from_db();row.check_finished_at=timezone.now()-timedelta(minutes=16)
        self.assertFalse(cloud.metadata(row)['check']['fresh'])

    def test_mismatch_and_error_redaction(self):
        row=self.create()
        with patch.object(cloud,'caller_account',return_value='999999999999'):
            self.assertEqual(self.check(row).json()['check']['status'],'account_mismatch')
        CloudCredential.objects.filter(pk=row.pk).update(check_started_at=timezone.now()-timedelta(minutes=2))
        with patch.object(cloud,'caller_account',side_effect=Exception('fixture-private-secret')):
            result=self.check(row);self.assertEqual(result.json()['check']['status'],'failed')
            self.assertNotIn('fixture-private-secret',result.content.decode()+str(list(SecurityAudit.objects.values())))

    def test_edit_race_cannot_verify_replacement(self):
        row=self.create()
        def race(_):
            cloud.save('operator',self.data(id=str(row.pk),revision=1,enabled=False))
            return row.account_id
        with patch.object(cloud,'caller_account',side_effect=race):self.assertEqual(self.check(row).status_code,409)
        row.refresh_from_db();self.assertFalse(row.enabled);self.assertEqual(cloud.metadata(row)['check']['status'],'outdated')
        with patch.object(cloud,'caller_account') as call:
            self.assertEqual(self.check(row).status_code,400);call.assert_not_called()

    def test_global_check_lease_and_recovery(self):
        row=self.create()
        CloudCredential.objects.filter(pk=row.pk).update(check_status='checking',check_revision=1,check_started_at=timezone.now())
        other=CloudCredential.objects.create(label='Other',mode='default',account_id='123456789012',revision=1)
        self.assertEqual(self.check(other).status_code,429)
        CloudCredential.objects.filter(pk=row.pk).update(check_started_at=timezone.now()-timedelta(minutes=2))
        row.refresh_from_db();self.assertEqual(cloud.metadata(row)['check']['status'],'interrupted')
        with patch.object(cloud,'caller_account',return_value=row.account_id):self.assertEqual(self.check(row).status_code,200)

    def test_invalid_provider_inputs_and_immutable_account(self):
        for changes in [{'account_id':'abc'},{'region':'https://evil.test'},{'mode':'azure'},{'enabled':'yes'},{'provider':'google'},{'secrets':{} }]:
            self.assertEqual(self.post('clouds',self.data(**changes)).status_code,400)
        row=self.create()
        self.assertEqual(self.post('clouds',self.data(id=str(row.pk),revision=1,account_id='999999999999')).status_code,400)

    def test_sdk_uses_fixed_https_endpoint_and_explicit_credentials(self):
        row=self.create()
        session=MagicMock();client=session.client.return_value;client.get_caller_identity.return_value={'Account':row.account_id}
        with patch.object(cloud.boto3,'Session',return_value=session) as factory:
            self.assertEqual(cloud.caller_account(row),row.account_id)
            self.assertEqual(factory.call_args.kwargs['aws_secret_access_key'],'fixture-private-secret')
            self.assertEqual(session.client.call_args.kwargs['endpoint_url'],'https://sts.us-east-1.amazonaws.com')
            client.close.assert_called_once()
