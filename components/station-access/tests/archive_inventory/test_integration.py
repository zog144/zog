"""Real provider + signed receiver + download authorization, isolated local fixture."""
import base64
import io
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from django.test import Client, TestCase, override_settings
from django.apps import apps
from unittest import skipUnless
from django.core.management import call_command
from zog.host_identify.archive import issue
from zog.station_access.archive_inventory import tests as inventory_fixture


@skipUnless(apps.is_installed('archive_mirror'), 'Optional provider enabled by tools/archive-inventory/test-provider.py')
@override_settings(HOST_IDENTITY_ORIGIN=inventory_fixture.ORIGIN, ALLOWED_HOSTS=['registry.example.test', 'testserver'])
class ProviderIntegrationTests(TestCase):
    setUp = inventory_fixture.InventoryTests.setUp
    send = inventory_fixture.InventoryTests.send
    mirror = inventory_fixture.InventoryTests.mirror
    item = inventory_fixture.InventoryTests.item
    report = inventory_fixture.InventoryTests.report
    # This module is run separately with the optional archive_mirror app enabled.
    def test_provider_report_command_and_shared_portal_boundary(self):
        from zog.archive_mirror.store import publish
        from zog.archive_mirror.observation import observe
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            intent=root/'intent.json'
            desired=dict(version=1,selected=True,revision=1,endpoint='https://mirror.example.test',lease_expires_at=int(time.time())+800)
            intent.write_text(json.dumps(dict(version=1,host_id=str(self.host.id),desired=desired)));intent.chmod(0o640)
            keyring=root/'public.json';keyring.write_text(json.dumps(dict(version=1,keys={'fixture':base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()})))
            config=root/'mirror.json';config.write_text(json.dumps(dict(root=str(root/'store'),host_id=str(self.host.id),collections=['sources','root-filesystems'],intent_file=str(intent),endpoint=desired['endpoint'],issuer='https://registry.example.test',audience='fixture',keyring=str(keyring))))
            with override_settings(ARCHIVE_MIRROR_CONFIGURATION=str(config)):
                source=root/'source.tar.xz';source.write_bytes(b'local-fixture-archive')
                archive=publish(source,'sources','source',{'import':'local','release_approved':False,'password':'must-not-appear'})
                publish(source,'root-filesystems','root-filesystem',{'import':'local','release_approved':False})
                (root/'store/scheduler.json').write_text(json.dumps(dict(host_id=str(self.host.id),revision=1,time=time.time())))
                key=root/'key.pem';key.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
                reporting=root/'report.json';reporting.write_text(json.dumps(dict(registry='https://registry.example.test',identity_key=str(key))));reporting.chmod(0o600)
                delivered=[]
                class Reply:
                    def __init__(self,status,body):self.status_code=status;self.raw=io.BytesIO(body)
                    def __enter__(self):return self
                    def __exit__(self,*args):return False
                def transport(session,message,**kwargs):
                    self.assertTrue(kwargs['verify']);self.assertFalse(kwargs['allow_redirects']);self.assertFalse(session.trust_env)
                    reply=self.send(None,message=message);delivered.append(reply.status_code)
                    return Reply(reply.status_code,reply.content)
                with patch('requests.Session.send',new=transport):
                    call_command('report_archive_inventory',configuration=str(reporting))
                self.assertEqual(delivered,[200])
                from zog.archive_mirror import notices, notice_contract as c
                value,_=inventory_fixture.InventoryTests.notice_fixture(self)
                value['archive_digest']=archive.digest;value['source_identity']['digest']=archive.digest
                value['records'][0]['source_digest']=archive.digest
                notices.publish(archive,value)
                reporting.write_text(json.dumps(dict(registry='https://registry.example.test',identity_key=str(key),observation_version=2)))
                with patch('requests.Session.send',new=transport):
                    call_command('report_archive_inventory',configuration=str(reporting))
                self.assertEqual(delivered,[200,200,200])
                from urllib.parse import urlencode
                notice_url='/api/archives/notices/?'+urlencode(dict(mirror=str(self.host.id),snapshot=self.mirror()['snapshot'],collection='sources',digest=archive.digest,format='text'))
                notice_response=self.client.get(notice_url)
                self.assertEqual(notice_response.status_code,200)
                self.assertEqual(notice_response.content,c.document(value))
                self.assertNotIn(b'must-not-appear',notice_response.content)
                mirror=self.mirror();self.assertEqual(mirror['state'],'serving');self.assertEqual(mirror['archive_count'],2)
                self.assertEqual(mirror['summary']['unique_content_bytes'],len(source.read_bytes()))
                url=f'/collections/sources/archives/{archive.digest}.tar.xz'
                machine=Client();self.assertEqual(machine.get(url).status_code,403)
                # Browser administrator credentials do not grant archive download rights.
                self.assertEqual(self.client.get(url).status_code,403)
                token=issue(self.key,'fixture','https://registry.example.test','fixture',self.host.id,['download'],['sources'])[0]
                response=machine.get(url,HTTP_AUTHORIZATION='Bearer '+token)
                self.assertEqual(response.status_code,200);self.assertEqual(b''.join(response.streaming_content),source.read_bytes())
                denied=machine.get(url.replace('/sources/','/root-filesystems/'),HTTP_AUTHORIZATION='Bearer '+token)
                self.assertEqual(denied.status_code,403)
                desired['selected']=False;intent.write_text(json.dumps(dict(version=1,host_id=str(self.host.id),desired=desired)))
                self.assertEqual(machine.get(url,HTTP_AUTHORIZATION='Bearer '+token).status_code,503)
                self.assertEqual(self.client.get('/archives/').status_code,200)
                self.assertTrue((root/'store/objects'/archive.digest).exists())
                self.assertEqual(len(observe()['items']),2)
