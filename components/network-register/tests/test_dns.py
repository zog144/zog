import copy
import tempfile
import unittest
from unittest.mock import patch
from zog.network_register.dns import DnsRecords, DnsConflict


class Provider:
    account = 'a' * 32
    def __init__(self):
        self.rows = []
        self.calls = []
        self.lose_response = False
    def pages(self, path, query):
        if path == '/zones':
            return [{'id':'zone', 'name':'example.uk', 'account':{'id':self.account}}]
        return copy.deepcopy(self.rows)
    def result(self, method, path, body=None):
        self.calls.append(method)
        if method == 'DELETE':
            self.rows = []
            result = {'id':'record'}
        else:
            self.rows = [dict(body, id='record')]
            result = copy.deepcopy(self.rows[0])
        if self.lose_response:
            self.lose_response = False
            raise TimeoutError('response lost after applying')
        return result


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Provider()
        self.dns = DnsRecords(self.provider, 'example.uk', self.temp.name)
    def ensure(self, address='192.0.2.1', owner='host-one'):
        return self.dns.ensure_a('one.hosts.example.uk', address, owner)
    def remove(self):
        return self.dns.remove_a('one.hosts.example.uk','host-one')
    def test_create_update_noop_delete_noop(self):
        self.assertEqual(self.ensure()['action'],'created')
        self.assertEqual(self.ensure()['action'],'unchanged')
        self.assertEqual(self.ensure('192.0.2.2')['action'],'updated')
        self.assertEqual(self.remove()['action'],'deleted')
        self.assertEqual(self.remove()['action'],'absent')
        self.assertEqual(self.provider.calls,['POST','PATCH','DELETE'])
    def test_owner_reservation_survives_removal(self):
        self.ensure();self.remove()
        with self.assertRaises(DnsConflict):self.ensure(owner='host-two')
    def test_foreign_record_never_adopted(self):
        self.provider.rows=[{'id':'foreign','type':'A','name':'one.hosts.example.uk','content':'192.0.2.8'}]
        with self.assertRaises(DnsConflict):self.ensure()
        with self.assertRaises(DnsConflict):self.remove()
        self.assertEqual(self.provider.calls,[])
    def test_changed_provider_identity_blocks_mutation(self):
        self.ensure();self.provider.rows[0]['id']='replacement'
        with self.assertRaises(DnsConflict):self.ensure('192.0.2.2')
    def test_create_response_loss_does_not_duplicate(self):
        self.provider.lose_response=True
        with self.assertRaises(TimeoutError):self.ensure()
        self.assertEqual(self.ensure()['action'],'unchanged')
        self.assertEqual(self.provider.calls,['POST'])
    def test_delete_response_loss_reconciles_absence(self):
        self.ensure();self.provider.lose_response=True
        with self.assertRaises(TimeoutError):self.remove()
        self.assertEqual(self.remove()['action'],'absent')
        self.assertEqual(self.provider.calls,['POST','DELETE'])
    def test_prepare_failure_prevents_mutation(self):
        with patch('zog.network_register.dns.save',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.ensure()
        self.assertEqual(self.provider.calls,[])
    def test_result_save_failure_recovers(self):
        from zog.network_register.state import save
        calls=[]
        def write(path,value):
            calls.append(1)
            if len(calls)==2:raise OSError('result save failed')
            return save(path,value)
        with patch('zog.network_register.dns.save',side_effect=write):
            with self.assertRaises(OSError):self.ensure()
        self.assertEqual(self.ensure()['action'],'unchanged')
        self.assertEqual(self.provider.calls,['POST'])
    def test_invalid_targets_and_ttl(self):
        for name,address,ttl in [('outside.uk','192.0.2.1',60),('one.example.uk','::1',60),('one.example.uk','192.0.2.1',0)]:
            with self.assertRaises(ValueError):self.dns.ensure_a(name,address,'host',ttl)
        self.assertEqual(self.provider.calls,[])
