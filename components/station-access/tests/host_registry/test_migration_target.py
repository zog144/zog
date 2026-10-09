import uuid
from django.test import TestCase,override_settings
from tests.host_registry.test_identity import IdentityTests
from zog.station_access.host_registry.models import Host,HostIdentity,EnrollmentRequest,SecurityAudit
from zog.station_access.host_registry import identity

@override_settings(HOST_IDENTITY_ORIGIN='https://registry.example.test',ALLOWED_HOSTS=['registry.example.test','testserver'])
class MigrationTargetTests(TestCase):
    setUp=IdentityTests.setUp
    request=IdentityTests.request
    send=IdentityTests.send
    pending=IdentityTests.pending
    heartbeat=IdentityTests.heartbeat
    def test_claim_rejects_new_host_or_wrong_target_without_side_effects(self):
        target=Host.objects.create(label='Keep this label');other=Host.objects.create(label='Other')
        self.assertEqual(self.pending(claimed=str(target.pk)).status_code,202)
        before=Host.objects.count()
        for choice in [None,'',other.pk]:
            with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,choice)
            self.assertEqual(Host.objects.count(),before);self.assertFalse(HostIdentity.objects.exists())
            self.assertTrue(EnrollmentRequest.objects.filter(pk=self.fp,status='pending').exists())
            self.assertFalse(SecurityAudit.objects.filter(action='approve-key').exists())
        approved=identity.approve('admin',self.fp,self.fp,target.pk)
        self.assertEqual(approved.pk,target.pk);self.assertEqual(approved.label,'Keep this label')
        self.assertEqual(Host.objects.count(),before);self.assertEqual(self.send(self.heartbeat(approved)).status_code,200)
    def test_claim_missing_record_does_not_create_replacement(self):
        claimed=uuid.uuid4();self.pending(claimed=str(claimed))
        for target in [None,claimed]:
            with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,target)
        self.assertEqual(Host.objects.count(),0)
    def test_unclaimed_new_host_still_requires_exact_fingerprint(self):
        self.pending()
        with self.assertRaises(ValueError):identity.approve('admin',self.fp,'wrong')
        host=identity.approve('admin',self.fp,self.fp)
        self.assertEqual(HostIdentity.objects.get(pk=self.fp).host_id,host.pk)
    def test_api_rejects_omitted_target_even_with_admin_and_fingerprint(self):
        import json
        target=Host.objects.create();self.pending(claimed=str(target.pk));self.client.force_login(self.admin)
        response=self.client.post('/api/hosts/identities/decision/',json.dumps({'action':'approve','fingerprint':self.fp,'confirmed_fingerprint':self.fp}),content_type='application/json')
        self.assertEqual(response.status_code,400);self.assertEqual(response.json()['code'],'migration_target_mismatch')
        self.assertEqual(Host.objects.count(),1);self.assertFalse(HostIdentity.objects.exists())
    def test_previously_misbound_key_is_not_rebound_implicitly(self):
        intended=Host.objects.create();wrong=Host.objects.create()
        self.pending(claimed=str(wrong.pk));identity.approve('prior-admin',self.fp,self.fp,wrong.pk)
        response=self.pending(claimed=str(intended.pk))
        self.assertEqual(response.status_code,409)
        self.assertEqual(HostIdentity.objects.get(pk=self.fp).host_id,wrong.pk)
        self.assertEqual(self.pending(claimed=str(wrong.pk)).status_code,200)

del IdentityTests
