import copy
import json
import os
import time
import uuid
import pytest
from zog.host_install.state_contract import StateError,canonical
from zog.host_identify import signatures,managed,recovery as proof
from zog.host_discover import recovery,beacon,supervisor
from test_supervised_beacon import environment,current,retry
from test_managed_admission import Station


@pytest.fixture
def expired(environment,monkeypatch):
    state,observation,root=environment
    # Synthetic account evidence, same convention as the existing joint fixtures.
    original=recovery.atomic
    monkeypatch.setattr(recovery,'atomic',lambda fd,n,v,t,u,g:original(fd,n,v,t,0,0))
    station=Station();station.approved=True;runtime=beacon.Beacon(state).open()
    runtime.tick(station,{'version':1});runtime.sessions.clear()
    call=station.post
    def lose(url,payload,*a):
        response=call(url,payload,*a)
        if url.endswith('/managed-session/'):raise StateError('managed-http-refused','expired response')
        return response
    station.post=lose
    with pytest.raises(StateError):runtime.tick(station,{'version':1})
    saved=copy.deepcopy(runtime.saved);runtime.close();state.fault=None
    value=current(state);operation=str(uuid.uuid4());now=int(time.time())
    claims=dict(iss=saved['registries']['primary']['origin'],aud=state.bundle['bootstrap']['control_authority']['authority_id'],
        sub=station.host,operation_id=operation,journal_sha256=beacon.digest(saved),request_sha256=proof.digest(saved['registries']['primary']['pending']),
        **{k:saved[k] for k in ('fingerprint','installation_id','state_volume_id')},registry_id='primary',
        iat=now,exp=now+300,jti=operation,epoch=station.previous['epoch'],checkpoint=station.previous['checkpoint'],session_expired_at=now-1)
    response=dict(version=1,public_key=signatures.public_text(station.key.public_key()),evidence=managed.sign(claims,station.key,proof.TYPE))
    args=(state.producer,value['revision'],value['run']['id'],operation,response,'Inspected expired pending session')
    return state,observation,root,station,value,saved,claims,args


def test_reconcile_retains_fault_then_explicit_reset_and_fresh_session(expired):
    state,_,root,station,old,saved,claims,args=expired
    result=recovery.apply(*args)
    value=current(state)
    assert result['reset_required'] and value['fault']==old['fault'] and value['run']==old['run']
    new=json.loads((root/'host-discover/control/managed.json').read_text())
    assert new['registries']['primary']['pending'] is None
    assert new['registries']['primary']['previous']==station.previous
    assert value['journal_sha256']==beacon.digest(new)
    assert recovery.inspect_recovery(state.producer)['status']=='recovery-complete'
    assert recovery.resume(state.producer,args[3])==result
    with pytest.raises(StateError):recovery.apply(*args)
    retry(state);station.post=Station.post.__get__(station)
    runtime=beacon.Beacon(state).open();runtime.tick(station,{'version':1})
    assert runtime.sessions['primary']['epoch']==3
    runtime.finish()


@pytest.mark.parametrize('change',['operation','digest','epoch','checkpoint_signature','key','expired','future','request','identity'])
def test_invalid_evidence_never_changes_checkpoint(expired,change):
    state,_,root,station,value,saved,c,args=expired;c=copy.deepcopy(c);args=list(args);response=copy.deepcopy(args[4])
    if change=='operation':c['operation_id']=str(uuid.uuid4())
    if change=='digest':c['journal_sha256']='f'*64
    if change=='epoch':c['epoch']+=1
    if change=='expired':c['iat']-=400;c['exp']-=400
    if change=='future':c['iat']+=400;c['exp']+=400
    if change=='request':c['request_sha256']='f'*64
    if change=='identity':c['installation_id']=str(uuid.uuid4())
    response['evidence']=managed.sign(c,station.key,proof.TYPE)
    if change=='checkpoint_signature':response['evidence']=response['evidence'][:-10]+'aaaaaaaaaa'
    if change=='key':response['public_key']=signatures.public_text(state.key.public_key())
    args[4]=response
    with pytest.raises((StateError,ValueError)):recovery.apply(*args)
    assert current(state)==value
    assert json.loads((root/'host-discover/control/managed.json').read_text())==saved
    assert not (root/supervisor.NAME/'recovery.json').exists()


def test_hold_and_stale_authorization_block(expired):
    state,observation,_,_,value,_,_,args=expired
    observation['recovery_hold']=True
    with pytest.raises(StateError):recovery.apply(*args)
    observation['recovery_hold']=False
    wrong=list(args);wrong[1]+=1
    with pytest.raises(StateError):recovery.apply(*wrong)
    assert current(state)==value


@pytest.mark.parametrize('boundary',range(1,14))
def test_recovery_fsync_interruption_is_resumable(expired,monkeypatch,boundary):
    state,_,root,_,old,_,_,args=expired
    original=os.fsync;count=0
    def fail(fd):
        nonlocal count
        count+=1
        if count==boundary:raise OSError('injected fsync failure')
        return original(fd)
    monkeypatch.setattr(os,'fsync',fail)
    try:recovery.apply(*args)
    except OSError:pass
    monkeypatch.setattr(os,'fsync',original)
    assert count>=boundary
    folder=root/supervisor.NAME
    if (folder/'recovery.json').exists():
        with pytest.raises(StateError):current(state)
        result=recovery.resume(state.producer,args[3])
    elif (folder/'last-recovery.json').exists():result=recovery.resume(state.producer,args[3])
    else:result=recovery.apply(*args)
    assert result['status']=='session-reconciled'
    assert current(state)['fault']==old['fault']
    assert set(p.name for p in folder.iterdir())=={'lock','ledger.json','last-recovery.json'}


