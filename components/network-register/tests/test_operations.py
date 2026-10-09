import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from zog.network_register.operations import register, ensure_a


def client():
    c = Mock(account='a'*32, registrar='/accounts/'+'a'*32+'/registrar')
    c.check.return_value = {'domains': [{'name': 'example.uk', 'registrable': True, 'tier': 'standard', 'pricing': {'currency': 'USD', 'registration_cost': '5.30', 'renewal_cost': '5.30'}}]}
    c.result.return_value = {'state': 'succeeded', 'completed': True}
    return c


class RegistrationTests(unittest.TestCase):
    def test_individual_classification_durable_before_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            c = client()
            def purchase(method, path, body):
                saved = json.loads((Path(d)/'registration-example.uk.json').read_text())
                self.assertEqual(saved['request'], body)
                self.assertEqual(body['contact_extensions'], {'registrant_type': 'FIND'})
                return {'state': 'succeeded'}
            c.result.side_effect = purchase
            register(c, 'example.uk', '6', d, 'FIND')

    def test_over_budget_never_purchases(self):
        with tempfile.TemporaryDirectory() as d:
            c = client()
            with self.assertRaises(ValueError): register(c, 'example.uk', '5.29', d)
            c.result.assert_not_called()

    def test_uncertain_purchase_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            c = client(); c.result.side_effect = TimeoutError('uncertain')
            with self.assertRaises(TimeoutError): register(c, 'example.uk', '6', d)
            with self.assertRaises(RuntimeError): register(c, 'example.uk', '6', d)
            self.assertEqual(c.result.call_count, 1)
            self.assertEqual(json.loads((Path(d)/'registration-example.uk.json').read_text())['phase'], 'submission-uncertain')

    def test_failed_durable_prepare_prevents_purchase(self):
        with tempfile.TemporaryDirectory() as d:
            c = client()
            with patch('zog.network_register.operations.save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): register(c, 'example.uk', '6', d)
            c.result.assert_not_called()

    def test_success_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            c = client()
            register(c, 'example.uk', '6', d)
            with self.assertRaises(RuntimeError): register(c, 'example.uk', '6', d)
            self.assertEqual(c.result.call_count, 1)
            self.assertFalse(c.result.call_args.args[2]['auto_renew'])

    def test_nonstandard_or_invalid_price_never_purchases(self):
        for changes in [{'tier': 'premium'}, {'registrable': False}, {'pricing': {'currency':'EUR','registration_cost':'1'}}, {'pricing': {'currency':'USD','registration_cost':'NaN'}}]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as d:
                c=client(); c.check.return_value['domains'][0].update(changes)
                with self.assertRaises(ValueError): register(c, 'example.uk', '6', d)
                c.result.assert_not_called()


class DnsTests(unittest.TestCase):
    def setup_client(self, record):
        c=client()
        c.pages.side_effect = [[{'id':'zone','name':'example.uk','account':{'id':c.account}}], record]
        return c

    def test_foreign_record_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.setup_client([{'id':'record','type':'A','comment':'someone else'}])
            with self.assertRaises(ValueError): ensure_a(c,'example.uk','demo.example.uk','192.0.2.1',d)
            c.result.assert_not_called()

    def test_idempotent_owned_record(self):
        record={'id':'record','type':'A','name':'demo.example.uk','content':'192.0.2.1','ttl':60,'proxied':False,'comment':'Managed by Zog network-register: demo.example.uk'}
        with tempfile.TemporaryDirectory() as d:
            c=self.setup_client([record])
            self.assertEqual(ensure_a(c,'example.uk','demo.example.uk','192.0.2.1',d),record)
            c.result.assert_not_called()

    def test_suffix_confusion_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c=client()
            with self.assertRaises(ValueError): ensure_a(c,'example.uk','notexample.uk','192.0.2.1',d)
            c.pages.assert_not_called()

    def test_multiple_records_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.setup_client([{},{}])
            with self.assertRaises(ValueError): ensure_a(c,'example.uk','demo.example.uk','192.0.2.1',d)
            c.result.assert_not_called()


if __name__ == '__main__': unittest.main()
