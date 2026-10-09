import copy
import json
import unittest
from urllib.parse import urlsplit, parse_qs
from zog.network_register.cloudflare import CloudflareDns, CloudflareTransport, BASE
from zog.network_register.contracts import NetworkError
from zog.network_register.models import Connection, RecordSnapshot

ACCOUNT, ZONE, RECORD = 'a' * 32, 'b' * 32, 'c' * 32
MARKER = 'zog-operation:12345678-1234-1234-1234-123456789abc'


class Secrets:
    def __init__(self): self.calls = []
    def resolve(self, owner, connection, reference):
        self.calls.append((owner, connection, reference))
        return {'api_token': 'fixture-secret'}


class Transport:
    def __init__(self):
        self.calls = []
        self.status, self.headers = 200, {}
        self.payload = dict(success=True, result=[])
        self.raw = None
        self.error = None

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.error: raise self.error
        return self.status, self.headers, self.raw if self.raw is not None else json.dumps(self.payload).encode()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.secrets, self.transport = Secrets(), Transport()
        self.connection = Connection('cf', 'owner', 'cloudflare', ACCOUNT, 'vault:1', status='ready')
        self.client = CloudflareDns(self.connection, self.secrets, self.transport)
        self.record = dict(id=RECORD, name='one.hosts.example.com', type='A', content='8.8.8.8', ttl=300, proxied=False, comment=MARKER)
        self.snapshot = RecordSnapshot('one.hosts.example.com', '8.8.8.8', 300)

    def assertCode(self, code, call):
        with self.assertRaises(NetworkError) as ctx: call()
        self.assertEqual(ctx.exception.code, code)
        self.assertNotIn('fixture-secret', str(ctx.exception))
        return ctx.exception

    def test_create_payload_has_dns_only_marker_and_no_assumed_idempotency_header(self):
        self.transport.payload['result'] = self.record
        self.assertEqual(self.client.create_record(ZONE, self.snapshot, marker=MARKER, idempotency_key='step')['id'], RECORD)
        method, url, kw = self.transport.calls[0]
        self.assertEqual(method, 'POST'); self.assertEqual(url, BASE + '/zones/' + ZONE + '/dns_records')
        self.assertEqual(json.loads(kw['body']), {k:v for k,v in self.record.items() if k != 'id'})
        self.assertNotIn('Idempotency-Key', kw['headers'])
        self.assertEqual(self.secrets.calls, [('owner', 'cf', 'vault:1')])

    def test_update_and_delete_address_exact_id(self):
        self.transport.payload['result'] = self.record
        self.client.update_record(ZONE, RECORD, self.snapshot, marker=MARKER, idempotency_key='step')
        self.client.delete_record(ZONE, RECORD, idempotency_key='step')
        self.assertEqual([x[0] for x in self.transport.calls], ['PATCH', 'DELETE'])
        self.assertTrue(all(x[1].endswith('/' + RECORD) for x in self.transport.calls))

    def test_pagination_and_unknown_record_types(self):
        future = dict(id=RECORD, name='*.example.com', type='FUTURE', content='opaque')
        self.transport.payload.update(result=[future], result_info={'page': 1, 'total_pages': 2})
        page = self.client.list_records(ZONE)
        self.assertEqual(page.next_cursor, '2'); self.assertEqual(page.items[0], future)
        self.transport.payload['result_info'] = {'page': 2, 'total_pages': 2}
        self.assertIsNone(self.client.list_records(ZONE, '2').next_cursor)
        self.assertEqual(parse_qs(urlsplit(self.transport.calls[-1][1]).query)['page'], ['2'])

    def test_missing_or_inconsistent_pagination_not_empty_inventory(self):
        self.assertCode('validation', lambda: self.client.list_records(ZONE))
        for info in ({'page': 2, 'total_pages': 2}, {'page': 1, 'total_pages': 1001}, {'page': 1, 'total_pages': 2}):
            self.transport.payload['result_info'] = info
            self.assertCode('validation', lambda: self.client.list_records(ZONE))

    def test_account_and_zone_identity_checks(self):
        self.transport.payload['result'] = dict(id=ZONE, name='example.com', account={'id': 'd'*32}, status='active')
        self.assertCode('permission', lambda: self.client.get_zone(ZONE))
        self.transport.payload['result']['account']['id'] = ACCOUNT
        self.transport.payload['result']['id'] = RECORD
        self.assertCode('conflict', lambda: self.client.get_zone(ZONE))

    def test_http200_failure_never_counts_as_empty_or_success(self):
        self.transport.payload = dict(success=False, errors=[{'message':'fixture-secret'}], result=[])
        self.assertCode('validation', lambda: self.client.list_records(ZONE))
        self.assertCode('uncertain', lambda: self.client.create_record(ZONE, self.snapshot, marker=MARKER, idempotency_key='step'))

    def test_status_categories_and_retry_after(self):
        for status, category in ((401,'authentication'), (403,'permission'), (404,'not-found'), (409,'conflict'), (429,'rate-limit'), (503,'transient')):
            self.transport.status = status; self.transport.headers = {'Retry-After': '120'}
            error = self.assertCode(category, lambda: self.client.get_record(ZONE, RECORD))
            self.assertEqual(error.retry_after, 120)
        self.assertCode('uncertain', lambda: self.client.delete_record(ZONE, RECORD, idempotency_key='step'))

    def test_transport_failure_is_sanitized_and_mutation_unknown(self):
        self.transport.error = OSError('fixture-secret')
        self.assertCode('transient', lambda: self.client.get_record(ZONE, RECORD))
        self.assertCode('uncertain', lambda: self.client.delete_record(ZONE, RECORD, idempotency_key='step'))

    def test_redirect_and_malformed_response_not_success(self):
        self.transport.status = 302
        self.assertCode('validation', lambda: self.client.get_record(ZONE, RECORD))
        self.transport.status = 200; self.transport.raw = b'not-json fixture-secret'
        self.assertCode('validation', lambda: self.client.get_record(ZONE, RECORD))
        self.assertCode('uncertain', lambda: self.client.delete_record(ZONE, RECORD, idempotency_key='step'))

    def test_endpoint_input_cannot_escape_fixed_host(self):
        self.assertCode('validation', lambda: self.client.get_zone('../registrar'))
        self.assertEqual(self.transport.calls, [])
        self.assertCode('validation', lambda: CloudflareTransport().request('GET', 'https://evil.example/', headers={}, body=None, timeout=1))

    def test_read_capability_does_not_claim_write_authority(self):
        self.transport.payload.update(result=[], result_info={'page': 1, 'total_pages': 0})
        caps = self.client.inspect_connection()
        self.assertTrue(caps['read'].authorized)
        self.assertIsNone(caps['write_a'].authorized)

    def test_global_key_shape_is_rejected(self):
        self.secrets.resolve = lambda *args: {'api_key': 'fixture-secret', 'email': 'person@example.com'}
        self.assertCode('authentication', lambda: self.client.get_zone(ZONE))
        self.assertEqual(self.transport.calls, [])

    def test_unrelated_service_label_survives_inspection(self):
        row=dict(self.record,name='_acme-challenge.example.com',type='TXT',content='token')
        self.transport.payload.update(result=[row],result_info={'page':1,'total_pages':1})
        self.assertEqual(self.client.list_records(ZONE).items[0]['name'],'_acme-challenge.example.com')


if __name__ == '__main__': unittest.main()
