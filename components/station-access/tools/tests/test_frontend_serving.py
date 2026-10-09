"""Actual Django views; no controller, database, cloud or external identity dependencies."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from django.conf import settings
if not settings.configured:
    settings.configure(DEFAULT_CHARSET='utf-8')
from django.http import Http404
from django.test import RequestFactory, override_settings
from zog.station_access import web


class SelectionServingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.request = RequestFactory().get('/')
        self.setting = override_settings(STATION_ACCESS_FRONTEND_INSTALLATION=self.root)
        self.setting.enable(); self.addCleanup(self.setting.disable)

    def release(self, identifier):
        root = self.root / 'releases' / identifier / 'dist'
        (root / 'assets').mkdir(parents=True)
        (root / 'index.html').write_text(identifier)
        data = ('legal ' + identifier).encode()
        sha = hashlib.sha256(data).hexdigest()
        name = 'assets/LICENSES-' + sha[:12] + '.txt'
        (root / name).write_bytes(data)
        (root / 'assets' / ('index-' + identifier + '.js')).write_text(identifier)
        (root / 'frontend-build.json').write_text(json.dumps({'licenses': name, 'outputs': {name: sha}}))
        return root, name

    def select(self, first, second):
        (self.root / 'selection.json').write_text(json.dumps({'schema': 1, 'active': first, 'retained': [first, second]}))

    def test_old_assets_retained_while_entry_and_notices_follow_active(self):
        first, second = 'a' * 32, 'b' * 32
        old, oldnotice = self.release(first); new, newnotice = self.release(second)
        self.select(second, first)
        response = web.portal(self.request)
        self.assertEqual(b''.join(response.streaming_content), second.encode())
        response = web.asset(self.request, oldnotice.removeprefix('assets/'))
        self.assertEqual(b''.join(response.streaming_content), (old / oldnotice).read_bytes())
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        response = web.licenses(self.request)
        self.assertEqual(response.content, (new / newnotice).read_bytes())
        self.assertIn('sandbox', response['Content-Security-Policy'])
        response = web.asset(self.request, 'index-' + first + '.js')
        self.assertEqual(b''.join(response.streaming_content), first.encode())
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_missing_corrupt_unsafe_or_symlink_selection_fails_closed(self):
        for data in (None, {}, {'schema': 1, 'active': '../private', 'retained': ['../private']},
                     {'schema': 1, 'active': 'a' * 32, 'retained': ['b' * 32]}):
            if data is not None:
                (self.root / 'selection.json').write_text(json.dumps(data))
            with self.assertRaises(Http404):
                web.portal(self.request)
        (self.root / 'selection.json').unlink()
        (self.root / 'selection.json').symlink_to('/etc/passwd')
        with self.assertRaises(Http404):
            web.portal(self.request)

    def test_only_hashed_asset_names_can_use_retention(self):
        for name in ('../installation.json', 'index.html', '../../etc/passwd', 'arbitrary.txt', 'folder/index-123.js'):
            with self.assertRaises(Http404):
                web.asset(self.request, name)


if __name__ == '__main__':
    unittest.main()
