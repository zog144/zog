import base64
import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.test import Client, override_settings
from django.utils import timezone
from tests.host_registry.test_identity import IdentityTests
from zog.station_access.host_registry import vault, mirror_roles, identity
from zog.station_access.host_registry.models import StationCredential, MirrorRole, SecurityAudit

# Reuse signing helpers without inheriting the baseline test cases a second time.
from django.test import TestCase
@override_settings(HOST_IDENTITY_ORIGIN='https://registry.example.test',ALLOWED_HOSTS=['registry.example.test','testserver'])
class OperationsTests(TestCase):
    setUp=IdentityTests.setUp
    request=IdentityTests.request
    send=IdentityTests.send
    pending=IdentityTests.pending
    approved=IdentityTests.approved
    heartbeat=IdentityTests.heartbeat
    def configure(self):
        p=Path(self.root.name)/'vault.json'
        p.write_text(json.dumps({'active':'v1','keys':{'v1':base64.b64encode(os.urandom(32)).decode()}}));p.chmod(0o600)
        override=override_settings(HOST_VAULT_CONFIGURATION=str(p));override.enable();self.addCleanup(override.disable)
        return p
    def login_heartbeat(self,host,login):
        return self.send(self.request(f'/api/hosts/{host.pk}/heartbeat/',self.report|{'station_login':login},subject=str(host.pk)))
    def test_signed_vault_reveal_rotation_no_list_leak(self):
        self.configure();h=self.approved();login={'username':'station-admin','password':'UNIQUE-private-test-value'}
        self.assertEqual(self.login_heartbeat(h,login).status_code,200)
        row=StationCredential.objects.get(host=h);self.assertNotIn(login['password'],row.ciphertext)
        h.refresh_from_db();self.assertNotIn('station_login',h.report)
        self.client.force_login(self.admin)
        for url in ['/api/hosts/','/api/hosts/identities/']:
            result=self.client.get(url);self.assertEqual(result.status_code,200);self.assertNotIn(login['password'],result.content.decode());self.assertNotIn(row.ciphertext,result.content.decode())
        url=f'/api/hosts/{h.pk}/station-login/reveal/'
        reveal=self.client.post(url,json.dumps({'revision':row.revision}),content_type='application/json')
        self.assertEqual(reveal.status_code,200);self.assertEqual(reveal.json()['password'],login['password']);self.assertEqual(reveal['Cache-Control'],'no-store')
        self.assertTrue(SecurityAudit.objects.filter(action='reveal-station-login').exists())
        self.assertEqual(self.login_heartbeat(h,login).status_code,200);row.refresh_from_db();self.assertEqual(row.revision,1)
        self.login_heartbeat(h,login|{'password':'replacement'});row.refresh_from_db();self.assertEqual(row.revision,2)
        self.assertEqual(self.client.post(url,json.dumps({'revision':1}),content_type='application/json').status_code,409)
        self.send(self.heartbeat(h));self.assertTrue(StationCredential.objects.filter(host=h).exists())
        self.login_heartbeat(h,None);self.assertFalse(StationCredential.objects.filter(host=h).exists())
    def test_pending_and_revoked_cannot_store_credentials(self):
        self.configure();login={'username':'station-admin','password':'secret-only-in-signed-body'}
        value={'public_key':__import__('zog.host_identify.signatures',fromlist=['public_text']).public_text(self.key.public_key()),'claimed_host_id':'','report':self.report|{'station_login':login}}
        self.assertNotEqual(self.send(self.request('/api/hosts/enrollment/',value)).status_code,202)
        self.assertFalse(StationCredential.objects.exists())
        h=self.approved();identity.revoke('admin',self.fp)
        self.assertEqual(self.login_heartbeat(h,login).status_code,401);self.assertFalse(StationCredential.objects.exists())
    def test_vault_authentication_aad_permissions_and_missing_key(self):
        path=self.configure();h=self.approved();login={'username':'station-admin','password':'secret'}
        self.login_heartbeat(h,login);row=StationCredential.objects.get(host=h)
        url=f'/api/hosts/{h.pk}/station-login/reveal/'
        self.assertNotEqual(self.client.post(url,'{"revision":1}',content_type='application/json').status_code,200)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url,'{"revision":1}',content_type='application/json').status_code,403)
        from django.contrib.auth import get_user_model
        user=get_user_model().objects.create_user('ordinary',password='test');self.client.force_login(user)
        self.assertEqual(self.client.post(url,'{"revision":1}',content_type='application/json').status_code,403)
        _,keys=vault.keyring();row.revision+=1
        with self.assertRaises(Exception):vault.decrypt(row,keys)
        path.unlink();self.assertEqual(self.login_heartbeat(h,login).status_code,503)
    def test_role_assignment_ack_readiness_removal_retains_reservation(self):
        h=self.approved()
        r=mirror_roles.assign('admin',h.pk,True,'https://mirror.example.test',0)
        self.assertFalse(mirror_roles.serialize(h)['ready'])
        self.assertIsNone(self.send(self.heartbeat(h)).json()['archive'])
        status={'revision':r.revision,'state':'ready','reason':'','runtime_id':'runtime-1'}
        self.assertEqual(self.send(self.request(f'/api/hosts/{h.pk}/heartbeat/',self.report|{'mirror_status':status},subject=str(h.pk))).status_code,200)
        h.refresh_from_db();self.assertTrue(mirror_roles.serialize(h)['ready'])
        MirrorRole.objects.filter(host=h).update(observed_at=timezone.now()-timedelta(minutes=4))
        self.assertFalse(mirror_roles.serialize(h)['ready'])
        r=mirror_roles.assign('admin',h.pk,False,'',1)
        self.assertEqual(r.endpoint,'https://mirror.example.test');self.assertEqual(r.revision,2)
        self.assertFalse(mirror_roles.response(h)['desired']['selected']);self.assertTrue(mirror_roles.response(h)['desired']['retain_archives'])
        self.assertEqual(mirror_roles.response(h)['candidates'],[])
    def test_role_api_requires_admin_csrf_and_approved_key(self):
        h=self.approved();url=f'/api/hosts/{h.pk}/mirror-role/';data={'selected':True,'endpoint':'https://mirror.example.test','revision':0}
        self.assertNotEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,200)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url,json.dumps(data),content_type='application/json').status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,200)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,400)
        identity.revoke('admin',self.fp)
        self.assertEqual(mirror_roles.response(h)['candidates'],[])
        with self.assertRaises(ValueError):mirror_roles.assign('admin',h.pk,True,'https://mirror2.example.test',1)
    def test_revoke_during_verification_prevents_vault_write(self):
        self.configure();h=self.approved();proof=identity.proof
        def race(*args,**kwargs):
            result=proof(*args,**kwargs);identity.revoke('admin',self.fp);return result
        with patch('zog.station_access.host_registry.identity.proof',side_effect=race):
            self.assertEqual(self.login_heartbeat(h,{'username':'station-admin','password':'private'}).status_code,401)
        self.assertFalse(StationCredential.objects.exists())

    def test_export_verifies_current_password_and_writes_private_file(self):
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        get_user_model().objects.create_superuser('station-admin',password='synthetic-current-password')
        root=Path(self.root.name);source=root/'FIRST-LOGIN.txt';target=root/'station-login.json'
        source.write_text('Username: station-admin\nPassword: synthetic-current-password\n');source.chmod(0o600)
        output=StringIO();call_command('export_station_login',source=str(source),output=str(target),stdout=output)
        self.assertEqual(target.stat().st_mode&0o777,0o600);self.assertNotIn('synthetic-current-password',output.getvalue())
        source.write_text('Username: station-admin\nPassword: old-password\n')
        with self.assertRaises(CommandError):call_command('export_station_login',source=str(source),output=str(target),stdout=output)
        self.assertEqual(json.loads(target.read_text())['password'],'synthetic-current-password')

    def test_multiple_providers_and_duplicate_endpoint_conflict(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from zog.host_identify.signatures import fingerprint
        first=self.approved();mirror_roles.assign('admin',first.pk,True,'https://one.example.test',0)
        self.key=Ed25519PrivateKey.generate();self.fp=fingerprint(self.key.public_key());second=self.approved()
        with self.assertRaises(ValueError):mirror_roles.assign('admin',second.pk,True,'https://one.example.test',0)
        mirror_roles.assign('admin',second.pk,True,'https://two.example.test',0)
        result=self.send(self.heartbeat(second)).json()
        self.assertEqual(len(result['mirror_roles']['candidates']),2);self.assertIsNone(result['archive'])
        self.assertTrue(all(not item['ready'] for item in result['mirror_roles']['candidates']))
        with self.assertRaises(ValueError):mirror_roles.assign('admin',second.pk,True,'https://two.example.test/path',1)

del IdentityTests
