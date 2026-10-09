import base64
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import urllib.error
import zipfile
from unittest.mock import patch
from zog.version_share import GitHub, ShareError
from zog.version_share.archives import zip_files, preview_zip, import_zip, install_snapshot
from zog.version_share.handoffs import write_handoff, create_release
from zog.version_share.transfer import download_archive, retrieve_archive
from zog.version_share.workspace import object_hash, manifest, save_json
from test_publication import Server


def package(items):
    result = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as output:
        warnings.simplefilter('ignore', UserWarning)
        for name, content, mode in items:
            entry = zipfile.ZipInfo(name); entry.create_system = 3; entry.external_attr = mode << 16
            output.writestr(entry, content)
    return result.getvalue()


class MigrationServer(Server):
    def __init__(self):
        super().__init__()
        self.document = None; self.release = None; self.release_posts = 0; self.lose_release = False
    def handle(self, method, path, body):
        if path == '/repos/owner/demo':
            return {'id': 10, 'full_name': 'owner/demo', 'default_branch': 'main'}
        if '/contents/version-share-handoff.json' in path:
            content = json.dumps(self.document).encode()
            return {'encoding': 'base64', 'content': base64.b64encode(content).decode(), 'sha': object_hash('blob', content)}
        if '/releases/tags/' in path:
            if self.release is None: raise ShareError('not-found', 'missing')
            return self.release
        if method == 'POST' and path.endswith('/releases'):
            self.release_posts += 1
            self.release = dict(body, html_url='https://github.com/owner/demo/releases/tag/handoffs/pass3',
                                zipball_url='https://api.github.com/zip', tarball_url='https://api.github.com/tar')
            if self.lose_release:
                self.lose_release = False
                raise ShareError('network', 'lost accepted response', 'uncertain')
            return self.release
        return super().handle(method, path, body)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.client = MigrationServer()
        self.archive = self.root / 'source.zip'
        self.archive.write_bytes(package([('bundle/run', b'#!/bin/sh\n', stat.S_IFREG | 0o755),
                                          ('bundle/current', b'run', stat.S_IFLNK | 0o777),
                                          ('bundle/.env', b'secret-local-configuration', stat.S_IFREG | 0o600)]))
    def test_import_preview_exclusions_modes_provenance(self):
        preview = preview_zip(self.archive, 'bundle')
        self.assertEqual(preview['excluded'], ['.env'])
        target = self.root / 'imported'
        result = import_zip(self.client, 'owner', 'demo', self.archive, target, 'bundle')
        self.assertEqual(result['file_count'], 2)
        self.assertTrue((target / 'run').stat().st_mode & 0o111)
        self.assertTrue((target / 'current').is_symlink())
        self.assertEqual((target / 'current').read_bytes(), b'#!/bin/sh\n')
        self.assertFalse((target / '.env').exists())
        self.assertEqual(json.loads((target / '.version-share/import.json').read_text())['archive_sha256'], preview['archive_sha256'])
    def test_path_traversal_even_outside_selected_root(self):
        self.archive.write_bytes(package([('../escape', b'bad', stat.S_IFREG | 0o644), ('bundle/file', b'ok', 0)]))
        with self.assertRaises(ShareError): preview_zip(self.archive, 'bundle')
    def test_duplicate_and_prefix_collision(self):
        for items in ([('bundle/a', b'a', 0), ('bundle/a', b'b', 0)],
                      [('bundle/a', b'a', 0), ('bundle/a/b', b'b', 0)]):
            with self.subTest(items=items):
                self.archive.write_bytes(package(items))
                with self.assertRaises(ShareError): preview_zip(self.archive, 'bundle')
    def test_bad_link_leaves_no_destination(self):
        self.archive.write_bytes(package([('bundle/a', b'../escape', stat.S_IFLNK | 0o777)]))
        target = self.root / 'bad'
        with self.assertRaises(ShareError): import_zip(self.client, 'owner', 'demo', self.archive, target, 'bundle')
        self.assertFalse(target.exists())
    def test_existing_destination_preserved(self):
        target = self.root / 'existing'; target.mkdir(); (target / 'keep').write_text('keep')
        with self.assertRaises(ShareError): import_zip(self.client, 'owner', 'demo', self.archive, target, 'bundle')
        self.assertEqual((target / 'keep').read_text(), 'keep')
    def test_metadata_has_caller_reported_evidence(self):
        target = self.root / 'imported'
        import_zip(self.client, 'owner', 'demo', self.archive, target, 'bundle')
        notes = self.root / 'notes.md'; notes.write_text('Migration notes')
        tests = self.root / 'tests.json'; tests.write_text(json.dumps([{'command': 'pytest', 'result': 'passed'}]))
        document = write_handoff(self.client, target, notes, tests, ['owner/demo=' + 'a' * 40], ['No host test'])
        self.assertEqual(document['tests'][0]['origin'], 'caller-reported')
        self.assertEqual(document['dependencies'][0]['commit'], 'a' * 40)
        self.assertIn('archive_sha256', document['import'])
    def test_dependencies_repeat_and_modified_copy_rejected(self):
        from zog.version_share.handoffs import retrieve_dependencies
        source = self.root / 'dependency-source'; source.mkdir()
        (source / 'version-share-handoff.json').write_text(json.dumps({'dependencies': [{'repository': 'owner/demo', 'commit': 'a' * 40}]}))
        content = b'dependency source'
        files = {'file': {'sha': object_hash('blob', content), 'mode': '100644', 'content': base64.b64encode(content).decode()}}
        def retrieve(client, owner, program, target, commit):
            metadata = {'repository': 'owner/demo', 'commit': commit, 'files': manifest(files)}
            install_snapshot(files, target, metadata)
            return metadata
        with patch('zog.version_share.transfer.retrieve_archive', side_effect=retrieve) as downloader:
            first = retrieve_dependencies(self.client, source, self.root / 'dependencies')
            self.assertEqual(retrieve_dependencies(self.client, source, self.root / 'dependencies'), first)
            self.assertEqual(downloader.call_count, 1)
            (self.root / 'dependencies/owner/demo/file').write_text('modified')
            with self.assertRaises(ShareError): retrieve_dependencies(self.client, source, self.root / 'dependencies')
    def test_unpinned_dependency_rejected(self):
        from zog.version_share.handoffs import dependency
        with self.assertRaises(ShareError): dependency('owner/demo=main')
    def test_release_reconciles_lost_response_and_is_repeatable(self):
        self.client.refs['tags/handoffs/pass3'] = 'a' * 40
        self.client.document = {'schema': 1, 'notes': 'Release notes', 'tests': [], 'dependencies': []}
        self.client.lose_release = True
        first = create_release(self.client, 'owner', 'demo', 'pass3')
        self.assertEqual(first, create_release(self.client, 'owner', 'demo', 'pass3'))
        self.assertEqual(self.client.release_posts, 1)
        self.assertEqual(first['commit'], 'a' * 40)
    def test_release_conflicting_notes_never_overwritten(self):
        self.client.refs['tags/handoffs/pass3'] = 'a' * 40
        self.client.document = {'schema': 1, 'notes': 'Release notes'}
        create_release(self.client, 'owner', 'demo', 'pass3')
        self.client.release['body'] = 'external change'
        with self.assertRaises(ShareError): create_release(self.client, 'owner', 'demo', 'pass3')
        self.assertEqual(self.client.release['body'], 'external change')
    def test_bulk_retrieval_checks_full_manifest(self):
        content = package([('github-root/file.txt', b'hello', stat.S_IFREG | 0o644)])
        expected = {'file.txt': {'sha': object_hash('blob', b'hello'), 'mode': '100644'}}
        with patch('zog.version_share.transfer.remote_manifest', return_value=('a' * 40, expected)), patch('zog.version_share.transfer.download_archive', return_value=content):
            result = retrieve_archive(self.client, 'owner', 'demo', self.root / 'retrieved')
            self.assertEqual(result['files'], expected)
            expected['file.txt']['sha'] = 'b' * 40
            with self.assertRaises(ShareError): retrieve_archive(self.client, 'owner', 'demo', self.root / 'mismatch')
            self.assertFalse((self.root / 'mismatch').exists())
    def test_archive_redirect_does_not_forward_token(self):
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 302, 'redirect', {'Location': 'https://codeload.github.com/owner/demo/zip/commit?token=signed'}, None)
                return io.BytesIO(b'archive')
        self.client._opener = Opener()
        self.assertEqual(download_archive(self.client, '/repos/owner/demo/zipball/commit'), b'archive')
        self.assertEqual(calls[0].get_header('Authorization'), 'Bearer ' + self.client._token)
        self.assertIsNone(calls[1].get_header('Authorization'))
    def test_unapproved_redirect_rejected(self):
        class Opener:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 302, 'redirect', {'Location': 'https://example.com/private'}, None)
        self.client._opener = Opener()
        with self.assertRaises(ShareError): download_archive(self.client, '/repos/owner/demo/zipball/commit')


class RetryTests(unittest.TestCase):
    def test_get_retries_bounded_post_not_retried(self):
        calls, sleeps = [], []
        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                raise urllib.error.HTTPError(request.full_url, 503, 'temporary', {}, None)
        client = GitHub('fake-token', Opener(), sleeper=sleeps.append)
        with self.assertRaises(ShareError): client.request('GET', '/user')
        self.assertEqual(len(calls), 3); self.assertEqual(sleeps, [1, 2])
        with self.assertRaises(ShareError): client.request('POST', '/user/repos', {})
        self.assertEqual(len(calls), 4)
    def test_long_rate_limit_is_returned_without_sleep(self):
        sleeps = []
        class Opener:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 429, 'rate', {'Retry-After': '60'}, None)
        client = GitHub('fake-token', Opener(), sleeper=sleeps.append)
        with self.assertRaises(ShareError) as caught: client.request('GET', '/user')
        self.assertEqual(caught.exception.code, 'rate-limit'); self.assertEqual(sleeps, [])

if __name__ == '__main__': unittest.main()
