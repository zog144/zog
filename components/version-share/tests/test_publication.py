import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import unquote
from unittest.mock import patch
from zog.version_share import ShareError, publish, resume, abandon, status, compare, list_versions
from zog.version_share.publication import tree_hash
from zog.version_share.workspace import object_hash, snapshot, manifest, locked, save_json

TOKEN = 'offline-test-credential'

class Server:
    """In-memory repository with fast-forward validation and response-loss injection."""
    _token = TOKEN
    def __init__(self):
        self.refs = {'heads/main': 'a' * 40}
        self.trees = {}
        self.commits = {'a' * 40: {'tree': {'sha': tree_hash({})}, 'parents': []}}
        self.trees[tree_hash({})] = {}
        self.blobs = {}
        self.calls = []
        self.fail_after = None
        self.fail_before = None
        self.race = None
    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        key = method + ' ' + path.split('?')[0]
        if self.fail_before == key:
            self.fail_before = None
            raise ShareError('network', 'simulated loss', 'uncertain')
        result = self.handle(method, path, body)
        if self.fail_after == key:
            self.fail_after = None
            raise ShareError('network', 'simulated loss', 'uncertain')
        return result
    def handle(self, method, path, body):
        prefix = '/repos/owner/demo'
        if path == '/user': return {'login': 'owner', 'id': 123}
        if path == prefix: return {'id': 10, 'full_name': 'owner/demo'}
        tail = path[len(prefix):].split('?')[0]
        if method == 'GET' and tail.startswith('/git/ref/'):
            ref = unquote(tail[len('/git/ref/'):])
            if ref not in self.refs: raise ShareError('not-found', 'no ref')
            return {'object': {'type': 'commit', 'sha': self.refs[ref]}}
        if method == 'POST' and tail == '/git/blobs':
            data = base64.b64decode(body['content'])
            sha = object_hash('blob', data); self.blobs[sha] = data
            return {'sha': sha}
        if method == 'POST' and tail == '/git/trees':
            files = {}
            for entry in body['tree']:
                data = entry['content'].encode() if 'content' in entry else self.blobs[entry['sha']]
                sha = object_hash('blob', data); self.blobs[sha] = data
                files[entry['path']] = {'mode': entry['mode'], 'sha': sha}
            sha = tree_hash(files); self.trees[sha] = files
            return {'sha': sha}
        if method == 'POST' and tail == '/git/commits':
            sha = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()
            self.commits[sha] = {'tree': {'sha': body['tree']}, 'parents': [{'sha': p} for p in body['parents']]}
            return dict(self.commits[sha], sha=sha)
        if method == 'PATCH' or (method == 'POST' and tail == '/git/refs'):
            if self.race:
                self.refs['heads/main'] = self.race
                self.race = None
            ref = unquote(tail[len('/git/refs/'):]) if method == 'PATCH' else body['ref'][5:]
            if method == 'POST' and ref in self.refs:
                raise ShareError('conflict', 'exists', 'not-published')
            if method == 'PATCH':
                assert body['force'] is False
                if not self.ancestor(self.refs[ref], body['sha']):
                    raise ShareError('conflict', 'non fast-forward', 'not-published')
            self.refs[ref] = body['sha']
            return {'object': {'type': 'commit', 'sha': body['sha']}}
        if method == 'GET' and tail.startswith('/compare/'):
            old, new = tail[len('/compare/'):].split('...')
            return {'status': 'identical' if old == new else 'ahead' if self.ancestor(old, new) else 'diverged'}
        if method == 'GET' and tail.startswith('/commits/'):
            ref = unquote(tail[len('/commits/'):])
            sha = self.refs.get('heads/' + ref, self.refs.get('tags/' + ref, ref))
            return {'sha': sha, 'commit': self.commits[sha]}
        if method == 'GET' and tail.startswith('/git/trees/'):
            files = self.trees[tail.rsplit('/', 1)[1]]
            return {'truncated': False, 'tree': [dict(item, path=name, type='blob') for name, item in files.items()]}
        if method == 'GET' and tail == '/tags':
            return [{'name': name[5:], 'commit': {'sha': sha}} for name, sha in self.refs.items() if name.startswith('tags/')]
        raise AssertionError((method, path, body))
    def ancestor(self, old, new):
        if old == new: return True
        return any(self.ancestor(old, p['sha']) for p in self.commits[new]['parents'])
    def advance(self, parent):
        sha = hashlib.sha1(('advance' + parent).encode()).hexdigest()
        self.commits[sha] = {'tree': {'sha': tree_hash({})}, 'parents': [{'sha': parent}]}
        return sha

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.client = Server()
        self.first = self.copy('first'); self.second = self.copy('second')
    def copy(self, name):
        root = self.root / name; (root / '.version-share').mkdir(parents=True)
        save_json(root / '.version-share/baseline.json', {'schema': 1, 'repository': 'owner/demo', 'repository_id': 10,
                                                       'commit': 'a' * 40, 'files': {}})
        (root / 'hello.txt').write_text('hello\n')
        return root
    def publish(self, root=None, version='pass2', identifier='attempt1', branch='main'):
        return publish(self.client, root or self.first, branch, 'Test publication', version, identifier)
    def test_publish_then_stale_rejected_new_branch_allowed(self):
        first = self.publish()
        with self.assertRaises(ShareError) as caught: self.publish(self.second, identifier='attempt2', version='pass2-second')
        self.assertEqual(caught.exception.code, 'conflict')
        second = self.publish(self.second, identifier='attempt2', version='pass2-second', branch='review/second')
        self.assertEqual(self.client.refs['heads/main'], first['commit'])
        self.assertEqual(self.client.refs['heads/review/second'], second['commit'])
    def test_response_lost_after_branch_acceptance(self):
        self.client.fail_after = 'PATCH /repos/owner/demo/git/refs/heads/main'
        with self.assertRaises(ShareError) as caught: self.publish()
        self.assertEqual(caught.exception.outcome, 'uncertain')
        head = self.client.refs['heads/main']
        (self.first / 'hello.txt').write_text('edited after interruption')
        result = resume(self.client, self.first)
        self.assertEqual(result['commit'], head)
        self.assertEqual(len(self.client.commits), 2)
        self.assertEqual(status(self.client, self.first)['changes']['modified'], ['hello.txt'])
    def test_response_lost_before_branch_acceptance(self):
        self.client.fail_before = 'PATCH /repos/owner/demo/git/refs/heads/main'
        with self.assertRaises(ShareError): self.publish()
        self.assertEqual(self.client.refs['heads/main'], 'a' * 40)
        result = resume(self.client, self.first)
        self.assertEqual(self.client.refs['heads/main'], result['commit'])
    def test_commit_response_loss_is_deterministic(self):
        self.client.fail_after = 'POST /repos/owner/demo/git/commits'
        with self.assertRaises(ShareError): self.publish()
        self.assertEqual(len(self.client.commits), 2)
        result = resume(self.client, self.first)
        self.assertEqual(len(self.client.commits), 2)
        self.assertEqual(result['outcome'], 'published')
    def test_tag_response_loss(self):
        self.client.fail_after = 'POST /repos/owner/demo/git/refs'
        with self.assertRaises(ShareError) as caught: self.publish()
        self.assertEqual(caught.exception.outcome, 'published')
        result = resume(self.client, self.first)
        self.assertEqual(self.client.refs['tags/handoffs/pass2'], result['commit'])
        self.assertEqual(len([c for c in self.client.calls if c[0] == 'POST' and c[1].endswith('/git/refs')]), 1)
    def test_retry_after_remote_descendant(self):
        self.client.fail_after = 'PATCH /repos/owner/demo/git/refs/heads/main'
        with self.assertRaises(ShareError): self.publish()
        commit = self.client.refs['heads/main']; later = self.client.advance(commit)
        self.client.refs['heads/main'] = later
        self.assertEqual(resume(self.client, self.first)['commit'], commit)
        self.assertEqual(self.client.refs['heads/main'], later)
    def test_ambiguous_divergence_blocks(self):
        self.client.fail_after = 'PATCH /repos/owner/demo/git/refs/heads/main'
        with self.assertRaises(ShareError): self.publish()
        self.client.refs['heads/main'] = self.client.advance('a' * 40)
        with self.assertRaises(ShareError) as caught: resume(self.client, self.first)
        self.assertEqual(caught.exception.outcome, 'uncertain')
        with self.assertRaises(ShareError): abandon(self.first)
    def test_race_rejected_and_abandon_preserves_source(self):
        self.client.race = self.client.advance('a' * 40)
        with self.assertRaises(ShareError) as caught: self.publish()
        self.assertEqual(caught.exception.outcome, 'not-published')
        abandon(self.first)
        self.assertEqual((self.first / 'hello.txt').read_text(), 'hello\n')
        self.publish(identifier='another', branch='recovered')
    def test_new_rejection_not_confused_with_prior_success(self):
        self.publish()
        (self.first / 'hello.txt').write_text(TOKEN)
        with self.assertRaises(ShareError) as caught:
            self.publish(identifier='different', version='later')
        self.assertEqual(caught.exception.outcome, 'not-published')
    def test_handoff_immutable(self):
        first = self.publish()
        (self.first / 'hello.txt').write_text('changed')
        with self.assertRaises(ShareError): self.publish(identifier='different')
        self.assertEqual(self.client.refs['tags/handoffs/pass2'], first['commit'])
    def test_old_publication_id_returns_recorded_result(self):
        first = self.publish()
        (self.first / 'hello.txt').write_text('changed')
        self.publish(identifier='attempt2', version='pass3')
        self.assertEqual(self.publish(), first)
        self.assertEqual(len(self.client.commits), 3)
    def test_secret_content_stops_before_upload(self):
        (self.first / 'hello.txt').write_text(TOKEN)
        with self.assertRaises(ShareError) as caught: self.publish()
        self.assertEqual(caught.exception.code, 'secret')
        self.assertFalse(any(call[0] != 'GET' for call in self.client.calls))
    def test_obvious_secret_and_excluded_files(self):
        (self.first / 'github-token.txt').write_text(TOKEN)
        (self.first / '.env').write_text(TOKEN)
        files, excluded = snapshot(self.first, TOKEN)
        self.assertNotIn('.env', files); self.assertIn('.env', excluded)
        (self.first / 'hello.txt').write_text('gh' + 'p_' + 'A' * 36)
        with self.assertRaises(ShareError): snapshot(self.first, TOKEN)
    def test_deleted_files_binary_modes_and_link(self):
        first = self.publish()
        (self.first / 'hello.txt').unlink()
        (self.first / 'binary').write_bytes(b'\xff\x00\xfe')
        (self.first / 'run').write_text('#!/bin/sh\n'); (self.first / 'run').chmod(0o755)
        (self.first / 'link').symlink_to('run')
        second = self.publish(identifier='attempt2', version='pass3')
        delta = compare(self.client, 'owner', 'demo', first['commit'], second['commit'])['changes']
        self.assertEqual(delta['deleted'], ['hello.txt'])
        files = self.client.trees[self.client.commits[second['commit']]['tree']['sha']]
        self.assertEqual(files['run']['mode'], '100755')
        self.assertEqual(files['link']['mode'], '120000')
        self.assertEqual(len(list_versions(self.client, 'owner', 'demo')), 2)
    def test_local_lock(self):
        with locked(self.first):
            with self.assertRaises(ShareError): self.publish()
    def test_fsync_failure_prevents_remote_mutation(self):
        with patch('zog.version_share.workspace.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises((OSError, ShareError)): self.publish()
        self.assertFalse(any(call[0] != 'GET' for call in self.client.calls))
    def test_baseline_write_failure_recoverable(self):
        original = save_json
        def fail(path, value):
            if str(path).endswith('baseline.json'): raise OSError('disk failure')
            return original(path, value)
        with patch('zog.version_share.publication.save_json', side_effect=fail):
            with self.assertRaises((OSError, ShareError)): self.publish()
        commit = self.client.refs['heads/main']
        self.assertEqual(resume(self.client, self.first)['commit'], commit)
    def test_new_branch_response_loss(self):
        self.client.fail_after = 'POST /repos/owner/demo/git/refs'
        with self.assertRaises(ShareError) as caught:
            self.publish(branch='new-branch')
        self.assertEqual(caught.exception.outcome, 'uncertain')
        commit = self.client.refs['heads/new-branch']
        self.assertEqual(resume(self.client, self.first)['commit'], commit)
        self.assertEqual(self.client.refs['heads/main'], 'a' * 40)
    def test_identifier_cannot_change_parameters(self):
        self.publish()
        with self.assertRaises(ShareError):
            publish(self.client, self.first, 'main', 'Different message', 'pass2', 'attempt1')
    def test_symlink_to_excluded_state_rejected(self):
        (self.first / 'leak').symlink_to('.version-share/baseline.json')
        with self.assertRaises(ShareError): self.publish()
        self.assertFalse(any(call[0] != 'GET' for call in self.client.calls))
    def test_tag_taken_after_lost_branch_response(self):
        self.client.fail_after = 'PATCH /repos/owner/demo/git/refs/heads/main'
        with self.assertRaises(ShareError): self.publish()
        self.client.refs['tags/handoffs/pass2'] = 'a' * 40
        with self.assertRaises(ShareError) as caught: resume(self.client, self.first)
        self.assertEqual(caught.exception.outcome, 'published')
        self.assertEqual(self.client.refs['tags/handoffs/pass2'], 'a' * 40)
    def test_manifest_existing_excluded_file_blocks(self):
        path = self.first / '.version-share/baseline.json'
        value = json.loads(path.read_text())
        value['files']['.env'] = {'sha': 'b' * 40, 'mode': '100644'}
        save_json(path, value)
        with self.assertRaises(ShareError) as caught: self.publish()
        self.assertEqual(caught.exception.code, 'secret')
    def test_tree_hash_matches_git(self):
        root = self.root / 'hash-test'; root.mkdir()
        for name in ('z.txt', 'a.txt', 'a/nested', 'a.c'):
            path = root / name; path.parent.mkdir(exist_ok=True); path.write_text(name)
        (root / 'z.txt').chmod(0o755); (root / 'link').symlink_to('z.txt')
        files, _ = snapshot(root)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
        expected = subprocess.check_output(['git', '-C', str(root), 'write-tree'], text=True).strip()
        self.assertEqual(tree_hash(files), expected)

if __name__ == '__main__': unittest.main()
