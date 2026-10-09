"""Real durable files, synthetic verified mount/account evidence; no live acceptance."""
import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_install.state_contract import StateError, canonical
from zog.host_install import state_inspect
from zog.host_identify import signatures
from zog.host_discover import supervisor, beacon, admission, beacon_state
from test_managed_admission import State, Station, B


@pytest.fixture
def environment(tmp_path, monkeypatch):
    home = tmp_path/'host-discover'; home.mkdir(mode=0o700); (home/'control').mkdir(mode=0o700)
    for name in ('trust','registries','health'):(home/name).mkdir(mode=0o700)
    key = Ed25519PrivateKey.generate(); state = State(tmp_path, key)
    observation = dict(recovery_hold=False, receipt={'fingerprint':signatures.fingerprint(key.public_key())}, bindings={'boot_id':str(uuid.uuid4())})
    monkeypatch.setattr(supervisor.wire, 'observe', lambda _: copy.deepcopy(observation))
    monkeypatch.setattr(supervisor.wire, 'bindings', lambda _: copy.deepcopy(observation['bindings']))
    monkeypatch.setattr(admission, 'observe', lambda _: copy.deepcopy(observation))
    metadata = state_inspect.metadata; read = admission.read_at
    adapted = lambda fd,u,g,m,*a:metadata(fd,os.geteuid(),os.getegid(),m,*a)
    monkeypatch.setattr(supervisor, 'metadata', adapted)
    monkeypatch.setattr(state_inspect, 'metadata', adapted)
    monkeypatch.setattr(admission, 'metadata', adapted)
    monkeypatch.setattr(admission, 'read_at', lambda fd,n,*a:read(fd,n,os.geteuid(),os.getegid(),0o600))
    state.producer=SimpleNamespace(fd=state.fd,bundle=state.bundle,recheck=lambda:None)
    supervisor.prepare(state.producer, B['bootstrap']['state']['state_volume_id'])
    class Local(supervisor.Client):
        def call(self, action_name, digest=None, code=None):
            return supervisor.action(self.context.producer, dict(schema=1,kind='zog-beacon-supervisor-request',nonce='a'*64,
                action=action_name,run_id=self.run_id,bindings=observation['bindings'],journal_sha256=digest,code=code))
    monkeypatch.setattr(beacon, 'Client', Local)
    yield state, observation, tmp_path
    os.close(state.fd)


def current(state):
    with supervisor.ledger(state.producer) as (_, value): return copy.deepcopy(value)


def retry(state):
    value=current(state)
    supervisor.reset(state.producer,value['revision'],value['run']['id'],'Operator checked existing state; authorize retry')
    state.fault=None


def test_complete_beacon_pending_approval_restart(environment):
    state,_,_=environment; station=Station(); runtime=beacon.Beacon(state).open()
    runtime.tick(station,{'version':1}); assert not runtime.sessions
    station.approved=True;runtime.tick(station,{'version':1})
    assert runtime.sessions['primary']['epoch']==1
    assert current(state)['journal_sha256']==beacon.digest(runtime.saved)
    with pytest.raises(StateError,match='managed-control-disabled'):runtime.inspect_command('primary','unused')
    runtime.finish(); assert current(state)['run'] is None
    runtime=beacon.Beacon(state).open();runtime.tick(station,{'version':1})
    assert runtime.sessions['primary']['epoch']==2
    runtime.finish()


def test_crash_requires_explicit_cas_reset(environment):
    state,_,_=environment; runtime=beacon.Beacon(state).open();runtime.close()
    value=current(state)
    with pytest.raises(StateError,match='reset-conflict'):supervisor.reset(state.producer,value['revision']+1,value['run']['id'],'wrong')
    with pytest.raises(StateError):beacon.Beacon(state).open()
    assert current(state)['run']==value['run']
    retry(state); runtime=beacon.Beacon(state).open();runtime.finish()


def test_reset_refuses_running_consumer(environment):
    state,_,_=environment; runtime=beacon.Beacon(state).open();value=current(state)
    try:
        with pytest.raises(StateError,match='managed-busy'):supervisor.reset(state.producer,value['revision'],value['run']['id'],'still running')
    finally:runtime.finish()


def test_changed_journal_cannot_replace_protected_binding(environment):
    state,_,root=environment;runtime=beacon.Beacon(state).open();runtime.finish()
    path=root/'host-discover/control/managed.json'; value=json.loads(path.read_text());value['fingerprint']='b'*64;path.write_bytes(canonical(value))
    with pytest.raises(StateError):beacon.Beacon(state).open()
    assert current(state)['run'] is not None


def test_missing_journal_never_reinitialized(environment):
    state,_,root=environment;runtime=beacon.Beacon(state).open();runtime.finish()
    (root/'host-discover/control/managed.json').unlink()
    with pytest.raises(StateError):beacon.Beacon(state).open()
    assert not (root/'host-discover/control/managed.json').exists()


