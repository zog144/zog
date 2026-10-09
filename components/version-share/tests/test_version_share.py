import base64
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from zog.version_share.core import *
from zog.version_share.__main__ import main

TOKEN = 'fake-token-offline-only'
COMMIT = 'a' * 40

class FakeGitHub:
    def __init__(self):
        self.exists = False
        self.calls = []
        self.entries = []
        self.blobs = {}
        self.truncated = False
        self.add('.hidden', b'hidden\n')
        self.add('run', b'#!/bin/sh\necho test\n', '100755')
        self.add('current', b'run', '120000')
    def add(self, path, content, mode='100644'):
        sha = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        self.entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': sha})
        self.blobs[sha] = {'encoding': 'base64', 'content': base64.b64encode(content).decode()}
    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        repo = {'full_name': 'adam/demo', 'name': 'demo', 'id': 12, 'private': True,
                'default_branch': 'main', 'html_url': 'https://github.com/adam/demo',
                'owner': {'login': 'adam'}, 'topics': ['zog-project']}
        if path == '/user': return {'login': 'adam'}
        if path.startswith('/user/repos?'): return [repo]
        if method == 'POST':
            assert body['private'] and body['auto_init']
            self.exists = True
            return repo
        if method == 'PUT': return body
        if path == '/repos/adam/demo':
            if not self.exists: raise ShareError('not-found', 'missing')
            return repo
        if '/commits/' in path: return {'sha': COMMIT, 'commit': {'tree': {'sha': 'b' * 40}}}
        if '/git/trees/' in path: return {'tree': self.entries, 'truncated': self.truncated}
        if '/git/blobs/' in path: return self.blobs[path.rsplit('/', 1)[1]]
        raise AssertionError(path)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / 'source'
        self.client = FakeGitHub()
        self.client.exists = True
    def retrieve(self, reference=None):
        return retrieve(self.client, 'adam', 'demo', self.destination, reference)
    def test_end_to_end(self):
        self.client.exists = False
        self.assertTrue(create_program(self.client, 'adam', 'demo')['created'])
        self.assertFalse(create_program(self.client, 'adam', 'demo')['created'])
        self.assertEqual(list_programs(self.client, 'adam')[0]['name'], 'demo')
        result = self.retrieve()
        self.assertEqual(result['commit'], COMMIT)
        self.assertEqual((self.destination / '.hidden').read_bytes(), b'hidden\n')
        self.assertTrue((self.destination / 'run').stat().st_mode & 0o111)
        self.assertEqual(os.readlink(self.destination / 'current'), 'run')
        self.assertEqual(json.loads((self.destination / '.version-share/baseline.json').read_text()), result)
        self.assertNotIn(TOKEN, str(result))
    def test_slash_reference(self):
        self.retrieve('feature/work')
        self.assertTrue(any('/commits/feature%2Fwork' in call[1] for call in self.client.calls))
    def test_existing_destination(self):
        self.destination.mkdir()
        (self.destination / 'keep').write_text('untouched')
        with self.assertRaises(ShareError): self.retrieve()
        self.assertEqual((self.destination / 'keep').read_text(), 'untouched')
        self.assertEqual(self.client.calls, [])
    def test_truncated(self):
        self.client.truncated = True
        with self.assertRaises(ShareError): self.retrieve()
        self.assertFalse(self.destination.exists())
    def test_bad_hash(self):
        next(iter(self.client.blobs.values()))['content'] = 'd3Jvbmc='
        with self.assertRaises(ShareError): self.retrieve()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])
    def test_unsafe_paths(self):
        for path in ('../escape', '/absolute', 'a/../../escape', '.git/config', '.version-share/x', 'a\\b'):
            with self.subTest(path=path):
                client = FakeGitHub(); client.exists = True; client.add(path, b'bad')
                with self.assertRaises(ShareError): retrieve(client, 'adam', 'demo', self.destination)
                self.assertFalse(self.destination.exists())
    def test_unsafe_links(self):
        for target in (b'../escape', b'/absolute', b'bad-link'):
            with self.subTest(target=target):
                client = FakeGitHub(); client.exists = True; client.add('bad-link', target, '120000')
                with self.assertRaises(ShareError): retrieve(client, 'adam', 'demo', self.destination)
                self.assertFalse(self.destination.exists())
    def test_submodule(self):
        self.client.entries.append({'path': 'submodule', 'type': 'commit', 'mode': '160000', 'sha': COMMIT})
        with self.assertRaises(ShareError): self.retrieve()
    def test_partial_create(self):
        client = self.client; client.exists = False
        original = client.request
        def request(method, path, body=None):
            if method == 'PUT': raise ShareError('forbidden', 'denied')
            return original(method, path, body)
        client.request = request
        with self.assertRaises(ShareError) as caught: create_program(client, 'adam', 'demo')
        self.assertEqual(caught.exception.outcome, 'published')

class TransportTests(unittest.TestCase):
    def client(self, error=None, payload=None):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                if error: raise error
                return io.BytesIO(json.dumps(payload).encode())
        opener = Opener()
        return GitHub(TOKEN, opener, sleeper=lambda delay: None), opener
    def test_auth_header(self):
        client, opener = self.client(payload={'login': 'adam'})
        self.assertTrue(check_access(client)['authenticated'])
        self.assertEqual(opener.request.get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertNotIn(TOKEN, opener.request.full_url)
    def test_http_errors(self):
        for status, code in ((401, 'authentication'), (403, 'forbidden'), (404, 'not-found'), (429, 'rate-limit'), (500, 'remote')):
            with self.subTest(status=status):
                client, _ = self.client(error=urllib.error.HTTPError('url', status, TOKEN, {}, io.BytesIO(TOKEN.encode())))
                with self.assertRaises(ShareError) as caught: client.request('GET', '/user')
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(TOKEN, str(caught.exception))
    def test_mutation_uncertainty(self):
        client, _ = self.client(error=urllib.error.URLError(TOKEN))
        with self.assertRaises(ShareError) as caught: client.request('POST', '/user/repos', {})
        self.assertEqual(caught.exception.outcome, 'uncertain')
        self.assertNotIn(TOKEN, str(caught.exception))
    def test_incomplete_mutation_response(self):
        client, _ = self.client(error=http.client.IncompleteRead(b'partial'))
        with self.assertRaises(ShareError) as caught: client.request('POST', '/user/repos', {})
        self.assertEqual(caught.exception.outcome, 'uncertain')
        self.assertEqual(caught.exception.code, 'network')
    def test_redirect_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
    def test_invalid_tokens(self):
        for token in ('', 'a\nb', 'a b'):
            with self.assertRaises(ShareError): GitHub(token)
    def test_cli_missing_token(self):
        output = io.StringIO()
        with patch('sys.stdout', output):
            status = main(['--token-file', '/nonexistent-token', '--owner', 'adam', '--json', 'check-access'])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())['error']['code'], 'configuration')

if __name__ == '__main__': unittest.main()
