from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from test_porkbun_dns import Http,Secrets,Policy,RESOURCE
from test_evidence_lifecycle import Source
from zog.network_register.initialization import initialize_porkbun_a,PORKBUN_NAMESERVERS
from zog.network_register.evidence import EvidenceGate
from zog.network_register.models import Connection,ZoneBinding
from zog.network_register.store import SqliteStateStore
from zog.network_register.ledger import OperationLedger
from zog.network_register.contracts import NetworkError

class InitializationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=SqliteStateStore(Path(self.temp.name)/'ledger',create=True)
  self.ledger=OperationLedger(self.store,Policy(),lambda:1000)
  self.c=Connection('pb','owner','porkbun','account','vault:1',status='ready')
  self.b=ZoneBinding('binding','owner','pb','example.com','example.com','hosts.example.com',status='ready',nameservers=PORKBUN_NAMESERVERS)
  self.ledger.put_connection('owner',self.c,0);self.ledger.put_binding('owner',self.b,0)
  self.source=Source(1000);self.gate=EvidenceGate(self.source,lambda:1000)
  self.collector=SimpleNamespace(delegation=lambda *a:1000)
  self.http=Http();self.http.authority=False
 def run_init(self):
  h=self.source.host_value
  return initialize_porkbun_a(self.ledger,self.gate,self.collector,Secrets(),'owner',self.c,self.b,RESOURCE,h.desired,h.desired_revision,transport=self.http)
 def blocked(self):
  with self.assertRaises(NetworkError):self.run_init()
  self.assertEqual(self.http.writes(),[])
 def test_missing_soa_create_and_replay_without_second_write(self):
  row=self.run_init();self.assertEqual(row['state'],'succeeded')
  self.assertEqual(self.run_init(),row);self.assertEqual(len(self.http.writes()),1)
  self.assertFalse(any('preflight' in x[1] for x in self.http.calls))
  with self.assertRaises(NetworkError):self.gate.authority(self.c,self.b)
 def test_lost_response_verified_without_replay(self):
  self.http.lost=True
  self.assertEqual(self.run_init()['state'],'succeeded')
  self.run_init();self.assertEqual(len(self.http.writes()),1)
 def test_warning_remains_conflict(self):
  self.http.warning=True
  self.assertEqual(self.run_init()['state'],'conflict')
  self.assertEqual(self.run_init()['state'],'conflict')
  self.assertEqual(len(self.http.writes()),1)
 def test_nonempty_native_zone_rejected(self):
  self.http.records=[dict(id='42',name='one.hosts.example.com',type='A',content='8.8.8.8',ttl='600',notes='foreign')]
  self.blocked()
 def test_cloudflare_connected_zone_rejected(self):
  self.http.cloudflare='enabled';self.blocked()
 def test_stale_parent_or_host_rejected(self):
  self.collector.delegation=lambda *a:0;self.blocked()
  self.collector.delegation=lambda *a:1000
  self.source.host_value=replace(self.source.host_value,signed_observed_at=0);self.blocked()
 def test_changed_delegation_rejected(self):
  def reject(*a):raise NetworkError('conflict')
  self.collector.delegation=reject;self.blocked()
 def test_wrong_provider_and_nameservers_rejected(self):
  self.c=replace(self.c,provider='cloudflare');self.blocked()
  self.c=replace(self.c,provider='porkbun');self.b=replace(self.b,nameservers=('foreign.example.com',));self.blocked()
 def test_changed_request_after_success_rejected(self):
  self.run_init();self.source.host_value=replace(self.source.host_value,desired_revision=2)
  with self.assertRaises(NetworkError):self.run_init()
  self.assertEqual(len(self.http.writes()),1)
 def test_no_record_after_lost_response_never_redispatched(self):
  self.http.lost=True;self.http.apply_write=False
  self.assertEqual(self.run_init()['state'],'verifying')
  self.run_init();self.assertEqual(len(self.http.writes()),1)