def test_unknown_actual_schema_refuses(environment):
    state,_,root=environment;runtime=beacon.Beacon(state).open();runtime.finish()
    p=root/'host-discover/control/managed.json';v=json.loads(p.read_text());v['schema']=2;p.write_bytes(canonical(v))
    with pytest.raises(StateError):beacon.Beacon(state).open()


def test_expected_uuid_checks_protected_saved_binding(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    runtime.tick(station,{'version':1});runtime.finish()
    state.bundle['bootstrap']['initialization']['expected_host_uuid']=str(uuid.uuid4())
    with pytest.raises(StateError,match='registry-binding-conflict'):beacon.Beacon(state).open()


def test_fault_is_retained_and_ordinary_restart_cannot_clear(environment):
    state,observation,_=environment;runtime=beacon.Beacon(state).open()
    observation['recovery_hold']=True
    with pytest.raises(StateError):runtime.tick(Station(),{'version':1})
    assert current(state)['fault'] is not None and runtime.key is None
    runtime.close(); observation['recovery_hold']=False; state.fault=None
    with pytest.raises(StateError):beacon.Beacon(state).open()


def test_unrecordable_fault_keeps_active_run(environment,monkeypatch):
    state,_,_=environment;runtime=beacon.Beacon(state).open()
    monkeypatch.setattr(runtime.supervisor,'fault',lambda: (_ for _ in ()).throw(OSError('unwritable')))
    with pytest.raises(StateError):runtime.fail(OSError('disk fault'))
    runtime.close(); assert current(state)['run'] is not None


def test_network_failure_requires_retry_without_resetting_checkpoint(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    runtime.tick(station,{'version':1});previous=copy.deepcopy(runtime.saved['registries']['primary']['previous'])
    class Broken:
        def post(self,*a):raise OSError('connection lost')
    with pytest.raises(StateError):runtime.tick(Broken(),{'version':1})
    runtime.close();retry(state)
    runtime=beacon.Beacon(state).open();assert runtime.saved['registries']['primary']['previous']==previous
    runtime.tick(station,{'version':1});assert runtime.sessions['primary']['epoch']==2;runtime.finish()


def test_interrupted_supervisor_write_cannot_be_reset_away(environment,monkeypatch):
    state,_,root=environment
    original=os.fsync
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('disk failure')))
    with pytest.raises(StateError):beacon.Beacon(state).open()
    monkeypatch.setattr(os,'fsync',original)
    assert (root/supervisor.NAME/'pending.json').exists()
    with pytest.raises(StateError,match='supervisor-incomplete'):current(state)


