import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from tests.host_registry.test_identity import IdentityTests
from zog.station_access.host_registry.models import Host, HostIdentity, EnrollmentRequest, SecurityAudit, InventoryScan, StationCredential, ArchivePolicy, MirrorRole, DnsAssignment
from zog.station_access.host_registry import identity, matching, retirement
from zog.station_access.host_registry.inventory import commit_region

CLOUD={'account_id':'123456789012','region':'us-east-1','instance_id':'i-0123456789abcdef0'}

@override_settings(HOST_IDENTITY_ORIGIN='https://registry.example.test',ALLOWED_HOSTS=['registry.example.test','testserver'])
class MatchingRemovalTests(TestCase):
    setUp=IdentityTests.setUp
    request=IdentityTests.request
    send=IdentityTests.send
    pending=IdentityTests.pending
    heartbeat=IdentityTests.heartbeat

    def aws(self):return Host.objects.create(provider='aws',label='Inventory label',**CLOUD)
    def match(self):return matching.resolve(EnrollmentRequest.objects.get(pk=self.fp))
    def test_signed_aws_enrollment_matches_inventory_and_preserves_record(self):
        host=self.aws();self.report['cloud']=CLOUD
        self.assertEqual(self.pending().status_code,202)
        self.assertEqual(self.match()['host']['id'],str(host.pk))
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp)
        with self.assertRaises(ValueError):identity.approve('admin',self.fp,'wrong',host.pk)
        result=identity.approve('admin',self.fp,self.fp,host.pk)
        self.assertEqual(result.pk,host.pk);self.assertEqual(result.label,'Inventory label')
        self.assertEqual(Host.objects.count(),1);self.assertEqual(self.send(self.heartbeat(host)).status_code,200)
        self.assertEqual(identity.approve('admin',self.fp,self.fp,host.pk).pk,host.pk)
        self.assertEqual(SecurityAudit.objects.filter(action='approve-key').count(),1)
    def test_no_match_creates_cloud_fields_and_repeated_creation_is_idempotent(self):
        self.report['cloud']=CLOUD;self.pending();self.assertEqual(self.match()['status'],'new')
        host=identity.approve('admin',self.fp,self.fp)
        self.assertEqual(host.provider,'aws');self.assertEqual(host.account_id,CLOUD['account_id'])
        self.assertEqual(host.region,CLOUD['region']);self.assertEqual(host.instance_id,CLOUD['instance_id'])
        self.assertEqual(self.send(self.heartbeat(host)).status_code,200)
        self.assertEqual(identity.approve('admin',self.fp,self.fp).pk,host.pk)
        self.assertEqual(Host.objects.count(),1)
    def test_exact_triple_not_instance_only(self):
        host=self.aws();self.report['cloud']=dict(CLOUD,account_id='999999999999');self.pending()
        self.assertEqual(self.match()['status'],'new')
        created=identity.approve('admin',self.fp,self.fp);self.assertNotEqual(created.pk,host.pk)
    def test_consistent_migration_and_conflicting_claim(self):
        host=self.aws();self.report['cloud']=CLOUD;self.pending(claimed=str(host.pk))
        self.assertEqual(self.match()['status'],'existing')
        other=Host.objects.create(label='Wrong')
        EnrollmentRequest.objects.filter(pk=self.fp).update(claimed_host_id=str(other.pk))
        self.assertEqual(self.match()['status'],'conflict')
        for choice in [None,host.pk,other.pk]:
            with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,choice)
        self.assertFalse(HostIdentity.objects.exists())
    def test_multiple_matches_block_instead_of_selecting_first(self):
        self.aws();Host.objects.create(provider='generic',**CLOUD)
        self.report['cloud']=CLOUD;self.pending()
        self.assertEqual(self.match()['status'],'conflict');self.assertEqual(len(self.match()['candidates']),2)
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp)
    def test_inventory_arrives_between_preview_and_approval(self):
        self.report['cloud']=CLOUD;self.pending();self.assertEqual(self.match()['status'],'new')
        host=self.aws()
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp)
        self.assertEqual(identity.approve('admin',self.fp,self.fp,host.pk).pk,host.pk)
    def test_bound_fingerprint_cannot_transfer_or_resurrect_revoked_key(self):
        self.pending();host=identity.approve('admin',self.fp,self.fp);other=Host.objects.create()
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,other.pk)
        identity.revoke('admin',self.fp)
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,host.pk)
    def test_invalid_cloud_or_forged_enrollment_does_not_create_pending(self):
        self.report['cloud']=dict(CLOUD,account_id='not-an-account')
        self.assertEqual(self.pending().status_code,401);self.assertFalse(EnrollmentRequest.objects.exists())
        self.report['cloud']=CLOUD
        payload={'public_key':'bad','claimed_host_id':'','report':self.report}
        self.assertEqual(self.send(self.request('/api/hosts/enrollment/',payload)).status_code,401)
        self.assertFalse(EnrollmentRequest.objects.exists())
    def test_unused_duplicate_archives_preserving_history_and_restores(self):
        host=Host.objects.create(label='Duplicate',report={'hostname':'compiler'})
        audit=SecurityAudit.objects.create(actor='old',action='migrate',host_id_text=str(host.pk))
        before=retirement.preview(host);self.assertTrue(before['can_archive'])
        retirement.archive_host('admin',host.pk,before['revision']);host.refresh_from_db()
        self.assertIsNotNone(host.archived_at);self.assertEqual(host.report,{'hostname':'compiler'})
        self.assertTrue(SecurityAudit.objects.filter(pk=audit.pk).exists())
        self.assertTrue(SecurityAudit.objects.filter(action='archive-host',host_id_text=str(host.pk)).exists())
        self.pending(claimed=str(host.pk));self.assertEqual(self.match()['status'],'conflict')
        retirement.restore_host('admin',host.pk,retirement.preview(host)['revision']);host.refresh_from_db()
        self.assertIsNone(host.archived_at);self.assertFalse(HostIdentity.objects.exists())
        self.assertEqual(self.match()['status'],'existing')
    def test_each_active_dependency_blocks_without_side_effects(self):
        host=Host.objects.create();now=timezone.now()
        creators=[
            lambda:HostIdentity.objects.create(host=host,fingerprint=self.fp,public_key='public',approved_by='admin',approved_at=now),
            lambda:StationCredential.objects.create(host=host,key_id='test',ciphertext='sensitive',source_fingerprint=self.fp,changed_at=now,received_at=now),
            lambda:ArchivePolicy.objects.create(host=host,operations=['download'],collections=['sources']),
            lambda:MirrorRole.objects.create(host=host,selected=True,changed_at=now),
            lambda:DnsAssignment.objects.create(host=host,name='keep.example.test',owner_id='keep',enabled=False),
            lambda:EnrollmentRequest.objects.create(fingerprint=self.fp,public_key='public',claimed_host_id=str(host.pk),expires_at=now+timedelta(hours=1))]
        for create in creators:
            row=create();preview=retirement.preview(host)
            self.assertFalse(preview['can_archive']);self.assertTrue(preview['blockers'])
            self.assertNotIn('sensitive',json.dumps(preview,default=str));self.assertNotIn('ciphertext',preview)
            with self.assertRaises(retirement.RemovalConflict):retirement.archive_host('admin',host.pk,preview['revision'])
            host.refresh_from_db();self.assertIsNone(host.archived_at);self.assertTrue(type(row).objects.filter(pk=row.pk).exists());row.delete()
        host.token_digest='secret-digest';host.save()
        self.assertFalse(retirement.preview(host)['can_archive']);self.assertNotIn('secret-digest',json.dumps(retirement.preview(host),default=str))
    def test_revoked_identity_retained_and_recent_tokens_block_until_expiry(self):
        host=Host.objects.create();now=timezone.now()
        key=HostIdentity.objects.create(host=host,fingerprint=self.fp,public_key='public',status='revoked',approved_by='admin',approved_at=now,revoked_at=now)
        self.assertFalse(retirement.preview(host)['can_archive'])
        with patch('zog.station_access.host_registry.retirement.timezone.now',return_value=now+timedelta(seconds=906)):
            preview=retirement.preview(host);self.assertTrue(preview['can_archive']);retirement.archive_host('admin',host.pk,preview['revision'])
        self.assertTrue(HostIdentity.objects.filter(pk=key.pk,status='revoked').exists())
    def test_stale_preview_cannot_archive_new_dependency(self):
        host=Host.objects.create();preview=retirement.preview(host)
        ArchivePolicy.objects.create(host=host,operations=['download'],collections=['sources'])
        with self.assertRaises(retirement.RemovalConflict):retirement.archive_host('admin',host.pk,preview['revision'])
    def test_inventory_updates_archived_record_without_recreating_it(self):
        host=self.aws();retirement.archive_host('admin',host.pk,retirement.preview(host)['revision'])
        record=InventoryScan.objects.create(scope='test')
        commit_region(CLOUD['account_id'],CLOUD['region'],[{'InstanceId':CLOUD['instance_id'],'State':{'Name':'running'}}],record)
        host.refresh_from_db();self.assertIsNotNone(host.archived_at);self.assertEqual(host.aws_observation['state'],'running');self.assertEqual(Host.objects.count(),1)
    def test_removal_admin_csrf_and_uuid_confirmation(self):
        host=Host.objects.create();url=f'/api/hosts/{host.pk}/removal/'
        data={'action':'archive','revision':retirement.preview(host)['revision'],'confirmed_host_id':str(host.pk)}
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,401)
        self.client.force_login(get_user_model().objects.create_user('ordinary'))
        self.assertEqual(self.client.get(f'/api/hosts/{host.pk}/removal-preview/').status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url,json.dumps(data),content_type='application/json').status_code,403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url,json.dumps(data|{'confirmed_host_id':'wrong'}),content_type='application/json').status_code,400)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type='application/json').status_code,200)
        preview=self.client.get(f'/api/hosts/{host.pk}/removal-preview/')
        self.assertEqual(preview['Cache-Control'],'no-store');self.assertTrue(preview.json()['archived_at'])
    def test_duplicate_hints_do_not_mutate_or_authorize(self):
        first=Host.objects.create(report={'hostname':'same'});second=self.aws();second.report={'hostname':'same'};second.save()
        hints=retirement.duplicate_candidates([first,second]);self.assertEqual(hints[str(first.pk)][0]['id'],str(second.pk))
        self.pending();self.assertEqual(self.match()['status'],'new');self.assertEqual(Host.objects.count(),2)

    def test_idle_duplicate_without_heartbeat_is_a_review_candidate(self):
        host=self.aws();host.aws_observation={'private_dns':'compiler.internal'};host.save()
        duplicate=Host.objects.create(label='compiler.internal')
        candidates=retirement.duplicate_candidates([host,duplicate])
        self.assertEqual(candidates[str(duplicate.pk)][0]['id'],str(host.pk))
        self.report['hostname']='compiler.internal';self.pending()
        self.assertEqual(self.match()['status'],'new')  # Name equality is never identity matching.
    def test_stopped_acknowledged_role_history_is_retained_on_archive(self):
        host=Host.objects.create()
        role=MirrorRole.objects.create(host=host,selected=False,revision=2,acknowledged_revision=2,reported_state='stopped',changed_at=timezone.now())
        retirement.archive_host('admin',host.pk,retirement.preview(host)['revision'])
        self.assertTrue(MirrorRole.objects.filter(pk=role.pk).exists())
    def test_pending_creation_requires_verified_signature(self):
        from zog.host_identify import signatures
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        wrong=Ed25519PrivateKey.generate()
        payload={'public_key':signatures.public_text(self.key.public_key()),'claimed_host_id':'','report':self.report}
        result=self.send(self.request('/api/hosts/enrollment/',payload,key=wrong))
        self.assertEqual(result.status_code,401);self.assertFalse(EnrollmentRequest.objects.exists())

    def test_signed_pending_hint_correction_preserves_expiry_and_requires_approval(self):
        host=self.aws();wrong=Host.objects.create();self.report['cloud']=CLOUD
        self.pending(claimed=str(wrong.pk));expiry=EnrollmentRequest.objects.get(pk=self.fp).expires_at
        self.assertEqual(self.match()['status'],'conflict')
        self.assertEqual(self.pending(claimed=str(host.pk)).status_code,202)
        self.assertEqual(self.match()['status'],'existing')
        self.assertEqual(EnrollmentRequest.objects.get(pk=self.fp).expires_at,expiry)
        self.assertFalse(HostIdentity.objects.exists())
        with self.assertRaises(identity.MigrationTargetError):identity.approve('admin',self.fp,self.fp,wrong.pk)
        self.assertEqual(identity.approve('admin',self.fp,self.fp,host.pk).pk,host.pk)
    def test_rejected_request_cannot_change_hints_and_become_pending(self):
        self.pending();identity.reject('admin',self.fp);host=Host.objects.create()
        self.assertEqual(self.pending(claimed=str(host.pk)).status_code,403)
        pending=EnrollmentRequest.objects.get(pk=self.fp)
        self.assertEqual(pending.status,'rejected');self.assertEqual(pending.claimed_host_id,'')

del IdentityTests
