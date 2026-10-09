import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, override_settings
from zog.archive_mirror import store
from zog.archive_mirror.models import Archive, ReviewedSource, SourcePinSet
from zog.archive_mirror.source_inputs import populate, deactivate, decode_manifest

class Response:
    def __init__(self, data, url, final=None, length=True, fail_after=False):
        self.data=data;self.url=url;self.final=final or url;self.offset=0;self.fail_after=fail_after
        self.headers={'Content-Length':str(len(data))} if length else {}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def geturl(self):return self.final
    def read(self,size):
        if self.fail_after and self.offset:
            raise OSError('interrupted')
        if self.offset>=len(self.data):return b''
        value=self.data[self.offset:self.offset+size];self.offset+=len(value);return value

class Opener:
    def __init__(self, factory):self.factory=factory;self.calls=[]
    def open(self, request, timeout=0):
        self.calls.append((request.full_url,timeout))
        return self.factory(request.full_url)

class ReviewedSourceTests(TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.config={'root':str(self.root/'store'),'collections':['sources','root-filesystems'],
                     'maximum_archive_bytes':1024*1024}
        self.configpath=self.root/'config.json';self.configpath.write_text(json.dumps(self.config))
        self.override=override_settings(ARCHIVE_MIRROR_CONFIGURATION=str(self.configpath));self.override.enable();self.addCleanup(self.override.disable)

    def manifest(self, records, identity='2026-10'):
        path=self.root/(identity.replace('/','-')+'.json')
        path.write_text(json.dumps({'schema':1,'pin_set':identity,'date':'2026-10-01','sources':records},
                                   sort_keys=True,separators=(',',':')))
        return path

    def record(self,data=b'exact source',package='example',source='release',
               url='https://upstream.example/example.tar.gz'):
        return {'package':package,'source':source,'url':url,'sha256':hashlib.sha256(data).hexdigest()}

    def test_canonical_download_publishes_exact_digest(self):
        data=b'exact source';record=self.record(data);opener=Opener(lambda url:Response(data,url))
        pin_set,archives=populate(self.manifest([record]),opener)
        self.assertTrue(pin_set.active);self.assertTrue(pin_set.complete);self.assertEqual(len(opener.calls),1)
        self.assertEqual(archives[0].digest,record['sha256'])
        self.assertEqual((self.root/'store/objects'/record['sha256']).read_bytes(),data)

    def test_already_present_digest_avoids_upstream(self):
        data=b'exact source';record=self.record(data)
        local=self.root/'source';local.write_bytes(data)
        archive=store.publish(local,'sources','source',{'import':'local'})
        opener=Opener(lambda url:(_ for _ in ()).throw(AssertionError('network used')))
        pin_set,archives=populate(self.manifest([record]),opener)
        self.assertEqual(opener.calls,[]);self.assertEqual(archives[0].pk,archive.pk);self.assertTrue(pin_set.active)

    def test_wrong_bytes_rejected_without_publication(self):
        record=self.record(b'expected');opener=Opener(lambda url:Response(b'wrong',url))
        with self.assertRaisesRegex(ValueError,'checksum'):
            populate(self.manifest([record]),opener)
        self.assertFalse(Archive.objects.exists())
        self.assertFalse(SourcePinSet.objects.get().complete)

    def test_redirect_rejected(self):
        data=b'exact';record=self.record(data)
        opener=Opener(lambda url:Response(data,url,'https://cdn.example/exact'))
        with self.assertRaisesRegex(ValueError,'redirect'):
            populate(self.manifest([record]),opener)
        self.assertFalse(Archive.objects.exists())

    def test_interrupted_download_has_no_published_partial(self):
        data=b'x'*10;record=self.record(data)
        opener=Opener(lambda url:Response(data,url,fail_after=True))
        with self.assertRaises(OSError):populate(self.manifest([record]),opener)
        self.assertFalse(Archive.objects.exists())
        objects=self.root/'store/objects'
        self.assertFalse(objects.exists() and any(objects.iterdir()))

    def test_duplicate_bytes_deduplicate_and_keep_multiple_declarations(self):
        data=b'same';digest=hashlib.sha256(data).hexdigest()
        records=[
            {'package':'one','source':'release','url':'https://upstream.example/one.tar.gz','sha256':digest},
            {'package':'two','source':'vendor','url':'https://upstream.example/two.tar.gz','sha256':digest},
        ]
        opener=Opener(lambda url:Response(data,url))
        pin_set,archives=populate(self.manifest(records),opener)
        self.assertEqual(len(opener.calls),1);self.assertEqual(Archive.objects.count(),1)
        self.assertEqual(ReviewedSource.objects.filter(pin_set=pin_set).count(),2)
        self.assertEqual(archives[0].pk,archives[1].pk)

    def test_credentials_and_unsupported_schemes_rejected(self):
        good=self.record()
        for url in ('https://user:secret@upstream.example/a.tar.gz','http://upstream.example/a.tar.gz',
                    'file:///tmp/a','https://upstream.example/a.tar.gz?token=secret'):
            bad=dict(good,url=url)
            with self.assertRaises(ValueError):decode_manifest(self.manifest([bad],str(uuid.uuid4())).read_bytes())
        self.assertFalse(Archive.objects.exists())

    def test_catalogue_exposes_bounded_safe_reviewed_provenance(self):
        data=b'exact';record=self.record(data)
        pin_set,archives=populate(self.manifest([record]),Opener(lambda url:Response(data,url)))
        from zog.archive_mirror.views import item
        value=item(archives[0])
        self.assertEqual(value['reviewed_sources'][0]['canonical_url'],record['url'])
        self.assertEqual(value['reviewed_sources'][0]['pin_set'],pin_set.identity)
        from django.http import JsonResponse
        self.assertNotIn('secret',JsonResponse(value).content.decode('utf-8'))

    def test_active_pin_set_protects_pruning(self):
        data=b'exact';record=self.record(data)
        pin_set,archives=populate(self.manifest([record]),Opener(lambda url:Response(data,url)))
        archive=archives[0];store.prune()
        self.assertTrue(Archive.objects.filter(pk=archive.pk).exists())
        deactivate(pin_set.identity);store.prune()
        self.assertFalse(Archive.objects.filter(pk=archive.pk).exists())
        self.assertFalse((self.root/'store/objects'/record['sha256']).exists())
