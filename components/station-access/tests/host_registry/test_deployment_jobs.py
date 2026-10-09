import json
from datetime import timedelta
from uuid import uuid4
from unittest.mock import Mock, patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from zog.station_access.host_registry.models import Host, HostIdentity, BeaconDestination, DeploymentJob
from zog.station_access.host_registry import deployment_jobs as jobs
from zog.station_access.host_registry.retirement import preview as removal_preview

@override_settings(HOST_DEPLOY_JOBS_ENABLED=True)
class DeploymentJobTests(TestCase):
    def setUp(self):
        self.host=Host.objects.create(label='Compiler',provider='aws',account_id='123456789012',region='us-east-1',instance_id='i-0123456789abcdef0',workspace_id='demo')
        self.identity=HostIdentity.objects.create(host=self.host,fingerprint='a'*64,public_key='fixture',approved_by='fixture',approved_at=timezone.now())
        self.destination=BeaconDestination.objects.create(label='Primary',server='https://registry.example',enabled=True,revision=1)
        self.admin=get_user_model().objects.create_superuser('admin',password='synthetic-fixture-password')
        self.observation=dict(primary=self.destination.server,destinations_sha256='b'*64,destinations=[dict(label='Previous',server=self.destination.server,enabled=True,revision=1,ca_sha256=None)],beacon_state='active',station_state='unknown',beacon_version='0.3.4',station_version=None,apply_supported=True)

    def inspected(self):
        job=jobs.create_inspection('fixture',str(self.host.pk),str(uuid4()))
        adapter=Mock();adapter.submit.return_value='command';adapter.poll.return_value={'status':'inspected','observation':self.observation}
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk);jobs.process(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'succeeded')
        return job

    def review(self):return jobs.preview('fixture',str(self.host.pk),str(self.inspected().pk))

    def test_admin_csrf_and_disabled_guards(self):
        url='/api/setup/deployment-jobs/'
        self.assertEqual(self.client.get(url).status_code,401)
        self.client.force_login(get_user_model().objects.create_user('ordinary'))
        self.assertEqual(self.client.get(url).status_code,403)
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin)
        self.assertEqual(client.post(url,'{}',content_type='application/json').status_code,403)
        with override_settings(HOST_DEPLOY_JOBS_ENABLED=False):
            with self.assertRaises(ValueError):jobs.create_inspection('fixture',str(self.host.pk),str(uuid4()))

    def test_http_only_records_intent_and_idempotent_inspection(self):
        self.client.force_login(self.admin);payload=dict(action='inspect',host_id=str(self.host.pk),action_id=str(uuid4()))
        with patch.object(jobs,'gateway') as remote:
            for _ in range(2):self.assertEqual(self.client.post('/api/setup/deployment-jobs/',json.dumps(payload),content_type='application/json').status_code,201)
            self.assertEqual(self.client.get('/api/setup/deployment-jobs/').status_code,200)
            remote.assert_not_called()
        self.assertEqual(DeploymentJob.objects.count(),1)
        with self.assertRaises(ValueError):jobs.create_inspection('fixture',str(self.host.pk),str(uuid4()))

    def test_review_captures_changes_and_confirmation_is_idempotent(self):
        job=self.review();self.assertEqual(job.state,'review');self.assertEqual(job.result['before'][0]['label'],'Previous')
        with patch.object(jobs,'gateway') as remote:
            jobs.confirm('fixture',job.pk);jobs.confirm('fixture',job.pk);remote.assert_not_called()
        adapter=Mock();adapter.submit.return_value='command'
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk);jobs.process(job.pk)
        adapter.submit.assert_called_once()

    def test_changed_saved_intent_and_expired_inspection_rejected(self):
        inspection=self.inspected();inspection.finished_at=timezone.now()-timedelta(minutes=6);inspection.save()
        with self.assertRaises(ValueError):jobs.preview('fixture',str(self.host.pk),str(inspection.pk))
        job=self.review();self.destination.label='Changed';self.destination.save()
        with self.assertRaises(ValueError):jobs.confirm('fixture',job.pk)

    def test_primary_and_remote_support_required(self):
        inspection=self.inspected();self.destination.enabled=False;self.destination.save()
        with self.assertRaises(ValueError):jobs.preview('fixture',str(self.host.pk),str(inspection.pk))
        self.destination.enabled=True;self.destination.save()
        inspection.result['observation']['apply_supported']=False;inspection.save()
        with self.assertRaises(ValueError):jobs.preview('fixture',str(self.host.pk),str(inspection.pk))

    def test_queued_change_revalidates_host_and_destinations(self):
        job=self.review();jobs.confirm('fixture',job.pk)
        self.identity.status='revoked';self.identity.save()
        with patch.object(jobs,'gateway') as remote:jobs.process(job.pk);remote.assert_not_called()
        job.refresh_from_db();self.assertEqual(job.state,'failed')

    def test_lost_submission_requires_read_only_recovery(self):
        job=self.review();jobs.confirm('fixture',job.pk)
        adapter=Mock();adapter.submit.side_effect=TimeoutError('do not expose secret')
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk);jobs.process(job.pk)
        adapter.submit.assert_called_once();job.refresh_from_db();self.assertEqual(job.state,'uncertain')
        self.assertNotIn('secret',job.message)
        self.assertTrue(any('deployment job' in item for item in removal_preview(self.host)['blockers']))
        jobs.recover('fixture',job.pk);adapter.submit.side_effect=None;adapter.submit.return_value='recovery-command'
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk)
        self.assertEqual(adapter.submit.call_args.args[0]['action'],'recover')
        self.assertEqual(adapter.submit.call_args.args[0]['id'],str(job.pk))

    def test_abandoned_submit_never_resubmits(self):
        job=self.review();job.state='submitting';job.started_at=timezone.now()-timedelta(minutes=3);job.save()
        with patch.object(jobs,'gateway') as remote:jobs.process(job.pk);remote.assert_not_called()
        job.refresh_from_db();self.assertEqual(job.state,'uncertain')

    def test_completed_digest_is_checked_and_output_sanitized(self):
        job=self.review();jobs.confirm('fixture',job.pk)
        adapter=Mock();adapter.submit.return_value='command';adapter.poll.return_value={'status':'installed','sha256':'bad','secret':'private'}
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk);jobs.process(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'uncertain');self.assertNotIn('private',json.dumps(jobs.serialize(job)))

    def test_unresolved_jobs_remain_visible_after_newer_history(self):
        original=jobs.create_inspection('fixture',str(self.host.pk),str(uuid4()))
        for _ in range(26):DeploymentJob.objects.create(host=self.host,operation='inspect',state='failed')
        self.client.force_login(self.admin)
        result=self.client.get('/api/setup/deployment-jobs/').json()
        self.assertIn(str(original.pk),[j['id'] for j in result['jobs']])

    def test_late_submission_cannot_overwrite_new_recovery_attempt(self):
        job=self.review();jobs.confirm('fixture',job.pk)
        def late(request):
            DeploymentJob.objects.filter(pk=job.pk).update(state='running',attempt_id=uuid4(),command_id='newer')
            return 'late-old'
        adapter=Mock();adapter.submit.side_effect=late
        with patch.object(jobs,'gateway',return_value=adapter):jobs.process(job.pk)
        job.refresh_from_db();self.assertEqual(job.command_id,'newer')
