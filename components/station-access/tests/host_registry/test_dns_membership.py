import copy
from unittest.mock import patch
from django.test import TestCase
from zog.network_register.contracts import NetworkError
from zog.network_register.store import SqliteStateStore
from zog.station_access.host_registry import test_dns_cutover as f, dns_membership as membership, dns_shared
from zog.station_access.host_registry.dns_reconcile import configure_assignment
from zog.station_access.host_registry.models import Host, HostIdentity, DnsAssignment, SecurityAudit

class MembershipTests(TestCase):
    setUp=f.CutoverTests.setUp
    review=f.CutoverTests.review
    commit=f.CutoverTests.commit
    run_worker=f.CutoverTests.run_worker
    def release_review(self):
        self.commit();configure_assignment(self.host,self.config,False);self.run_worker()
        return membership.review(self.config,str(self.host.pk),'release',**self.kw)
    def change(self,review):return membership.commit(self.config,review['review_id'],**self.kw)
    def new_host(self):
        cloud=dict(self.cloud,instance_id='i-new')
        host=Host.objects.create(provider='aws',**cloud,signed_dns_fingerprint='b'*64,
            signed_dns_report=dict(cloud=cloud,public_ip='8.8.8.8'),signed_dns_observed_at=self.now,
            aws_checked_at=self.now,aws_observation=dict(cloud=cloud,observed_at=self.now.isoformat(),public_ip='8.8.8.8',state='running'))
        HostIdentity.objects.create(host=host,fingerprint='b'*64,public_key='fixture',status='approved',approved_at=self.key.approved_at)
        return host
    def test_onboard_new_host_and_worker(self):
        self.commit();host=self.new_host()
        reviewed=membership.review(self.config,str(host.pk),'reserve','new',**self.kw)
        self.assertFalse(DnsAssignment.objects.filter(host=host).exists());self.assertFalse(self.provider.calls)
        result=self.change(reviewed)
        self.assertEqual(result,self.change(reviewed));self.assertFalse(self.provider.calls)
        self.assertEqual(self.run_worker(),{'synchronized':2})
        self.assertTrue(DnsAssignment.objects.get(host=host).record_id)
    def test_release_retired_host_and_reuse(self):
        reviewed=self.release_review();self.key.status='revoked';self.key.save()
        calls=copy.deepcopy(self.provider.calls);self.change(reviewed)
        self.assertEqual(calls,self.provider.calls);self.assertFalse(DnsAssignment.objects.filter(host=self.host).exists())
        self.assertEqual(self.run_worker(),{})
        host=self.new_host();new=membership.review(self.config,str(host.pk),'reserve','compiler',**self.kw)
        self.change(new);self.change(reviewed)
        self.assertEqual(DnsAssignment.objects.get(host=host).name,reviewed['name'])
        self.assertEqual(self.run_worker(),{'synchronized':1})
        self.assertEqual(SecurityAudit.objects.filter(action='dns-membership').count(),2)
    def test_same_host_reuse_increases_revision(self):
        reviewed=self.release_review();floor=reviewed['revision_floor'];self.change(reviewed)
        new=membership.review(self.config,str(self.host.pk),'reserve','compiler',**self.kw)
        self.change(new)
        self.assertGreater(DnsAssignment.objects.get(host=self.host).revision,floor)
        self.assertEqual(self.run_worker(),{'synchronized':1})
    def test_stale_review_and_unenrolled_host(self):
        self.commit();host=self.new_host()
        reviewed=membership.review(self.config,str(host.pk),'reserve','new',**self.kw)
        HostIdentity.objects.filter(host=host).update(status='revoked')
        with self.assertRaises(NetworkError):self.change(reviewed)
        self.assertIsNone(dns_shared.status(self.config)['membership']['pending'])
        with self.assertRaises(NetworkError):membership.review(self.config,str(host.pk),'reserve','new',**self.kw)
    def test_live_release_and_wrong_owner_rejected(self):
        self.commit()
        with self.assertRaises(NetworkError):membership.review(self.config,str(self.host.pk),'release',**self.kw)
        host=self.new_host()
        with self.assertRaises(NetworkError):membership.review(self.config,str(host.pk),'reserve','new',actor_id=self.admin.pk+1,**self.kw)
    def test_recovery_after_projection_commit(self):
        reviewed=self.release_review();original=SqliteStateStore.write
        def fail(store,kind,key,value):
            if kind=='membership-operation' and value['phase']=='completed':raise NetworkError('storage')
            return original(store,kind,key,value)
        with patch.object(SqliteStateStore,'write',fail):
            with self.assertRaises(NetworkError):self.change(reviewed)
        self.assertFalse(DnsAssignment.objects.filter(host=self.host).exists())
        with self.assertRaises(NetworkError):self.run_worker()
        with self.assertRaises(NetworkError):membership.cancel(self.config,reviewed['review_id'])
        self.change(reviewed)
        self.assertEqual(SecurityAudit.objects.filter(action='dns-membership').count(),1)
        self.assertEqual(self.run_worker(),{})
    def test_recovery_after_allocation_receipt(self):
        self.commit();host=self.new_host();reviewed=membership.review(self.config,str(host.pk),'reserve','new',**self.kw)
        with patch.object(DnsAssignment.objects,'create',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):self.change(reviewed)
        with self.assertRaises(NetworkError):self.run_worker()
        self.change(reviewed);self.assertEqual(self.run_worker(),{'synchronized':2})
    def test_foreign_record_race_before_commit_does_not_fence(self):
        self.commit();host=self.new_host();reviewed=membership.review(self.config,str(host.pk),'reserve','new',**self.kw)
        self.provider.rows.append(dict(id='foreign',name=reviewed['name'],type='A',content='1.1.1.1',ttl=300,proxied=False))
        with self.assertRaises(NetworkError):self.change(reviewed)
        self.assertIsNone(dns_shared.status(self.config)['membership']['pending'])
    def test_cancel_before_receipt_only(self):
        reviewed=self.release_review()
        from zog.network_register.reservations import NameReservations
        with patch.object(NameReservations,'change',side_effect=NetworkError('transient')):
            with self.assertRaises(NetworkError):self.change(reviewed)
        membership.cancel(self.config,reviewed['review_id'])
        with self.assertRaises(NetworkError):self.change(reviewed)
        self.assertEqual(self.run_worker(),{'unpublished':1})
    def test_membership_loss_fails_closed(self):
        reviewed=self.release_review();self.change(reviewed)
        store=SqliteStateStore(self.root/('dns-ledger-'+self.reviewed['review_id']+'.sqlite3'))
        with store.transaction():store.delete('meta','membership')
        with self.assertRaises(NetworkError):self.run_worker()
    def test_api_review_requires_explicit_commit_and_host_scope(self):
        self.commit();host=self.new_host();self.client.force_login(self.admin)
        with patch('zog.station_access.host_registry.dns_reconcile.configuration',return_value=self.config),patch('zog.station_access.host_registry.dns_shared.open_runtime',wraps=dns_shared.open_runtime) as opened:
            # Inject provider and authority fixtures at the API's service boundary.
            original=membership.review
            def reviewed(*args,**kw):return original(*args,**kw,**self.kw)
            with patch('zog.station_access.host_registry.dns_membership_views.configuration',return_value=self.config),patch('zog.station_access.host_registry.dns_membership_views.dns_membership.review',side_effect=reviewed):
                response=self.client.post('/api/hosts/'+str(host.pk)+'/dns-membership/',data={'action':'reserve','label':'new'},content_type='application/json')
            self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(DnsAssignment.objects.filter(host=host).exists())
        with self.assertRaises(NetworkError):membership.commit(self.config,response.json()['review_id'],resource_id=self.host.pk,**self.kw)
    def test_revoked_host_can_request_unpublish_via_api(self):
        self.commit();self.key.status='revoked';self.key.save();self.client.force_login(self.admin)
        with patch('zog.station_access.host_registry.dns_reconcile.configuration',return_value=self.config):
            response=self.client.post('/api/hosts/'+str(self.host.pk)+'/dns/',data={'enabled':False},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.run_worker(),{'unpublished':1})
    def test_cli_review_commit_and_status(self):
        import io,json
        from django.core.management import call_command
        reviewed=self.release_review();out=io.StringIO()
        original=membership.commit
        def commit(*args,**kw):return original(*args,**kw,**self.kw)
        with patch('zog.station_access.host_registry.management.commands.manage_host_dns.configuration',return_value=self.config),patch('zog.station_access.host_registry.dns_membership.commit',side_effect=commit):
            call_command('manage_host_dns','commit',approve_review=reviewed['review_id'],stdout=out)
        self.assertEqual(json.loads(out.getvalue())['action'],'release')
    def test_release_clears_dns_archival_blocker(self):
        from zog.station_access.host_registry.retirement import preview
        reviewed=self.release_review();self.change(reviewed)
        # The archive workflow may still require key revocation/token expiry, but DNS no longer blocks it.
        result=preview(self.host)
        self.assertEqual(result['dns'],[])
