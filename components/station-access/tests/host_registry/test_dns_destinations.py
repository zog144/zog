from unittest.mock import patch
from django.test import TestCase
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.contracts import NetworkError
from zog.station_access.host_registry import test_dns_cutover as f,dns_destinations as d
from zog.station_access.host_registry.dns_evidence import selection,RegistryEvidenceSource
from zog.station_access.host_registry.dns_cutover import Authorization
from zog.station_access.host_registry.models import DnsDestination,AdditionalDnsAssignment,HostIdentity,DnsAssignment
from zog.station_access.host_registry.retirement import preview

class DestinationTests(TestCase):
 review=f.CutoverTests.review
 commit=f.CutoverTests.commit
 def setUp(self):
  f.CutoverTests.setUp(self);self.commit()
  self.data2=dict(self.data,binding_id='additional',prefix='extra.example.uk',host_ids=[])
  self.destination=DnsDestination.objects.create(id='additional',selection=self.data2,ledger_path='additional.sqlite3',enabled=True)
  selected=selection(self.data2,allow_empty=True)
  store=SqliteStateStore(self.root/'additional.sqlite3',create=True)
  ledger=OperationLedger(store,Authorization(RegistryEvidenceSource(selected,self.collector)))
  ledger.put_connection(selected.connection.owner_id,selected.connection,0);ledger.put_binding(selected.connection.owner_id,selected.binding,0)
  self.extra=f.Provider({},'a'*32);self.extra.rows=[]
  self.kw2=dict(collector=self.collector,provider_factory=lambda _:self.extra)
 def change(self,action,label=None,revision=None,owner=None):
  return d.configure(self.config,'additional',self.host.pk,action,actor_id=owner or self.admin.pk,label=label,expected_revision=revision,**self.kw2)
 def worker(self):return d.reconcile_all(self.config,self.root,**self.kw2)
 def row(self):return AdditionalDnsAssignment.objects.get(host=self.host)
 def test_two_assignments_independent_and_noop(self):
  self.change('reserve','compiler');self.assertEqual(self.worker(),{'synchronized':1})
  primary=DnsAssignment.objects.get(host=self.host)
  self.assertEqual(primary.name,'compiler.hosts.example.uk');self.assertEqual(primary.record_id,'legacy-record')
  self.assertEqual(self.row().name,'compiler.extra.example.uk')
  count=len(self.extra.calls);self.worker();self.assertEqual(len(self.extra.calls),count)
 def test_unpublish_release_reuse_and_stale_request(self):
  self.change('reserve','compiler');self.worker();r=self.row()
  self.change('unpublish',revision=r.revision);self.assertEqual(self.worker(),{'unpublished':1})
  r=self.row();oldrev=r.revision;self.change('release',revision=oldrev)
  self.assertFalse(AdditionalDnsAssignment.objects.exists())
  self.change('reserve','compiler');self.assertGreater(self.row().revision,oldrev)
  with self.assertRaises(NetworkError):self.change('unpublish',revision=oldrev)
  self.worker();self.assertEqual([x[0] for x in self.extra.calls],['create','delete','create'])
 def test_secondary_reservation_blocks_archive_without_primary(self):
  self.change('reserve','compiler');DnsAssignment.objects.all().delete()
  self.assertTrue(any('DNS assignment' in x for x in preview(self.host)['blockers']))
 def test_wrong_owner_and_stale_evidence(self):
  with self.assertRaises(NetworkError):self.change('reserve','compiler',owner=self.admin.pk+1)
  self.assertFalse(AdditionalDnsAssignment.objects.exists())
  self.change('reserve','compiler');HostIdentity.objects.filter(host=self.host).update(status='revoked')
  self.assertEqual(self.worker(),{'waiting_verification':1});self.assertFalse(self.extra.calls)
 def test_reservation_receipt_survives_projection_failure(self):
  original=AdditionalDnsAssignment.save
  def fail(row,*a,**kw):
   if row.phase=='ready':raise OSError('fixture')
   return original(row,*a,**kw)
  with patch.object(AdditionalDnsAssignment,'save',fail):
   with self.assertRaises(OSError):self.change('reserve','compiler')
  self.assertEqual(self.row().phase,'reserving');self.assertEqual(self.worker(),{'conflict':1})
  self.change('reserve','compiler');self.assertEqual(self.worker(),{'synchronized':1})
 def test_missing_ledger_fails_closed(self):
  self.change('reserve','compiler');(self.root/'additional.sqlite3').unlink()
  self.assertEqual(self.worker(),{'provider_error':1});self.assertFalse(self.extra.calls)
 def test_serialize_without_primary(self):
  self.change('reserve','compiler');DnsAssignment.objects.all().delete()
  from zog.station_access.host_registry.views import serialize
  self.assertEqual(serialize(self.host,self.now)['additional_dns'][0]['binding_id'],'additional')
 def test_cancel_uncommitted_invalid_host_reservation(self):
  HostIdentity.objects.filter(host=self.host).update(status='revoked')
  with self.assertRaises(NetworkError):self.change('reserve','compiler')
  self.change('cancel',revision=self.row().revision)
  self.assertFalse(AdditionalDnsAssignment.objects.exists())
 def test_import_owned_ledger_requires_readback_and_preserves_primary(self):
  self.change('reserve','compiler');self.worker();record=self.row()
  data=dict(self.data2,host_ids=[str(self.host.pk)])
  AdditionalDnsAssignment.objects.all().delete();self.destination.delete()
  result=d.import_destination(self.config,data,'additional.sqlite3',**self.kw2)
  self.assertEqual(result['binding_id'],'additional');self.assertEqual(self.row().record_id,record.record_id)
  self.assertEqual(len(self.extra.calls),1)
 def test_import_rejects_provider_drift(self):
  self.change('reserve','compiler');self.worker()
  data=dict(self.data2,host_ids=[str(self.host.pk)])
  AdditionalDnsAssignment.objects.all().delete();self.destination.delete();self.extra.rows[0]['content']='9.9.9.9'
  with self.assertRaises(NetworkError):d.import_destination(self.config,data,'additional.sqlite3',**self.kw2)
  self.assertFalse(DnsDestination.objects.exists())
 def test_release_receipt_survives_projection_failure(self):
  self.change('reserve','compiler');self.worker();self.change('unpublish',revision=self.row().revision);self.worker()
  revision=self.row().revision
  with patch.object(AdditionalDnsAssignment,'delete',side_effect=OSError('fixture')):
   with self.assertRaises(OSError):self.change('release',revision=revision)
  self.assertEqual(self.row().phase,'releasing');self.assertEqual(self.worker(),{'conflict':1})
  self.change('release',revision=revision);self.assertFalse(AdditionalDnsAssignment.objects.exists())
 def test_api_permissions_and_destination_selection(self):
  url='/api/hosts/'+str(self.host.pk)+'/dns-destinations/additional/'
  self.assertEqual(self.client.post(url,{},content_type='application/json').status_code,401)
  self.client.force_login(self.admin)
  with patch('zog.station_access.host_registry.dns_destination_views.configuration',return_value=self.config), patch('zog.station_access.host_registry.dns_destination_views.configure',return_value={'name':'compiler.extra.example.uk'}) as configure:
   response=self.client.post(url,{'action':'unpublish','revision':7},content_type='application/json')
   self.assertEqual(response.status_code,200);self.assertEqual(configure.call_args.kwargs['expected_revision'],7)
  self.assertEqual(self.client.post(url,{'action':'unpublish','revision':True},content_type='application/json').status_code,400)
