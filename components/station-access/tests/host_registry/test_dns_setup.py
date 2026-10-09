from unittest.mock import patch
from datetime import timedelta
from dataclasses import replace
from django.test import TestCase,Client
from zog.network_register.contracts import NetworkError,Page
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import digest
from zog.station_access.host_registry import test_dns_cutover as f,dns_setup as s
from zog.station_access.host_registry.models import DnsDestination,ProviderCredential,Host,SecurityAudit

class SetupTests(TestCase):
 review=f.CutoverTests.review
 commit=f.CutoverTests.commit
 def setUp(self):
  f.CutoverTests.setUp(self);self.commit()
  original=self.provider.get_zone
  self.provider.get_zone=lambda z:dict(original(z),name_servers=self.data['nameservers'])
  self.provider.list_zones=lambda cursor=None:Page((dict(id='zone',name='example.uk'),),'2' if cursor is None else None)
 def setup_review(self,label='extra'):
  return s.review(self.config,self.admin.pk,str(self.credential.pk),self.credential.revision,'zone',label,**self.kw)
 def apply(self,r):return s.commit(self.config,self.admin.pk,r['review_id'],**self.kw)
 def test_review_commit_replay_without_provider_writes(self):
  r=self.setup_review();self.assertFalse(DnsDestination.objects.exists());self.assertFalse(self.provider.calls)
  result=self.apply(r);d=DnsDestination.objects.get(pk=result['binding_id']);self.assertTrue(d.enabled)
  self.assertEqual(d.selection['prefix'],'extra.example.uk');self.assertTrue(self.apply(r)['replayed'])
  self.assertEqual(SecurityAudit.objects.filter(action='dns-destination-setup').count(),1);self.assertFalse(self.provider.calls)
 def test_overlap_and_existing_provider_records_block(self):
  with self.assertRaises(s.Blocked):self.setup_review('hosts')
  self.provider.rows.append(dict(id='foreign',name='x.extra.example.uk',type='A'))
  with self.assertRaises(s.Blocked) as error:self.setup_review()
  self.assertEqual(error.exception.stage,'namespace');self.assertFalse(DnsDestination.objects.exists())
 def test_apex_dname_blocks(self):
  self.provider.rows.append(dict(id='foreign',name='example.uk',type='DNAME'))
  with self.assertRaises(s.Blocked):self.setup_review()
 def test_credential_revision_change_invalidates_review(self):
  r=self.setup_review();ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=2)
  with self.assertRaises(NetworkError):self.apply(r)
  self.assertFalse(DnsDestination.objects.exists())
 def test_expiry_and_owner_and_tamper(self):
  r=self.setup_review()
  with patch.object(s.time,'time',return_value=r['expires_at']+1):
   with self.assertRaises(s.Blocked):self.apply(r)
  with self.assertRaises(s.Blocked):s.commit(self.config,self.admin.pk+1,r['review_id'],**self.kw)
  path=self.root/('dns-review-'+r['review_id']+'.json');path.write_text('{}')
  with self.assertRaises(NetworkError):self.apply(r)
 def test_drift_after_review_blocks(self):
  r=self.setup_review();self.provider.rows.append(dict(id='foreign',name='x.extra.example.uk',type='A'))
  with self.assertRaises(s.Blocked):self.apply(r)
  self.assertFalse(DnsDestination.objects.exists());self.assertFalse(self.provider.calls)
 def test_nameserver_change_blocks(self):
  r=self.setup_review();old=self.provider.get_zone
  self.provider.get_zone=lambda z:dict(old(z),name_servers=['other.example.net'])
  with self.assertRaises(s.Blocked):self.apply(r)
 def test_ledger_survives_db_failure_and_missing_active_ledger_stops(self):
  r=self.setup_review()
  with patch.object(DnsDestination.objects,'create',side_effect=OSError('fixture')):
   with self.assertRaises(OSError):self.apply(r)
  self.assertFalse(DnsDestination.objects.exists());self.apply(r)
  d=DnsDestination.objects.get();(self.root/d.ledger_path).unlink()
  with self.assertRaises(s.Blocked):self.apply(r)
  self.assertFalse((self.root/d.ledger_path).exists())
 def test_initialization_at_rotated_credential_revision(self):
  ProviderCredential.objects.filter(pk=self.credential.pk).update(revision=2);self.credential.refresh_from_db()
  r=self.setup_review();self.apply(r);d=DnsDestination.objects.get();store=SqliteStateStore(self.root/d.ledger_path)
  with store.transaction():self.assertEqual(store.all('connection')[0]['revision'],2)
 def test_zone_pagination_and_redacted_auth_failure(self):
  self.assertEqual(s.zones(self.admin.pk,str(self.credential.pk),1,provider_factory=lambda _:self.provider)['cursor'],'2')
  self.provider.list_zones=lambda *_:(_ for _ in ()).throw(NetworkError('authentication'))
  with self.assertRaises(s.Blocked) as e:s.zones(self.admin.pk,str(self.credential.pk),1,provider_factory=lambda _:self.provider)
  self.assertIn('authentication failed',e.exception.report()['message'])
 def test_inspection_reports_stale_host_without_mutation(self):
  Host.objects.filter(pk=self.host.pk).update(signed_dns_observed_at=self.now-timedelta(minutes=10))
  result=s.inspect(self.config,self.admin.pk,'primary',**self.kw)
  self.assertEqual(result['hosts'][0]['code'],'stale-evidence');self.assertFalse(self.provider.calls)
 def test_authority_failure_has_distinct_stage(self):
  with patch.object(self.collector,'authority',side_effect=NetworkError('conflict')):
   with self.assertRaises(s.Blocked) as e:self.setup_review()
  self.assertEqual(e.exception.stage,'authority')
 def test_api_admin_csrf_and_request_shape(self):
  url='/api/hosts/dns-setup/'
  self.assertEqual(self.client.post(url,{},content_type='application/json').status_code,401)
  self.client.force_login(self.admin)
  self.assertEqual(self.client.post(url,dict(action='review',path='/tmp/unsafe'),content_type='application/json').status_code,400)
  csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
  self.assertEqual(csrf.post(url,dict(action='commit',review_id='a'*64),content_type='application/json').status_code,403)
 def test_porkbun_nameservers_are_provider_pinned(self):
  self.credential.provider='porkbun';self.credential.account_id='';self.credential.save()
  old=self.provider.get_zone
  self.provider.get_zone=lambda z:dict(old(z),account={'id':'provider:'+str(self.credential.pk)})
  r=self.setup_review();self.assertEqual(r['nameservers'],sorted(s.PORKBUN_NS));self.apply(r)
 def test_pending_uncertain_operation_is_reported_without_retry(self):
  from zog.station_access.host_registry.dns_shared import open_runtime
  selected,source,engine=open_runtime(self.config,self.root,**self.kw)
  c,b=selected.connection,selected.binding;h=source.host(c.owner_id,b.id,str(self.host.pk))
  plan=engine.plan(c.owner_id,c.owner_id,b.id,str(self.host.pk),h.desired,h.desired_revision)
  op=engine.ledger.prepare(c.owner_id,'fixture-pending',plan)
  op=engine.ledger.transition(c.owner_id,c.owner_id,'fixture-pending',op['revision'],'dispatching')
  engine.ledger.transition(c.owner_id,c.owner_id,'fixture-pending',op['revision'],'uncertain')
  result=s.inspect(self.config,self.admin.pk,'primary',**self.kw)
  self.assertEqual(result['operations'][0]['state'],'uncertain');self.assertFalse(result['ready']);self.assertFalse(self.provider.calls)
 def test_foreign_record_drift_is_reported_without_adoption(self):
  self.provider.rows[0]['comment']='another owner'
  result=s.inspect(self.config,self.admin.pk,'primary',**self.kw)
  self.assertEqual(result['hosts'][0]['code'],'conflict');self.assertFalse(result['ready']);self.assertFalse(self.provider.calls)
 def test_api_review_and_confirm_use_server_held_selection(self):
  self.client.force_login(self.admin);url='/api/hosts/dns-setup/'
  with patch('zog.station_access.host_registry.dns_setup_views.configuration',return_value=self.config),patch.object(s,'provider',return_value=self.provider),patch.object(s,'DnsAuthorityCollector',return_value=self.collector):
   r=self.client.post(url,dict(action='review',credential_id=str(self.credential.pk),revision=1,zone_id='zone',label='extra'),content_type='application/json')
   self.assertEqual(r.status_code,200,r.content);self.assertNotIn('ciphertext',r.content.decode());self.assertFalse(DnsDestination.objects.exists())
   result=self.client.post(url,dict(action='commit',review_id=r.json()['review_id']),content_type='application/json')
   self.assertEqual(result.status_code,200,result.content);self.assertTrue(DnsDestination.objects.exists());self.assertFalse(self.provider.calls)