def test_partial_marker_is_replaced_only_after_fresh_validation(expired):
    state,_,root,_,old,_,_,args=expired
    p=root/supervisor.NAME/'recovery.stage';p.write_bytes(b'{');p.chmod(0o600)
    with pytest.raises(StateError):current(state)
    wrong=list(args);wrong[1]+=1
    with pytest.raises(StateError):recovery.apply(*wrong)
    assert p.read_bytes()==b'{'
    recovery.apply(*args);assert not p.exists()


def test_resume_after_evidence_expiry_uses_durable_authorization(expired,monkeypatch):
    state,_,root,_,_,_,_,args=expired
    real=recovery.finish
    monkeypatch.setattr(recovery,'finish',lambda *a:(_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):recovery.apply(*args)
    monkeypatch.setattr(recovery,'finish',real)
    monkeypatch.setattr(recovery.time,'time',lambda:9999999999)
    assert recovery.resume(state.producer,args[3])['status']=='session-reconciled'


def test_concurrent_journal_change_cannot_be_adopted(expired,monkeypatch):
    state,_,root,_,_,_,_,args=expired
    real=recovery.finish;monkeypatch.setattr(recovery,'finish',lambda *a:(_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):recovery.apply(*args)
    monkeypatch.setattr(recovery,'finish',real)
    p=root/'host-discover/control/managed.json';v=json.loads(p.read_text());v['registries']['primary']['pending']['challenge']=str(uuid.uuid4());p.write_bytes(canonical(v))
    with pytest.raises(StateError):recovery.resume(state.producer,args[3])
    assert (root/supervisor.NAME/'recovery.json').exists()


def test_first_session_requires_independent_key_confirmation(expired):
    state,_,_,station,_,saved,c,args=expired
    saved['registries']['primary'].update(public_key=None,previous=None)
    saved['registries']['primary']['pending']['previous']=None
    c.update(epoch=1,journal_sha256=beacon.digest(saved),request_sha256=proof.digest(saved['registries']['primary']['pending']))
    response=dict(args[4],evidence=managed.sign(c,station.key,proof.TYPE))
    with pytest.raises(StateError):recovery.replacement(state.producer,saved,response,args[3])
    result=recovery.replacement(state.producer,saved,response,args[3],signatures.fingerprint(station.key.public_key()))
    assert result['registries']['primary']['previous']['epoch']==1


@pytest.mark.parametrize('write_number',[1,2,3])
def test_partial_write_at_each_file_recovers_from_record(expired,monkeypatch,write_number):
    state,_,root,_,_,_,_,args=expired
    original=os.write;count=0
    def partial(fd,data):
        nonlocal count
        count+=1
        if count==write_number:
            original(fd,data[:7]);raise OSError('partial write')
        return original(fd,data)
    monkeypatch.setattr(os,'write',partial)
    with pytest.raises(OSError):recovery.apply(*args)
    monkeypatch.setattr(os,'write',original)
    if (root/supervisor.NAME/'recovery.json').exists():result=recovery.resume(state.producer,args[3])
    else:result=recovery.apply(*args)
    assert result['status']=='session-reconciled'


def test_recovery_blocks_reset_wrong_resume_and_running_consumer(expired,monkeypatch):
    state,_,_,_,old,_,_,args=expired
    from zog.host_discover.admission import Journal
    j=Journal(state.producer);j.acquire()
    try:
        with pytest.raises(StateError,match='managed-busy'):recovery.apply(*args)
    finally:j.close()
    real=recovery.finish;monkeypatch.setattr(recovery,'finish',lambda *a:(_ for _ in ()).throw(OSError('crash')))
    with pytest.raises(OSError):recovery.apply(*args)
    monkeypatch.setattr(recovery,'finish',real)
    with pytest.raises(StateError):supervisor.reset(state.producer,old['revision'],old['run']['id'],'must not reset incomplete recovery')
    with pytest.raises(StateError):recovery.resume(state.producer,str(uuid.uuid4()))
    recovery.resume(state.producer,args[3])


def test_nonroot_cannot_authorize_recovery(expired,monkeypatch):
    *_,args=expired
    monkeypatch.setattr(recovery.os,'geteuid',lambda:970)
    with pytest.raises(StateError,match='root-required'):recovery.apply(*args)


def test_recovery_temporary_created_before_chown_is_safe_to_replace(tmp_path):
    fd=os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY)
    try:
        p=tmp_path/'managed.recovery';p.write_bytes(b'partial');p.chmod(0o600)
        recovery.atomic(fd,'managed.json',{'test':'durable'},'managed.recovery',970,970)
        s=(tmp_path/'managed.json').stat()
        assert (s.st_uid,s.st_gid)==(970,970)
    finally:os.close(fd)
