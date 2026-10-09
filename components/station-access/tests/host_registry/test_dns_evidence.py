import io
import json
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from zog.network_register.contracts import NetworkError, Page
from zog.network_register.evidence import EvidenceGate, AuthorityEvidence, AuthoritativeAnswer
from zog.station_access.host_registry.models import Host, HostIdentity, DnsAssignment, InventoryScan, ProviderCredential
from zog.station_access.host_registry.dns_evidence import selection, RegistryEvidenceSource, RegistrySecretResolver, readiness


class DnsEvidenceTests(TestCase):
    def setUp(self):
        self.now=timezone.now();self.admin=get_user_model().objects.create_superuser('evidence-admin',password='fixture')
        self.credential=ProviderCredential.objects.create(label='fixture',provider='cloudflare',account_id='a'*32,
            key_id='fixture',ciphertext='fixture',revision=1)
        self.cloud=dict(account_id='123456789012',region='us-east-1',instance_id='i-123')
        self.host=Host.objects.create(provider='aws',**self.cloud,
            signed_dns_report={'cloud':self.cloud,'public_ip':'8.8.8.8'},signed_dns_fingerprint='a'*64,
            signed_dns_observed_at=self.now,aws_checked_at=self.now,
            aws_observation={'cloud':self.cloud,'observed_at':self.now.isoformat(),'public_ip':'8.8.8.8','state':'running'})
        self.key=HostIdentity.objects.create(host=self.host,fingerprint='a'*64,public_key='fixture',status='approved',
            approved_by='fixture',approved_at=self.now-timedelta(seconds=5))
        self.assignment=DnsAssignment.objects.create(host=self.host,name='compiler.hosts.example.uk',owner_id='legacy:'+str(self.host.pk),
            desired_action='present',desired_address='8.8.8.8')
        for scope in ('region-discovery','123456789012/region-discovery','123456789012/us-east-1'):
            InventoryScan.objects.create(scope=scope,last_success=self.now)
        self.data=dict(schema=1,owner_user_id=self.admin.pk,credential_id=str(self.credential.pk),credential_revision=1,
            binding_id='binding',binding_revision=1,zone_id='zone',zone_name='example.uk',prefix='hosts.example.uk',
            nameservers=['ns1.example.net','ns2.example.net'],host_ids=[str(self.host.pk)])
        self.s=selection(self.data)
        test=self
        class Collector:
            def authority(self,c,b):
                return AuthorityEvidence(c.owner_id,c.id,c.revision,c.credential_ref,b.id,b.revision,b.zone_id,b.zone_name,b.prefix,
                    b.nameservers,test.now.timestamp(),tuple(AuthoritativeAnswer(n,b.zone_name,True,test.now.timestamp(),True) for n in b.nameservers))
        self.collector=Collector()
        self.source=RegistryEvidenceSource(self.s,self.collector)
        self.gate=EvidenceGate(self.source)
        self.reads=[]
        class Provider:
            def get_zone(_,zone):
                self.reads.append('zone');return dict(id=zone,name='example.uk',account={'id':'a'*32},status='active')
            def list_records(_,zone,cursor):self.reads.append('records');return Page((),None)
        self.provider=Provider()
    def evidence(self):return self.source.host(self.s.connection.owner_id,self.s.binding.id,str(self.host.pk))
    def check(self):
        h=self.evidence();self.gate.check(self.s.connection,self.s.binding,str(self.host.pk),h.desired,
            'publish' if h.publish_enabled else 'unpublish',h.desired_revision)
    def blocked(self):
        with self.assertRaises(NetworkError):self.check()
    def test_verified_evidence_and_ttl(self):
        self.check();self.assertEqual(self.evidence().desired.ttl,300)
    def test_legacy_report_cannot_replace_signed_evidence(self):
        Host.objects.filter(pk=self.host.pk).update(report={'cloud':{},'public_ip':'1.1.1.1'},signed_last_received=self.now)
        self.check();self.assertEqual(self.evidence().signed_address,'8.8.8.8')
        Host.objects.filter(pk=self.host.pk).update(signed_dns_report={});self.blocked()
    def test_key_revocation(self):
        self.key.status='revoked';self.key.save();self.blocked()
    def test_another_approved_key_does_not_validate_old_report(self):
        self.key.delete();HostIdentity.objects.create(host=self.host,fingerprint='b'*64,public_key='fixture',approved_by='fixture',approved_at=self.now)
        self.blocked()
    def test_old_signed_snapshot_requires_new_heartbeat(self):
        Host.objects.filter(pk=self.host.pk).update(signed_dns_observed_at=None);self.blocked()
    def test_signature_freshness_is_observation_not_receive_time(self):
        Host.objects.filter(pk=self.host.pk).update(signed_dns_observed_at=self.now-timedelta(seconds=301),signed_last_received=self.now)
        self.blocked()
    def test_missing_inventory_provenance(self):
        Host.objects.filter(pk=self.host.pk).update(aws_observation={'state':'running','public_ip':'8.8.8.8'})
        self.blocked()
    def test_inventory_identity_mismatch(self):
        row=self.host.aws_observation;row['cloud']={**self.cloud,'instance_id':'other'}
        Host.objects.filter(pk=self.host.pk).update(aws_observation=row);self.blocked()
    def test_slow_inventory_not_rejuvenated_by_commit_time(self):
        row=self.host.aws_observation;row['observed_at']=(self.now-timedelta(seconds=301)).isoformat()
        Host.objects.filter(pk=self.host.pk).update(aws_observation=row);self.blocked()
    def test_failed_scan_even_with_recent_last_success(self):
        InventoryScan.objects.filter(scope='123456789012/us-east-1').update(error='denied');self.blocked()
    def test_missing_account_scoped_discovery(self):
        InventoryScan.objects.filter(scope='123456789012/region-discovery').delete();self.blocked()
    def test_stopped_host_does_not_authorize_unpublish(self):
        row=self.host.aws_observation;row['state']='stopped';Host.objects.filter(pk=self.host.pk).update(aws_observation=row)
        self.blocked()
    def test_explicit_disabled_assignment_can_unpublish_without_live_host(self):
        DnsAssignment.objects.filter(pk=self.host.pk).update(enabled=False)
        Host.objects.filter(pk=self.host.pk).update(archived_at=self.now,signed_dns_report={},aws_observation={})
        self.key.delete();InventoryScan.objects.all().delete();self.check()
    def test_scope_and_desired_revision_enforced(self):
        with self.assertRaises(NetworkError):self.source.host('other','binding',str(self.host.pk))
        h=self.evidence()
        with self.assertRaises(NetworkError):self.gate.check(self.s.connection,self.s.binding,str(self.host.pk),h.desired,'publish',h.desired_revision+1)
    def test_assignment_outside_selected_prefix(self):
        DnsAssignment.objects.filter(pk=self.host.pk).update(name='compiler.other.example.uk');self.blocked()
    def test_credential_changed_after_selection(self):
        ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=2);self.blocked()
    def test_owner_disabled_after_selection(self):
        self.admin.is_active=False;self.admin.save();self.blocked()
    def test_readiness_never_changes_legacy_assignments_or_provider(self):
        before=list(DnsAssignment.objects.values())
        result=readiness(self.s,collector=self.collector,provider_factory=lambda _:self.provider)
        self.assertEqual(result['hosts'][0]['evidence'],'ready')
        self.assertEqual(result['write_permission'],'unknown');self.assertFalse(result['writes_enabled'])
        self.assertEqual(self.reads,['zone','records']);self.assertEqual(before,list(DnsAssignment.objects.values()))
    def test_readiness_reports_blocked_host(self):
        self.key.delete()
        r=readiness(self.s,collector=self.collector,provider_factory=lambda _:self.provider)
        self.assertEqual(r['hosts'][0]['evidence'],'blocked')
    def test_no_secret_fallback_on_rotation_or_vault_failure(self):
        resolver=RegistrySecretResolver(self.source);c=self.s.connection
        with patch('zog.station_access.host_registry.setup_configuration.decrypt_provider',side_effect=RuntimeError('secret-value')):
            with self.assertRaises(NetworkError) as caught:resolver.resolve(c.owner_id,c.id,c.credential_ref)
            self.assertNotIn('secret-value',str(caught.exception))
        ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=2)
        with patch('zog.station_access.host_registry.setup_configuration.decrypt_provider') as decrypt:
            with self.assertRaises(NetworkError):resolver.resolve(c.owner_id,c.id,c.credential_ref)
            decrypt.assert_not_called()
    def test_command_sanitizes_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'selection.json';path.write_text(json.dumps(self.data));path.chmod(0o600)
            with patch('zog.station_access.host_registry.management.commands.check_dns_evidence.readiness',side_effect=ValueError('secret-value')):
                with self.assertRaises(CommandError) as caught:call_command('check_dns_evidence',configuration=str(path),stdout=io.StringIO())
                self.assertNotIn('secret-value',str(caught.exception))
    def test_reject_duplicate_hosts_unknown_fields_unpinned_credential(self):
        for data in ({**self.data,'host_ids':[str(self.host.pk)]*2},{**self.data,'unexpected':True},
                     {**self.data,'credential_revision':0},{**self.data,'nameservers':[]}):
            with self.subTest(data_keys=list(data)):
                with self.assertRaises(NetworkError):selection(data)

    def test_inventory_commit_records_account_and_scan_start(self):
        from zog.station_access.host_registry.inventory import commit_region
        scan=InventoryScan.objects.get(scope='123456789012/us-east-1')
        scan.last_attempt=self.now-timedelta(seconds=301);scan.save()
        commit_region('123456789012','us-east-1',[{'InstanceId':'i-123','State':{'Name':'running'},'PublicIpAddress':'8.8.8.8'}],scan)
        self.host.refresh_from_db()
        self.assertEqual(self.host.aws_observation['cloud'],self.cloud)
        self.assertEqual(self.host.aws_observation['observed_at'],scan.last_attempt.isoformat())
        self.blocked()
