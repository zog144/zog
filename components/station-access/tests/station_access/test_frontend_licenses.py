import hashlib
import json
from pathlib import Path
import tempfile
from django.test import SimpleTestCase, override_settings

class FrontendLicenseTests(SimpleTestCase):
    def test_real_shipped_inventory_link_and_plain_text_are_public(self):
        from django.conf import settings
        root=Path(settings.STATION_ACCESS_FRONTEND_DIRECTORY)
        manifest=json.loads((root/'frontend-build.json').read_text())
        response=self.client.get('/frontend-build.json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(b''.join(response.streaming_content)),manifest)
        response=self.client.get('/')
        self.assertIn(('href="/'+manifest['licenses']+'"').encode(),b''.join(response.streaming_content))
        data=(root/manifest['licenses']).read_bytes()
        response=self.client.get('/licenses/')
        self.assertEqual(response.status_code,200);self.assertEqual(response.content,data)
        self.assertEqual(response['Content-Type'],'text/plain; charset=utf-8')
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertEqual(response['Cache-Control'],'no-store')
        response=self.client.get('/'+manifest['licenses'])
        self.assertEqual(b''.join(response.streaming_content),data)
        self.assertEqual(hashlib.sha256(data).hexdigest(),manifest['outputs'][manifest['licenses']])
    def test_invalid_missing_changed_or_unsafe_manifest_never_serves_other_files(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATION_ACCESS_FRONTEND_DIRECTORY=directory):
            root=Path(directory);(root/'assets').mkdir()
            self.assertEqual(self.client.get('/licenses/').status_code,404)
            for name in ('../private.txt','index.html','https://example/notice.txt'):
                (root/'frontend-build.json').write_text(json.dumps({'licenses':name,'outputs':{}}))
                self.assertEqual(self.client.get('/licenses/').status_code,404)
            name='assets/LICENSES-000000000000.txt';(root/name).write_text('<script>not executable</script>')
            (root/'frontend-build.json').write_text(json.dumps({'licenses':name,'outputs':{name:'wrong'}}))
            self.assertEqual(self.client.get('/licenses/').status_code,404)
    def test_legal_text_is_not_executable_html(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STATION_ACCESS_FRONTEND_DIRECTORY=directory):
            root=Path(directory);(root/'assets').mkdir();data=b'<script>alert("license fixture")</script>'
            sha=hashlib.sha256(data).hexdigest();name='assets/LICENSES-'+sha[:12]+'.txt';(root/name).write_bytes(data)
            (root/'frontend-build.json').write_text(json.dumps({'licenses':name,'outputs':{name:sha}}))
            response=self.client.get('/licenses/');self.assertEqual(response.content,data)
            self.assertEqual(response['Content-Type'],'text/plain; charset=utf-8');self.assertIn("default-src 'none'",response['Content-Security-Policy'])
