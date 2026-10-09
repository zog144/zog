import copy
import time
import uuid
from unittest.mock import patch
from django.test import override_settings
from zog.host_identify import managed, signatures
from tests.host_registry.test_identity import IdentityTests, ORIGIN
from zog.station_access.host_registry.models import ManagedAdmission, HostIdentity

# Reuse only helpers; avoid inheriting the baseline test methods twice.
from django.test import TestCase

@override_settings(HOST_IDENTITY_ORIGIN=ORIGIN, ALLOWED_HOSTS=['registry.example.test','testserver'])
class ManagedTests(TestCase):
    request=IdentityTests.request
    send=IdentityTests.send
    pending=IdentityTests.pending
    approved=IdentityTests.approved
    heartbeat=IdentityTests.heartbeat
    def setUp(self):
        IdentityTests.setUp(self)
        self.authority=str(uuid.uuid4())
        self.override_managed=override_settings(HOST_MANAGED_ADMISSION_ENABLED=True,HOST_MANAGED_AUTHORITY_ID=self.authority,
            HOST_MANAGED_SIGNING_KEY_FILE=self.root.name+'/archive-signing.pem')
        self.override_managed.enable();self.addCleanup(self.override_managed.disable)
        # Test fixture shares a generated key file only; production instructions
        # require a separate dedicated control signer.
        self.value=dict(version=1,installation_id=str(uuid.uuid4()),state_volume_id=str(uuid.uuid4()),
            authority_id=self.authority,registry_id='primary',challenge=str(uuid.uuid4()),previous=None,boot_id=str(uuid.uuid4()))
    def session_request(self,host,value=None):
        return self.request(f'/api/hosts/{host.pk}/managed-session/',value or self.value,subject=str(host.pk))
    def expected(self,host,value):
        return dict(iss=ORIGIN,aud=self.authority,sub=str(host.pk),fingerprint=self.fp,
            **{k:value[k] for k in ('installation_id','state_volume_id','registry_id','challenge','previous','boot_id')})
    def establish(self,host,value=None):
        value=value or self.value
        response=self.send(self.session_request(host,value));self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response['Cache-Control'],'no-store')
        return managed.session(response.json()['session'],self.signing.public_key(),self.expected(host,value))
    def test_managed_session_required_after_first_admission(self):
        host=self.approved();claims=self.establish(host)
        self.assertEqual(self.send(self.heartbeat(host)).status_code,401)
        packet=self.request(f'/api/hosts/{host.pk}/heartbeat/',dict(self.report,managed_session=claims['jti']),subject=str(host.pk))
        response=self.send(packet);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['managed_session'],claims['jti'])
        self.assertEqual(self.send(packet).status_code,401)
    def test_managed_idempotent_and_rollback_refused(self):
        host=self.approved();first=self.establish(host)
        second=self.establish(host);self.assertEqual(first,second)
        wrong=dict(self.value,challenge=str(uuid.uuid4()))
        self.assertEqual(self.send(self.session_request(host,wrong)).status_code,409)
        next_value=dict(wrong,previous={k:first[k] for k in ('epoch','checkpoint')})
        next_claims=self.establish(host,next_value);self.assertEqual(next_claims['epoch'],2)
        self.assertEqual(self.send(self.session_request(host)).status_code,409)
        old=self.request(f'/api/hosts/{host.pk}/heartbeat/',dict(self.report,managed_session=first['jti']),subject=str(host.pk))
        self.assertEqual(self.send(old).status_code,401)
    def test_managed_revocation_race(self):
        host=self.approved();proof=__import__('zog.station_access.host_registry.identity',fromlist=['proof']).proof
        def revoke(*args):
            result=proof(*args);HostIdentity.objects.filter(pk=self.fp).update(status='revoked');return result
        with patch('zog.station_access.host_registry.identity.proof',side_effect=revoke):
            self.assertEqual(self.send(self.session_request(host)).status_code,401)
        self.assertFalse(ManagedAdmission.objects.exists())
    def test_managed_expired_and_foreign_bindings(self):
        host=self.approved();claims=self.establish(host)
        with patch('zog.station_access.host_registry.managed_views.time.time',return_value=claims['exp']+1):
            self.assertEqual(self.send(self.session_request(host)).status_code,409)
        value=dict(self.value,installation_id=str(uuid.uuid4()),previous={k:claims[k] for k in ('epoch','checkpoint')})
        self.assertEqual(self.send(self.session_request(host,value)).status_code,409)
    def test_managed_unsigned_and_pending_denied(self):
        self.pending()
        self.assertFalse(ManagedAdmission.objects.exists())
        host=self.approved()
        response=self.client.post(f'/api/hosts/{host.pk}/managed-session/',self.value,content_type='application/json')
        self.assertEqual(response.status_code,401)
    def test_managed_station_history_loss_blocks(self):
        host=self.approved();claims=self.establish(host)
        ManagedAdmission.objects.all().delete()
        value=dict(self.value,challenge=str(uuid.uuid4()),previous={k:claims[k] for k in ('epoch','checkpoint')})
        self.assertEqual(self.send(self.session_request(host,value)).status_code,409)

    def test_managed_end_to_end_consumer_enrollment_session_and_control(self):
        import hashlib,json,os,tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from zog.host_identify import initialization
        from zog.host_discover.managed import ManagedState
        from zog.host_discover.managed_transport import Runtime
        from zog.host_discover import admission
        from zog.host_install import state_inspect
        from zog.host_install.state_contract import StateError
        from zog.box_control.host_gateway import dispatch
        from zog.station_access.host_registry import identity
        # Production consumer and journal; real temporary keys/files. Mount and
        # fixed-account evidence are synthetic, not a live-boot acceptance claim.
        bundle=json.loads((Path(__file__).parent/'fixtures/managed-state.json').read_text())
        bundle['bootstrap']['control_authority']['authority_id']=self.authority
        bundle['bootstrap']['registries'][0]['origin']=ORIGIN
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'host-discover';home.mkdir(mode=0o700)
            identity_dir=home/'identity';identity_dir.mkdir(mode=0o700);(home/'control').mkdir(mode=0o700)
            b=bundle['bootstrap'];auth=dict(schema=1,kind='zog-identity-initialization',
                authorization_id=b['initialization']['authorization_id'],installation_id=b['installation_id'],
                state_volume_id=b['state']['state_volume_id'],identity_directory=str(identity_dir),account_profile='zog-host-accounts-v1',expected_fingerprint=None)
            receipt=initialization.prepare(identity_dir,auth)
            self.key=initialization.load_existing(identity_dir,receipt);self.fp=signatures.fingerprint(self.key.public_key())
            auth['identity_directory']=b['state']['identity_directory']
            receipt['authorization_sha256']=hashlib.sha256(initialization.encode(auth)).hexdigest()
            (identity_dir/'initialization.json').write_bytes(initialization.encode(auth))
            (identity_dir/'receipt.json').write_bytes(initialization.encode(receipt))
            context=SimpleNamespace(fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY),bundle=bundle,recheck=lambda:None)
            state=ManagedState();state.context=context
            project=dict(bindings={'boot_id':str(uuid.uuid4())},receipt=receipt)
            metadata=state_inspect.metadata;read=admission.read_at
            service_metadata=lambda fd,u,g,m,*args:metadata(fd,os.geteuid(),os.getegid(),m,*args)
            service_read=lambda fd,n,*args:read(fd,n,os.geteuid(),os.getegid(),0o600)
            owner=self
            class HTTPSFixture:
                def post(self,url,payload,key,subject,ca):
                    message=signatures.sign(url,json.dumps(payload).encode(),key,subject)
                    response=owner.send(message)
                    owner.assertIn(response.status_code,(200,202),response.content)
                    return response.json()
            runtime=None
            try:
                with patch('zog.host_discover.admission.observe',return_value=project),patch('zog.host_discover.admission.metadata',side_effect=service_metadata),patch('zog.host_install.state_inspect.metadata',side_effect=service_metadata),patch('zog.host_discover.admission.read_at',side_effect=service_read):
                    runtime=Runtime(state).open(True);runtime.close();runtime=Runtime(state).open()
                    runtime.tick(HTTPSFixture(),self.report)
                    self.assertFalse(runtime.sessions)
                    host=identity.approve('test-admin',self.fp,self.fp)
                    runtime.tick(HTTPSFixture(),self.report)
                    session=runtime.sessions['primary']
                    self.assertEqual(session['sub'],str(host.pk));self.assertEqual(ManagedAdmission.objects.count(),1)
                    now=int(time.time());request_id=str(uuid.uuid4());target=str(uuid.uuid4())
                    command=dict(iss=ORIGIN,aud=self.authority,sub=str(host.pk),iat=now,exp=now+60,jti=request_id,
                        session_id=session['jti'],operation='inspect',runtime_id=target)
                    class Control:
                        def application_runtime(self,rid):
                            owner.assertEqual(rid,target)
                            return SimpleNamespace(state=SimpleNamespace(value='running'),cleanup_pending=False)
                    class Gateway:
                        def inspect(self,rid,runtime_id):
                            return dispatch(Control(),dict(version=1,request_id=rid,operation='inspect',runtime_id=runtime_id),970)['result']
                    token=managed.sign(command,self.signing,managed.COMMAND_TYPE)
                    answer=runtime.inspect_command('primary',token,Gateway())
                    verified=managed.verify(answer,self.key.public_key(),managed.RESULT_TYPE,self.fp,ORIGIN)
                    self.assertEqual(verified['jti'],request_id);self.assertEqual(verified['result']['state'],'running')
                    with self.assertRaises(StateError):runtime.inspect_command('primary',token,Gateway())
            finally:
                if runtime:runtime.close()
                os.close(context.fd)

    def test_supervised_beacon_pending_approval_heartbeat_and_restart(self):
        import hashlib,json,os,tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from zog.host_identify import initialization
        from zog.host_discover.managed import ManagedState
        from zog.host_discover.beacon import Beacon as Runtime
        from zog.host_discover import beacon, supervisor
        from zog.host_discover import admission
        from zog.host_install import state_inspect
        from zog.host_install.state_contract import StateError
        from zog.box_control.host_gateway import dispatch
        from zog.station_access.host_registry import identity
        # Production consumer and journal; real temporary keys/files. Mount and
        # fixed-account evidence are synthetic, not a live-boot acceptance claim.
        bundle=json.loads((Path(__file__).parent/'fixtures/managed-state.json').read_text())
        bundle['bootstrap']['control_authority']['authority_id']=self.authority
        bundle['bootstrap']['registries'][0]['origin']=ORIGIN
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'host-discover';home.mkdir(mode=0o700)
            identity_dir=home/'identity';identity_dir.mkdir(mode=0o700);(home/'control').mkdir(mode=0o700)
            for name in ('trust','registries','health'):(home/name).mkdir(mode=0o700)
            b=bundle['bootstrap'];auth=dict(schema=1,kind='zog-identity-initialization',
                authorization_id=b['initialization']['authorization_id'],installation_id=b['installation_id'],
                state_volume_id=b['state']['state_volume_id'],identity_directory=str(identity_dir),account_profile='zog-host-accounts-v1',expected_fingerprint=None)
            receipt=initialization.prepare(identity_dir,auth)
            self.key=initialization.load_existing(identity_dir,receipt);self.fp=signatures.fingerprint(self.key.public_key())
            auth['identity_directory']=b['state']['identity_directory']
            receipt['authorization_sha256']=hashlib.sha256(initialization.encode(auth)).hexdigest()
            (identity_dir/'initialization.json').write_bytes(initialization.encode(auth))
            (identity_dir/'receipt.json').write_bytes(initialization.encode(receipt))
            context=SimpleNamespace(fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY),bundle=bundle,recheck=lambda:None)
            state=ManagedState();state.context=context
            project=dict(bindings={'boot_id':str(uuid.uuid4())},receipt=receipt,recovery_hold=False)
            metadata=state_inspect.metadata;read=admission.read_at
            service_metadata=lambda fd,u,g,m,*args:metadata(fd,os.geteuid(),os.getegid(),m,*args)
            service_read=lambda fd,n,*args:read(fd,n,os.geteuid(),os.getegid(),0o600)
            owner=self
            class HTTPSFixture:
                def post(self,url,payload,key,subject,ca):
                    message=signatures.sign(url,json.dumps(payload).encode(),key,subject)
                    response=owner.send(message)
                    owner.assertIn(response.status_code,(200,202),response.content)
                    return response.json()
            class LocalSupervisor(supervisor.Client):
                def call(inner, action_name, digest=None, code=None):
                    return supervisor.action(context, dict(schema=1,kind='zog-beacon-supervisor-request',
                        nonce='a'*64,action=action_name,run_id=inner.run_id,bindings=project['bindings'],
                        journal_sha256=digest,code=code))
            runtime=None
            try:
                with patch('zog.host_discover.admission.observe',return_value=project),patch('zog.host_discover.admission.metadata',side_effect=service_metadata),patch('zog.host_install.state_inspect.metadata',side_effect=service_metadata),patch('zog.host_discover.admission.read_at',side_effect=service_read),patch('zog.host_discover.supervisor.wire.observe',return_value=project),patch('zog.host_discover.supervisor.wire.bindings',return_value=project['bindings']),patch('zog.host_discover.beacon.Client',LocalSupervisor):
                    supervisor.prepare(context,b['state']['state_volume_id'])
                    runtime=Runtime(state).open()
                    runtime.tick(HTTPSFixture(),self.report)
                    self.assertFalse(runtime.sessions)
                    host=identity.approve('test-admin',self.fp,self.fp)
                    runtime.tick(HTTPSFixture(),self.report)
                    session=runtime.sessions['primary']
                    self.assertEqual(session['sub'],str(host.pk));self.assertEqual(ManagedAdmission.objects.count(),1)
                    with self.assertRaises(StateError):runtime.inspect_command('primary','unused')
                    first=session['jti'];runtime.finish()
                    runtime=Runtime(state).open();runtime.tick(HTTPSFixture(),self.report)
                    self.assertNotEqual(first,runtime.sessions['primary']['jti'])
                    self.assertEqual(runtime.sessions['primary']['epoch'],2)
                    # Lose a committed response, expire that exact session in the
                    # fixture, fetch signed evidence, reconcile, and reset explicitly.
                    from zog.host_discover import recovery
                    runtime.sessions.clear()
                    class Lost(HTTPSFixture):
                        def post(inner,url,*args):
                            result=super().post(url,*args)
                            if url.endswith('/managed-session/'):raise StateError('managed-http-refused','lost response')
                            return result
                    with self.assertRaises(StateError):runtime.tick(Lost(),self.report)
                    runtime.close();state.fault_code=None
                    row=ManagedAdmission.objects.get(host=host);row.claims['exp']=int(time.time())-1;row.claims['iat']=row.claims['exp']-300;row.save()
                    operation=str(uuid.uuid4())
                    evidence=recovery.evidence(state,operation,HTTPSFixture())
                    with supervisor.ledger(context) as (_,v):before=copy.deepcopy(v)
                    atomic=recovery.atomic
                    with patch('zog.host_discover.recovery.atomic',side_effect=lambda fd,n,v,t,u,g:atomic(fd,n,v,t,os.geteuid(),os.getegid())):
                        recovered=recovery.apply(context,before['revision'],before['run']['id'],operation,evidence,'Verified expired response')
                    row.refresh_from_db();self.assertEqual(row.epoch,3)
                    with supervisor.ledger(context) as (_,v):
                        self.assertEqual(v['fault'],before['fault'])
                        revision=v['revision']
                    with patch('zog.host_discover.supervisor.metadata',side_effect=service_metadata):
                        supervisor.reset(context,revision,before['run']['id'],'Authorize restart after reconciliation')
                    runtime=Runtime(state).open();runtime.tick(HTTPSFixture(),self.report)
                    self.assertEqual(runtime.sessions['primary']['epoch'],4)
                    runtime.finish()
            finally:
                if runtime:runtime.close()
                os.close(context.fd)

    def test_managed_signed_request_replay_and_alteration(self):
        host=self.approved();packet=self.session_request(host)
        self.assertEqual(self.send(packet).status_code,200)
        self.assertEqual(self.send(packet).status_code,401)
        self.assertEqual(self.send(self.session_request(host),body=b'{}').status_code,401)

    def recovery_request(self,host,pending=None,operation=None):
        return self.request(f'/api/hosts/{host.pk}/managed-recovery/',dict(version=1,
            operation_id=operation or str(uuid.uuid4()),journal_sha256='a'*64,pending=pending or self.value),subject=str(host.pk))

    def test_expired_recovery_evidence_is_read_only_and_nonce_protected(self):
        from zog.host_identify import recovery
        host=self.approved();first=self.establish(host);now=first['exp']+1
        before=ManagedAdmission.objects.get(host=host);operation=str(uuid.uuid4())
        with patch('zog.station_access.host_registry.managed_views.time.time',return_value=now):
            packet=self.recovery_request(host,operation=operation)
            response=self.send(packet);self.assertEqual(response.status_code,200,response.content)
            self.assertEqual(self.send(packet).status_code,401)
            again=self.send(self.recovery_request(host,operation=operation));self.assertEqual(again.status_code,200)
        expected=dict(iss=ORIGIN,aud=self.authority,sub=str(host.pk),operation_id=operation,journal_sha256='a'*64,
            request_sha256=recovery.digest(self.value),fingerprint=self.fp,
            **{k:self.value[k] for k in ('installation_id','state_volume_id','registry_id')})
        claims=recovery.verify(response.json()['evidence'],self.signing.public_key(),expected,now)
        self.assertEqual(claims['epoch'],first['epoch']);self.assertEqual(claims['checkpoint'],first['checkpoint'])
        after=ManagedAdmission.objects.get(host=host)
        self.assertEqual(before.request,after.request);self.assertEqual(before.claims,after.claims)
        with self.assertRaises(Exception):managed.session(response.json()['evidence'],self.signing.public_key(),self.expected(host,self.value))

    def test_recovery_rejects_unexpired_unknown_or_conflicting_history(self):
        host=self.approved();first=self.establish(host)
        self.assertEqual(self.send(self.recovery_request(host)).status_code,409)
        with patch('zog.station_access.host_registry.managed_views.time.time',return_value=first['exp']+1):
            wrong=dict(self.value,challenge=str(uuid.uuid4()))
            self.assertEqual(self.send(self.recovery_request(host,wrong)).status_code,409)
            ManagedAdmission.objects.all().delete()
            self.assertEqual(self.send(self.recovery_request(host)).status_code,409)

    def test_recovery_rechecks_revocation_and_refuses_unsigned(self):
        host=self.approved();first=self.establish(host)
        self.assertEqual(self.client.post(f'/api/hosts/{host.pk}/managed-recovery/',{},content_type='application/json').status_code,401)
        proof=__import__('zog.station_access.host_registry.identity',fromlist=['proof']).proof
        def revoke(*args):
            result=proof(*args);HostIdentity.objects.filter(pk=self.fp).update(status='revoked');return result
        with patch('zog.station_access.host_registry.identity.proof',side_effect=revoke),patch('zog.station_access.host_registry.managed_views.time.time',return_value=first['exp']+1):
            self.assertEqual(self.send(self.recovery_request(host)).status_code,401)
