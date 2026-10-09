import copy
import json
import tempfile
import uuid
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import signatures, archive
from zog.station_access.host_registry.models import Host, HostIdentity, EnrollmentRequest, ReplayRecord, SecurityAudit, DnsAssignment
from zog.station_access.host_registry import identity
from zog.station_access.host_registry.services import enroll
from zog.station_access.host_registry.dns_reconcile import desired

ORIGIN='https://registry.example.test'
@override_settings(HOST_IDENTITY_ORIGIN=ORIGIN, ALLOWED_HOSTS=['registry.example.test','testserver'])
class IdentityTests(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('admin',password='test-only')
        self.key=Ed25519PrivateKey.generate();self.fp=signatures.fingerprint(self.key.public_key())
        self.report={'version':1,'hostname':'compiler'}
        self.root=tempfile.TemporaryDirectory();self.addCleanup(self.root.cleanup)
        root=Path(self.root.name)
        self.signing=Ed25519PrivateKey.generate()
        p=root/'archive-signing.pem';p.write_bytes(self.signing.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));p.chmod(0o600)
        c=root/'archive.json';c.write_text(json.dumps({'mirror':'https://mirror.example.test','issuer':ORIGIN,'audience':'zog-mirror','key_id':'archive-1','private_key_file':str(p)}))
        self.override=override_settings(HOST_ARCHIVE_CONFIGURATION=str(c));self.override.enable();self.addCleanup(self.override.disable)
    def request(self,path,payload,key=None,subject='pending',**kwargs):
        return signatures.sign(ORIGIN+path,json.dumps(payload).encode(),key or self.key,subject,**kwargs)
    def send(self,message,client=None,body=None,**headers):
        values={'HTTP_'+k.upper().replace('-','_'):v for k,v in message.headers.items() if k.lower() not in ['content-type','content-length']}
        values.update(headers)
        values.setdefault('HTTP_HOST','registry.example.test')
        return (client or self.client).post(message.path_url,body if body is not None else message.body,content_type='application/json',**values)
    def pending(self,key=None,claimed=''):
        key=key or self.key
        data={'public_key':signatures.public_text(key.public_key()),'claimed_host_id':claimed,'report':self.report}
        return self.send(self.request('/api/hosts/enrollment/',data,key,claimed or 'pending'))
    def approved(self,target=None):
        self.assertEqual(self.pending(claimed=str(target) if target else '').status_code,202)
        return identity.approve('admin',self.fp,self.fp,target)
    def heartbeat(self,host,key=None):
        return self.request(f'/api/hosts/{host.pk}/heartbeat/',self.report,key,str(host.pk))
    def host_generation(self):
        return {
            'schema': 1,
            'source': 'verified-host-install-state-v1',
            'installation': {
                'installation_id': '00000001-0001-4001-8001-000000000001',
                'record_id': '00000005-0005-4005-8005-000000000005',
                'record_schema': 1,
                'operation': 'fresh',
            },
            'selected_slot': 'HOST-A',
            'booted_slot': None,
            'slots': {
                'HOST-A': {
                    'generation': 'generation-a',
                    'root_partuuid': '00000009-0009-4009-8009-000000000009',
                },
                'HOST-B': None,
            },
            'transitional_boot_bundle': {
                'kind': 'foreign',
                'provider': 'amazon-linux-2023',
                'record_reference': '00000007-0007-4007-8007-000000000007',
                'record_sha256': 'b' * 64,
            },
        }

    def test_signed_heartbeat_persists_verified_host_generation(self):
        self.report['host_generation'] = self.host_generation()
        host = self.approved()
        response = self.send(self.heartbeat(host))
        self.assertEqual(response.status_code, 200)
        host.refresh_from_db()
        self.assertEqual(host.report['host_generation'], self.host_generation())
        self.assertEqual(host.report['host_generation']['selected_slot'], 'HOST-A')
        self.assertIsNone(host.report['host_generation']['booted_slot'])

    def test_malformed_signed_host_generation_is_rejected_without_replacing_report(self):
        host = self.approved()
        self.assertEqual(self.send(self.heartbeat(host)).status_code, 200)
        host.refresh_from_db()
        before = copy.deepcopy(host.report)
        self.report['host_generation'] = self.host_generation()
        self.report['host_generation']['slots']['HOST-A']['generation'] = '../not-a-generation'
        self.assertEqual(self.send(self.heartbeat(host)).status_code, 401)
        host.refresh_from_db()
        self.assertEqual(host.report, before)

    def test_legacy_bearer_heartbeat_cannot_submit_host_generation(self):
        host, token = enroll(label='legacy-provenance')
        host.legacy_until = timezone.now() + timedelta(hours=1)
        host.save(update_fields=['legacy_until'])
        report = {'version': 1, 'hostname': 'legacy', 'host_generation': self.host_generation()}
        path = f'/api/hosts/{host.pk}/heartbeat/'
        result = self.client.post(
            path, json.dumps(report), content_type='application/json',
            HTTP_AUTHORIZATION='Bearer ' + token,
        )
        self.assertEqual(result.status_code, 400)
        host.refresh_from_db()
        self.assertNotIn('host_generation', host.report)

    def test_signed_dns_snapshot_is_written_only_after_verified_heartbeat(self):
        h=self.approved()
        self.assertEqual(self.send(self.heartbeat(h)).status_code,200)
        h.refresh_from_db()
        self.assertEqual(h.signed_dns_fingerprint,self.fp)
        self.assertEqual(h.signed_dns_report,{'cloud':{},'public_ip':''})
        self.assertLessEqual(h.signed_dns_observed_at,h.signed_last_received)
        saved=(h.signed_dns_report,h.signed_dns_observed_at,h.signed_dns_fingerprint)
        self.assertEqual(self.send(self.heartbeat(h),body=b'{}').status_code,401)
        h.refresh_from_db()
        self.assertEqual(saved,(h.signed_dns_report,h.signed_dns_observed_at,h.signed_dns_fingerprint))

    def test_demonstration_pending_approval_scoped_download(self):
        self.assertEqual(self.pending().status_code,202);self.assertEqual(Host.objects.count(),0)
        self.assertEqual(HostIdentity.objects.count(),0)
        h=identity.approve('admin',self.fp,self.fp)
        result=self.send(self.heartbeat(h));self.assertEqual(result.status_code,200);self.assertIsNone(result.json()['archive'])
        identity.set_policy('admin',h.pk,['download'],['sources'])
        result=self.send(self.heartbeat(h));self.assertEqual(result.status_code,200);self.assertEqual(result['Cache-Control'],'no-store')
        grant=result.json()['archive'];claims=archive.verify(grant['token'],{'archive-1':self.signing.public_key()},ORIGIN,'zog-mirror','download','sources')
        self.assertEqual(claims['sub'],str(h.pk));self.assertEqual(claims['exp']-claims['iat'],900)
        with self.assertRaises(PermissionError):archive.verify(grant['token'],{'archive-1':self.signing.public_key()},ORIGIN,'zog-mirror','list','sources')
        second=self.send(self.heartbeat(h)).json()['archive'];self.assertNotEqual(second['token'],grant['token'])
    def test_pending_dedup_expiry_rejection(self):
        self.pending();self.pending();self.assertEqual(EnrollmentRequest.objects.count(),1)
        identity.reject('admin',self.fp)
        self.assertEqual(self.pending().status_code,403)
        with self.assertRaises(EnrollmentRequest.DoesNotExist):identity.approve('admin',self.fp,self.fp)
        EnrollmentRequest.objects.filter(pk=self.fp).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.pending().status_code,202)
    @override_settings(HOST_PENDING_LIMIT=1)
    def test_pending_storage_bounded(self):
        self.pending();self.assertEqual(self.pending(Ed25519PrivateKey.generate()).status_code,429)
    @override_settings(HOST_ENROLLMENT_PER_ADDRESS=1)
    def test_persistent_rate_limit(self):
        self.pending();self.assertEqual(self.pending().status_code,429)
    def test_forged_and_altered_requests(self):
        h=self.approved();message=self.heartbeat(h)
        self.assertEqual(self.send(message,body=b'{"version":1,"hostname":"altered"}').status_code,401)
        wrong=self.heartbeat(h,Ed25519PrivateKey.generate());self.assertEqual(self.send(wrong).status_code,401)
        message.headers['X-Host-Id']=str(uuid.uuid4());self.assertEqual(self.send(message).status_code,401)
    def test_digest_recomputed_signature_cannot_hide_modified_body(self):
        h=self.approved();message=self.heartbeat(h);message.body=b'{}'
        self.assertEqual(self.send(message).status_code,401)
    def test_destination_path_method_and_profile_bound(self):
        h=self.approved();m=self.heartbeat(h)
        self.assertEqual(self.send(m,HTTP_X_FORWARDED_HOST='registry.example.test',HTTP_HOST_OVERRIDE='evil').status_code,200)
        m=self.heartbeat(h);m.url=m.url.replace(str(h.pk),str(uuid.uuid4()));self.assertEqual(self.send(m).status_code,401)
        m=self.heartbeat(h);m.headers['Signature-Input']=m.headers['Signature-Input'].replace('"@method" ','');self.assertEqual(self.send(m).status_code,401)
        m=self.request(f'/api/hosts/{h.pk}/heartbeat/',self.report,subject=str(h.pk),now=timezone.now()-timedelta(minutes=5));self.assertEqual(self.send(m).status_code,401)
    def test_replay_rejected_by_new_worker_client(self):
        h=self.approved();m=self.heartbeat(h)
        self.assertEqual(self.send(m).status_code,200)
        self.assertEqual(self.send(m,client=Client()).status_code,401)
        self.assertTrue(ReplayRecord.objects.filter(fingerprint=self.fp).exists())
    def test_substitution_requires_new_explicit_decision(self):
        h=self.approved();new=Ed25519PrivateKey.generate();fp=signatures.fingerprint(new.public_key())
        self.assertEqual(self.pending(new,str(h.pk)).status_code,202)
        with self.assertRaises(ValueError):identity.approve('admin',fp,fp,h.pk)
        self.assertEqual(HostIdentity.objects.get(pk=self.fp).status,'approved')
        identity.revoke('admin',self.fp);identity.approve('admin',fp,fp,h.pk)
        self.assertEqual(self.send(self.heartbeat(h)).status_code,401)
        self.assertEqual(self.send(self.heartbeat(h,new)).status_code,200)
    def test_revocation_between_verification_and_commit(self):
        h=self.approved();identity.set_policy('admin',h.pk,['download'],['sources'])
        original=identity.proof
        def raced(*args):
            result=original(*args);identity.revoke('admin',self.fp);return result
        with patch('zog.station_access.host_registry.identity.proof',side_effect=raced):
            result=self.send(self.heartbeat(h))
        self.assertEqual(result.status_code,401);h.refresh_from_db();self.assertIsNone(h.signed_last_received)
    def test_policy_withdrawal_and_revocation(self):
        h=self.approved();identity.set_policy('admin',h.pk,['download'],['sources'])
        token=self.send(self.heartbeat(h)).json()['archive']['token']
        identity.set_policy('admin',h.pk,[],[]);self.assertIsNone(self.send(self.heartbeat(h)).json()['archive'])
        identity.revoke('admin',self.fp);self.assertEqual(self.send(self.heartbeat(h)).status_code,401)
        # Previously issued token remains valid until expiry; verifier has no revocation feed.
        archive.verify(token,{'archive-1':self.signing.public_key()},ORIGIN,'zog-mirror','download','sources')
    def test_admin_permissions_csrf_exact_fingerprint(self):
        self.pending();url='/api/hosts/identities/decision/'
        data={'action':'approve','fingerprint':self.fp,'confirmed_fingerprint':self.fp}
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,401)
        user=get_user_model().objects.create_user('ordinary');self.client.force_login(user)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url,json.dumps(data),content_type='application/json').status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url,json.dumps(data|{'confirmed_fingerprint':'wrong'}),content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,200)
        self.assertEqual(SecurityAudit.objects.get(action='approve-key').actor,str(self.admin.pk)+':admin')
    def test_migration_preserves_uuid_label_dns_no_implicit_approval(self):
        h,token=enroll(label='Keep label');h.report={'hostname':'history'};h.save()
        DnsAssignment.objects.create(host=h,name='fixed.hosts.example.test',owner_id='original-owner')
        path=f'/api/hosts/{h.pk}/heartbeat/'
        self.assertEqual(self.client.post(path,json.dumps(self.report),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+token).status_code,401)
        h.legacy_until=timezone.now()+timedelta(hours=1);h.save()
        legacy=self.client.post(path,json.dumps(self.report),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+token)
        self.assertEqual(legacy.status_code,200);self.assertNotIn('archive',legacy.json());self.assertEqual(HostIdentity.objects.count(),0)
        self.assertEqual(desired(h,True,timezone.now())[0],'waiting')
        approved=self.approved(h.pk);self.assertEqual(approved.pk,h.pk);self.assertEqual(approved.label,'Keep label')
        self.assertEqual(approved.dns_assignment.owner_id,'original-owner')
        self.assertEqual(self.client.post(path,json.dumps(self.report),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+token).status_code,401)
    def test_no_secrets_in_administrative_responses_or_audit(self):
        h=self.approved();identity.set_policy('admin',h.pk,['download'],['sources']);token=self.send(self.heartbeat(h)).json()['archive']['token']
        self.client.force_login(self.admin)
        for url in ['/api/hosts/','/api/hosts/identities/']:
            text=self.client.get(url).content.decode();self.assertNotIn(token,text);self.assertNotIn('PRIVATE KEY',text);self.assertNotIn('token_digest',text)
    def test_replay_capacity_fails_closed(self):
        h=self.approved()
        with override_settings(HOST_REPLAY_LIMIT=0):self.assertEqual(self.send(self.heartbeat(h)).status_code,401)
    def test_valid_signature_with_incomplete_coverage_rejected(self):
        from http_message_signatures import HTTPMessageSigner, algorithms
        h=self.approved();m=self.heartbeat(h)
        HTTPMessageSigner(signature_algorithm=algorithms.ED25519,key_resolver=signatures.Resolver(self.key,self.fp)).sign(
            m,key_id=self.fp,covered_component_ids=('content-digest',),nonce='x'*32,tag=signatures.TAG,label='host',expires=timezone.now()+timedelta(seconds=120))
        self.assertEqual(self.send(m).status_code,401)
    @override_settings(ALLOWED_HOSTS=['registry.example.test','other.example.test'])
    def test_wrong_external_authority_and_forwarded_headers_cannot_authorize(self):
        h=self.approved();m=self.heartbeat(h);m.url=m.url.replace('registry.example.test','other.example.test')
        self.assertEqual(self.send(m,HTTP_HOST='other.example.test',HTTP_X_FORWARDED_HOST='registry.example.test').status_code,401)
        m=signatures.sign('https://other.example.test'+f'/api/hosts/{h.id}/heartbeat/',json.dumps(self.report).encode(),self.key,str(h.id))
        self.assertEqual(self.send(m,HTTP_X_FORWARDED_HOST='other.example.test').status_code,401)
    def test_expired_pending_cannot_be_approved_and_does_not_create_host(self):
        self.pending();EnrollmentRequest.objects.filter(pk=self.fp).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(EnrollmentRequest.DoesNotExist):identity.approve('admin',self.fp,self.fp)
        self.assertEqual(Host.objects.count(),0)
    def test_legacy_window_command_is_bounded_and_not_extendable(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        h,_=enroll(label='legacy')
        with self.assertRaises(CommandError):call_command('allow_legacy_host',str(h.pk),hours=169,actor='admin')
        call_command('allow_legacy_host',str(h.pk),hours=1,actor='admin')
        with self.assertRaises(CommandError):call_command('allow_legacy_host',str(h.pk),hours=2,actor='admin')
        self.assertFalse(HostIdentity.objects.exists())
    def test_unapproved_key_cannot_beacon_to_inventory_host(self):
        h,_=enroll(account_id='123456789012',region='us-east-1',instance_id='i-inventory')
        self.pending(claimed=str(h.pk))
        self.assertEqual(self.send(self.heartbeat(h)).status_code,401)
        self.assertFalse(HostIdentity.objects.exists())
    def test_issuer_error_fails_closed_without_credential_in_response(self):
        h=self.approved();identity.set_policy('admin',h.pk,['download'],['sources'])
        with override_settings(HOST_ARCHIVE_CONFIGURATION='/missing/issuer-config'):
            result=self.send(self.heartbeat(h))
        self.assertEqual(result.status_code,503);self.assertNotIn('token',result.json())
    def test_signature_expiry_rechecked_after_lock_wait(self):
        with identity.locked(),self.assertRaises(ValueError):
            identity.consume(self.fp,'x'*32,timezone.now()-timedelta(seconds=1))
