"""Real separate DB connections and a restarted Python process, not mocked locks."""
import json
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from django.test import TransactionTestCase, Client, override_settings
from django.db import connection, close_old_connections
from django.utils import timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import signatures
from zog.station_access.host_registry.models import Host, HostIdentity, SecurityGate, ReplayRecord
from zog.station_access.host_registry import identity

@override_settings(HOST_IDENTITY_ORIGIN='https://registry.example.test',ALLOWED_HOSTS=['registry.example.test'])
class ConcurrentIdentityTests(TransactionTestCase):
    def setUp(self):
        SecurityGate.objects.get_or_create(pk=1)
        self.key=Ed25519PrivateKey.generate();self.fp=signatures.fingerprint(self.key.public_key())
        self.host=Host.objects.create(label='concurrent')
        HostIdentity.objects.create(host=self.host,fingerprint=self.fp,public_key=signatures.public_text(self.key.public_key()),approved_by='test',approved_at=timezone.now())
        self.message=signatures.sign('https://registry.example.test/api/hosts/'+str(self.host.id)+'/heartbeat/',b'{"version":1}',self.key,str(self.host.id))
    def send(self):
        close_old_connections()
        try:
            h={'HTTP_'+k.upper().replace('-','_'):v for k,v in self.message.headers.items() if k.lower() not in ('content-type','content-length')}
            return Client().post(self.message.path_url,self.message.body,content_type='application/json',HTTP_HOST='registry.example.test',**h).status_code
        finally:close_old_connections()
    def test_concurrent_duplicate_only_commits_once(self):
        barrier=threading.Barrier(2)
        def worker():barrier.wait();return self.send()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(results.count(200),1,results)
        self.assertTrue(all(x in (200,401,503) for x in results),results)
        self.assertEqual(self.send(),401)
        self.assertEqual(ReplayRecord.objects.count(),1)
    def test_revocation_blocks_waiting_heartbeat(self):
        ready=threading.Event();release=threading.Event()
        def revoke():
            close_old_connections()
            try:
                with identity.locked():
                    HostIdentity.objects.filter(pk=self.fp).update(status='revoked')
                    ready.set();release.wait(timeout=5)
            finally:close_old_connections()
        with ThreadPoolExecutor(2) as pool:
            rev=pool.submit(revoke);self.assertTrue(ready.wait(5))
            beat=pool.submit(self.send);release.set();rev.result();result=beat.result()
        self.assertIn(result,(401,503));self.assertEqual(self.send(),401)
        self.host.refresh_from_db();self.assertIsNone(self.host.signed_last_received)
    def test_replay_survives_process_restart(self):
        self.assertEqual(self.send(),200)
        database=connection.settings_dict['NAME']
        self.assertNotIn('memory',str(database),'Run with file-backed test database as documented')
        code='''import os,json,sys
os.environ['DJANGO_SETTINGS_MODULE']='zog.station_access.project.settings'
from django.conf import settings
settings.DATABASES['default']['NAME']=sys.argv[1]
settings.HOST_IDENTITY_ORIGIN='https://registry.example.test'
settings.ALLOWED_HOSTS=['registry.example.test']
import django;django.setup()
from django.test import Client
m=json.load(sys.stdin)
r=Client().post(m['path'],m['body'],content_type='application/json',HTTP_HOST='registry.example.test',**m['headers'])
assert r.status_code==401,r.status_code
print('Restarted worker rejected replay')
'''
        headers={'HTTP_'+k.upper().replace('-','_'):v for k,v in self.message.headers.items() if k.lower() not in ('content-type','content-length')}
        result=subprocess.run([sys.executable,'-c',code,str(database)],input=json.dumps({'headers':headers,'body':self.message.body.decode(),'path':self.message.path_url}),text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('rejected replay',result.stdout)

class ConcurrentApprovalRemovalTests(TransactionTestCase):
    def setUp(self):
        SecurityGate.objects.get_or_create(pk=1)
    def run_workers(self,operations):
        barrier=threading.Barrier(len(operations))
        def worker(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:return operation()
                except ValueError:return 'conflict'
            finally:close_old_connections()
        with ThreadPoolExecutor(len(operations)) as pool:return list(pool.map(worker,operations))
    def pending(self,host=None):
        from zog.station_access.host_registry.models import EnrollmentRequest
        from datetime import timedelta
        key=Ed25519PrivateKey.generate();fp=signatures.fingerprint(key.public_key())
        EnrollmentRequest.objects.create(fingerprint=fp,public_key=signatures.public_text(key.public_key()),claimed_host_id=str(host.pk) if host else '',claims={'hostname':'test'},expires_at=timezone.now()+timedelta(hours=1))
        return fp
    def test_concurrent_same_fingerprint_creates_once(self):
        from zog.station_access.host_registry.models import SecurityAudit
        fp=self.pending()
        def approve():return str(identity.approve('admin',fp,fp).pk)
        results=self.run_workers([approve,approve]);self.assertEqual(results[0],results[1]);self.assertNotEqual(results[0],'conflict')
        self.assertEqual(Host.objects.count(),1);self.assertEqual(SecurityAudit.objects.filter(action='approve-key').count(),1)
    def test_concurrent_replacement_keys_only_one_is_approved(self):
        host=Host.objects.create();one=self.pending(host);two=self.pending(host)
        results=self.run_workers([lambda:str(identity.approve('admin',one,one,host.pk).pk),lambda:str(identity.approve('admin',two,two,host.pk).pk)])
        self.assertEqual(results.count('conflict'),1);self.assertEqual(HostIdentity.objects.filter(host=host,status='approved').count(),1)
    def test_archive_races_policy_change_under_same_gate(self):
        from zog.station_access.host_registry import retirement
        from zog.station_access.host_registry.models import ArchivePolicy
        host=Host.objects.create();revision=retirement.preview(host)['revision']
        results=self.run_workers([lambda:str(retirement.archive_host('admin',host.pk,revision).pk),lambda:identity.set_policy('admin',host.pk,['download'],['sources'])])
        self.assertEqual(results.count('conflict'),1)
        host.refresh_from_db();self.assertFalse(host.archived_at and ArchivePolicy.objects.filter(host=host,operations=['download']).exists())
    def test_inventory_and_new_aws_approval_share_the_gate(self):
        from zog.station_access.host_registry.models import EnrollmentRequest, InventoryScan
        from zog.station_access.host_registry.inventory import commit_region
        from tests.host_registry.test_matching_removal import CLOUD
        fp=self.pending();EnrollmentRequest.objects.filter(pk=fp).update(claims={'hostname':'test','cloud':CLOUD})
        scan=InventoryScan.objects.create(scope='test')
        def inventory():
            commit_region(CLOUD['account_id'],CLOUD['region'],[{'InstanceId':CLOUD['instance_id'],'State':{'Name':'running'}}],scan)
            return 'inventory'
        results=self.run_workers([lambda:str(identity.approve('admin',fp,fp).pk),inventory])
        self.assertIn('inventory',results);self.assertEqual(Host.objects.count(),1)
        host=Host.objects.get()
        # Inventory won: stale new-host approval was blocked and explicit refresh is needed.
        if 'conflict' in results:identity.approve('admin',fp,fp,host.pk)
        self.assertEqual(HostIdentity.objects.get(pk=fp).host_id,host.pk)


@override_settings(HOST_IDENTITY_ORIGIN='https://registry.example.test',ALLOWED_HOSTS=['registry.example.test'])
class ConcurrentManagedTests(TransactionTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from cryptography.hazmat.primitives import serialization
        SecurityGate.objects.get_or_create(pk=1)
        self.key=Ed25519PrivateKey.generate();self.fp=signatures.fingerprint(self.key.public_key())
        self.host=Host.objects.create(label='managed-concurrent')
        HostIdentity.objects.create(host=self.host,fingerprint=self.fp,public_key=signatures.public_text(self.key.public_key()),approved_by='test',approved_at=timezone.now())
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        path=Path(self.folder.name)/'control.pem'
        key=Ed25519PrivateKey.generate();path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));path.chmod(0o600)
        self.authority=str(uuid.uuid4())
        self.config=override_settings(HOST_MANAGED_ADMISSION_ENABLED=True,HOST_MANAGED_AUTHORITY_ID=self.authority,HOST_MANAGED_SIGNING_KEY_FILE=str(path));self.config.enable();self.addCleanup(self.config.disable)
        self.payload=dict(version=1,installation_id=str(uuid.uuid4()),state_volume_id=str(uuid.uuid4()),authority_id=self.authority,registry_id='primary',challenge=str(uuid.uuid4()),previous=None,boot_id=str(uuid.uuid4()))
    def send(self,value):
        close_old_connections()
        try:
            packet=signatures.sign(f'https://registry.example.test/api/hosts/{self.host.pk}/managed-session/',json.dumps(value).encode(),self.key,str(self.host.pk))
            h={'HTTP_'+k.upper().replace('-','_'):v for k,v in packet.headers.items() if k.lower() not in ('content-type','content-length')}
            r=Client().post(packet.path_url,packet.body,content_type='application/json',HTTP_HOST='registry.example.test',**h)
            return r.status_code
        finally:close_old_connections()
    def test_competing_process_sessions_cannot_both_advance_same_checkpoint(self):
        from zog.station_access.host_registry.models import ManagedAdmission
        barrier=threading.Barrier(2)
        values=[self.payload,dict(self.payload,challenge=str(uuid.uuid4()))]
        def worker(value):barrier.wait();return self.send(value)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(worker,values))
        self.assertEqual(results.count(200),1,results)
        self.assertEqual(ManagedAdmission.objects.get(host=self.host).epoch,1)
        self.assertTrue(all(code in (200,409,503) for code in results))
    def test_same_pending_request_is_idempotent_across_workers(self):
        from zog.station_access.host_registry.models import ManagedAdmission
        barrier=threading.Barrier(2)
        def worker(_):barrier.wait();return self.send(self.payload)
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(worker,range(2)))
        self.assertIn(200,results)
        self.assertTrue(all(code in (200,503) for code in results))
        self.assertEqual(self.send(self.payload),200)
        self.assertEqual(ManagedAdmission.objects.get(host=self.host).epoch,1)