def test_repeat_prepare_never_resets_active_ledger(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();runtime.close()
    with pytest.raises(StateError):supervisor.prepare(state,B['bootstrap']['state']['state_volume_id'])
    assert current(state)['run'] is not None


def test_trust_schema_checks_nested_fields(environment):
    state,_,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True;runtime.tick(station,{'version':1})
    value=copy.deepcopy(runtime.saved);value['registries']['primary']['previous']['epoch']=True
    with pytest.raises(StateError):beacon_state.validate(value)
    runtime.finish()


def test_running_journal_change_blocks_before_network(environment):
    state,_,root=environment;runtime=beacon.Beacon(state).open()
    path=root/'host-discover/control/managed.json';v=json.loads(path.read_text());v['fingerprint']='c'*64;path.write_bytes(canonical(v))
    class NoNetwork:
        def post(self,*a):pytest.fail('No request may leave host')
    with pytest.raises(StateError):runtime.tick(NoNetwork(),{'version':1})
    runtime.close()


def test_control_directory_replacement_blocks(environment):
    state,_,root=environment;runtime=beacon.Beacon(state).open()
    path=root/'host-discover/control';path.rename(root/'host-discover/old-control');path.mkdir(mode=0o700)
    with pytest.raises(StateError,match='managed-directory-changed'):runtime.tick(Station(),{'version':1})
    runtime.close()


@pytest.mark.parametrize('field,value',[('nonce','b'*64),('ok',1),('run_id',str(uuid.uuid4())),('transport_enabled',True),('revision',True),('journal_sha256','bad')])
def test_supervisor_response_validation(environment,field,value):
    state,_,_=environment;run_id=str(uuid.uuid4());nonce='a'*64
    result=dict(binding=current(state)['binding'],revision=0,journal_sha256=None,run_id=run_id,transport_enabled=False,control_authorized=False)
    response=dict(schema=1,kind='zog-beacon-supervisor-response',nonce=nonce,ok=True,result=result)
    if field in ('nonce','ok'):response[field]=value
    else:result[field]=value
    with pytest.raises(StateError):supervisor.validate_response(response,nonce,run_id)


def test_real_socket_roundtrip_and_wrong_peer(environment,monkeypatch):
    import socket, threading
    from contextlib import contextmanager
    state,observation,_=environment
    @contextmanager
    def inspected():yield state.producer
    monkeypatch.setattr(supervisor,'inspect_live',inspected)
    left,right=socket.socketpair()
    assert supervisor.wire.peer_uid(left)==os.geteuid()
    monkeypatch.setattr(supervisor.wire,'peer_uid',lambda _:971)
    with pytest.raises(StateError,match='supervisor-peer'):supervisor.serve_connection(left)
    monkeypatch.setattr(supervisor.wire,'peer_uid',lambda _:970)
    errors=[]
    def server():
        try:
            with left:supervisor.serve_connection(left)
        except BaseException as exc:errors.append(exc)
    t=threading.Thread(target=server);t.start();run_id=str(uuid.uuid4())
    with right:
        right.settimeout(5)
        right.sendall(canonical(dict(schema=1,kind='zog-beacon-supervisor-request',nonce='a'*64,action='begin',run_id=run_id,bindings=observation['bindings'],journal_sha256=None,code=None)))
        right.shutdown(socket.SHUT_WR);response=supervisor.wire.receive(right,8192)
    t.join(5);assert not t.is_alive() and not errors
    assert supervisor.validate_response(response,'a'*64,run_id)['journal_sha256'] is None


def test_lost_session_reply_preserved_across_reboot_and_authorized_retry(environment):
    state,observation,_=environment;runtime=beacon.Beacon(state).open();station=Station();station.approved=True
    original=station.post;lost={}
    def broken(url,payload,key,subject,ca):
        result=original(url,payload,key,subject,ca)
        if url.endswith('/managed-session/'):
            lost.update(payload=copy.deepcopy(payload),result=result)
            raise ConnectionError('lost reply')
        return result
    station.post=broken
    with pytest.raises(StateError):runtime.tick(station,{'version':1})
    runtime.close();observation['bindings']['boot_id']=str(uuid.uuid4());retry(state)
    def reconcile(url,payload,key,subject,ca):
        if url.endswith('/managed-session/') and payload==lost['payload']:return lost['result']
        return original(url,payload,key,subject,ca)
    station.post=reconcile;runtime=beacon.Beacon(state).open();runtime.tick(station,{'version':1})
    assert runtime.sessions['primary']['epoch']==2
    assert runtime.sessions['primary']['boot_id']==observation['bindings']['boot_id']
    runtime.finish()


def test_correct_expected_uuid_from_protected_journal(environment):
    state,_,_=environment;station=Station();station.approved=True;runtime=beacon.Beacon(state).open()
    runtime.tick(station,{'version':1});runtime.finish()
    state.bundle['bootstrap']['initialization']['expected_host_uuid']=station.host
    runtime=beacon.Beacon(state).open();runtime.tick(station,{'version':1});runtime.finish()


def test_foreign_trust_state_is_not_ignored(environment):
    state,_,root=environment
    (root/'host-discover/trust/newer-schema.json').write_text('{}')
    with pytest.raises(StateError,match='managed-component-state'):beacon.Beacon(state).open()


def test_actual_client_wire_roundtrip(environment,monkeypatch,tmp_path):
    import socket,threading,stat
    from contextlib import contextmanager
    state,observation,_=environment
    @contextmanager
    def inspected():yield state.producer
    left,right=socket.socketpair();parent=tmp_path/'runtime';parent.mkdir(mode=0o755)
    parentfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
    class Connected:
        def __enter__(self):return self
        def __exit__(self,*a):right.close()
        def __getattr__(self,n):return getattr(right,n)
        def connect(self,path):assert path.startswith('/proc/self/fd/')
    original_peer=supervisor.wire.peer_uid
    def peer(c):
        actual=right if isinstance(c,Connected) else c
        assert original_peer(actual)==0
        return 0 if threading.current_thread() is threading.main_thread() else 970
    monkeypatch.setattr(supervisor,'inspect_live',inspected)
    monkeypatch.setattr(supervisor,'directory',lambda _:os.dup(parentfd))
    monkeypatch.setattr(supervisor.os,'stat',lambda *a,**k:SimpleNamespace(st_mode=stat.S_IFSOCK|0o660,st_uid=0,st_gid=970))
    monkeypatch.setattr(supervisor.os,'geteuid',lambda:970 if threading.current_thread() is threading.main_thread() else 0)
    monkeypatch.setattr(supervisor.os,'getegid',lambda:970 if threading.current_thread() is threading.main_thread() else 0)
    # Metadata assertions on root-owned fixture directories use actual fixed IDs.
    monkeypatch.setattr(supervisor,'metadata',lambda fd,u,g,m,*a:None)
    monkeypatch.setattr(supervisor.wire,'peer_uid',peer)
    monkeypatch.setattr(supervisor.socket,'socket',lambda *a,**k:Connected())
    errors=[]
    def server():
        try:
            with left:supervisor.serve_connection(left)
        except BaseException as exc:errors.append(exc)
    t=threading.Thread(target=server);t.start()
    try:
        result=supervisor.Client(state).begin()
        assert result['journal_sha256'] is None
        t.join(5);assert not t.is_alive() and not errors
    finally:os.close(parentfd);right.close();left.close()
