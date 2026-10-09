import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from zog.network_register.porkbun import PorkbunClient, PorkbunError, credentials

class PorkbunTests(unittest.TestCase):
    def setUp(self):
        self.client=PorkbunClient('fixture-public-key','fixture-secret-key');self.client._opener=Mock()
    def response(self,data):self.client._opener.open.return_value=io.BytesIO(json.dumps(data).encode())
    def test_verify_read_endpoint(self):
        self.response({'status':'SUCCESS','yourIp':'192.0.2.1'})
        self.assertEqual(self.client.verify(),{'authenticated':True,'provider':'porkbun'})
        request=self.client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.porkbun.com/api/json/v3/ping')
        self.assertEqual(json.loads(request.data)['secretapikey'],'fixture-secret-key')
    def test_domain_list_sanitized(self):
        self.response({'status':'SUCCESS','domains':[{'domain':'example.com','apiAccess':'yes','secret':'never-return'}]})
        page=self.client.list_domains()
        self.assertEqual(page['domains'],[{'id':'example.com','name':'example.com','status':'listed','api_access':True}]);self.assertFalse(page['more_available'])
    def test_pagination(self):
        self.response({'status':'SUCCESS','domains':[{'domain':f'a{i}.com'} for i in range(1000)]})
        self.assertEqual(self.client.list_domains(1000)['next_start'],2000)
    def test_invalid_and_duplicate_domains(self):
        for rows in [[{'domain':'bad/name.com'}],[{'domain':'a.com'},{'domain':'a.com'}],[{}],None]:
            self.response({'status':'SUCCESS','domains':rows})
            with self.assertRaises(PorkbunError):self.client.list_domains()
    def test_mutations_not_available(self):
        for path in ['/domain/create/example.com','/domain/renew/example.com','/dns/create/example.com','https://other.test','/balance/add']:
            with self.assertRaises(ValueError):self.client._read(path)
        self.client._opener.open.assert_not_called()
    def test_errors_do_not_echo_credentials(self):
        self.response({'status':'ERROR','message':'fixture-secret-key'})
        with self.assertRaises(PorkbunError) as caught:self.client.verify()
        self.assertNotIn('fixture-secret-key',str(caught.exception))
        self.client._opener.open.side_effect=urllib.error.HTTPError('https://api.porkbun.com',403,'fixture-secret-key',{},io.BytesIO(b'fixture-secret-key'))
        with self.assertRaises(PorkbunError) as caught:self.client.verify()
        self.assertNotIn('fixture-secret-key',str(caught.exception))
    def test_credentials_multiline(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'keys';p.write_text('API Key: fixture-public-key\nSecret Key:\nfixture-secret-key\n')
            self.assertEqual(credentials(p),('fixture-public-key','fixture-secret-key'))
            p.write_text('API Key: only-one\n')
            with self.assertRaises(ValueError):credentials(p)
    def test_records_and_inputs(self):
        self.response({'status':'SUCCESS','records':[]});self.assertEqual(self.client.records('example.com'),[])
        self.client._opener.reset_mock()
        for offset in (-1,True,'0'):
            with self.assertRaises(ValueError):self.client.list_domains(offset)
        with self.assertRaises(ValueError):self.client.records('../evil')
        self.client._opener.open.assert_not_called()
