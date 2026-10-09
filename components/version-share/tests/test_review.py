import base64
import importlib
import unittest
from unittest.mock import patch
from zog.version_share import review, ShareError
from zog.version_share.workspace import object_hash

review_module = importlib.import_module('zog.version_share.review')


class Source:
    def __init__(self):
        self.blobs, self.calls = {}, []

    def entry(self, content, mode='100644'):
        sha = object_hash('blob', content)
        self.blobs[sha] = content
        return {'sha': sha, 'mode': mode}

    def request(self, method, path):
        self.calls.append((method, path))
        assert method == 'GET'
        return {'encoding': 'base64', 'content': base64.b64encode(self.blobs[path.rsplit('/', 1)[1]]).decode()}


class ReviewTests(unittest.TestCase):
    def run_review(self, source, old, new, **kwargs):
        with patch.object(review_module, 'remote_manifest', side_effect=[('a'*40, old), ('b'*40, new)]):
            return review(source, 'owner', 'demo', 'main', 'review/change', **kwargs)

    def test_added_deleted_modified_and_exact_links(self):
        source = Source()
        old = {'changed': source.entry(b'old\n'), 'gone': source.entry(b'gone\n')}
        new = {'changed': source.entry(b'new\n'), 'a #?.txt': source.entry(b'added\n')}
        result = self.run_review(source, old, new)
        self.assertEqual(result['counts'], {'added': 1, 'deleted': 1, 'modified': 1})
        self.assertTrue(result['complete_text_diffs'])
        self.assertIn('/'+'b'*40+'/a%20%23%3F.txt', result['files'][0]['after_url'])
        self.assertIn('--- /dev/null', result['files'][0]['patch'])
        self.assertIn('+++ /dev/null', result['files'][1]['patch'])
        self.assertIn('-old\n+new\n', result['files'][2]['patch'])

    def test_mode_only_avoids_download(self):
        source = Source(); entry = source.entry(b'script')
        result = self.run_review(source, {'run': entry}, {'run': dict(entry, mode='100755')})
        self.assertEqual(result['files'][0]['diff_status'], 'mode-only')
        self.assertEqual(source.calls, [])

    def test_binary_and_symlink_target(self):
        source = Source()
        new = {'binary': source.entry(b'\x00text'), 'link': source.entry(b'target', '120000')}
        result = self.run_review(source, {}, new)
        self.assertEqual(result['files'][0]['diff_status'], 'binary')
        self.assertIn('No newline at end of file', result['files'][1]['patch'])
        self.assertFalse(result['complete_text_diffs'])

    def test_file_budget_preserves_full_inventory(self):
        source = Source(); new = {str(i): source.entry(str(i).encode()) for i in range(4)}
        result = self.run_review(source, {}, new, maximum_files=1)
        self.assertEqual(len(result['files']), 4)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(result['files'][1]['diff_status'], 'omitted-budget')
        source.calls.clear()
        self.run_review(source, {}, new, maximum_files=0)
        self.assertEqual(source.calls, [])

    def test_size_lines_and_total_patch_limits(self):
        source = Source()
        result = self.run_review(source, {}, {'large': source.entry(b'x'*65537), 'lines': source.entry(b'x\n'*2001)})
        self.assertEqual([r['diff_status'] for r in result['files']], ['omitted-size', 'omitted-lines'])
        with patch.object(review_module, 'MAXIMUM_PATCH', 10):
            result = self.run_review(source, {}, {'small': source.entry(b'abc')})
        self.assertEqual(result['files'][0]['diff_status'], 'omitted-budget')
        self.assertNotIn('patch', result['files'][0])

    def test_corrupt_blob_fails_integrity(self):
        source = Source(); entry = source.entry(b'good'); source.blobs[entry['sha']] = b'bad'
        with self.assertRaises(ShareError) as raised:
            self.run_review(source, {}, {'file': entry})
        self.assertEqual(raised.exception.code, 'integrity')

    def test_invalid_encoding_and_limit(self):
        source = Source(); entry = source.entry(b'good')
        with patch.object(source, 'request', return_value={'encoding': 'base64', 'content': '!'}):
            with self.assertRaises(ShareError) as raised:
                self.run_review(source, {}, {'file': entry})
            self.assertEqual(raised.exception.code, 'remote')
        for limit in (-1, 101, True):
            with self.assertRaises(ShareError):
                review(source, 'owner', 'demo', 'a', 'b', limit)

    def test_identical_trees(self):
        source = Source(); files = {'same': source.entry(b'same')}
        result = self.run_review(source, files, files)
        self.assertEqual(result['files'], [])
        self.assertTrue(result['complete_text_diffs'])
        self.assertEqual(source.calls, [])
