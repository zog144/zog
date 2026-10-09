import json
import pytest
from zog.image_build.box_control_adapter import BoxControlExecutionAdapter, BuildRegistrationPending
from zog.box_control.errors import RecoveryRequired, RootControlReplyTimeout


def adapter(control):
    return BoxControlExecutionAdapter(control,execution_user_id=1000,execution_group_id=1000,
        startup_timeout_seconds=30,termination_grace_seconds=5,wait_timeout_seconds=0,
        resource_limits={},input_manifest_id='fixture')


def test_exact_registration_replayed_only_after_ready(tmp_path, monkeypatch):
    calls=[]; observations=iter(['importing','ready'])
    class Control:
        def register_build_root(self,**kw):
            calls.append(kw)
            if len(calls)==1:
                try: raise RootControlReplyTimeout('build_register',60)
                except RootControlReplyTimeout as exc: raise RecoveryRequired('unresolved') from exc
            return {'state':'ready'}
        def inspect_build_root(self,rid):return {'state':next(observations),'phase':'copy-root'}
    delays=[];monkeypatch.setattr('zog.image_build.box_control_adapter.time.sleep',delays.append)
    intent={'input_manifest_id':'fixed'}
    assert adapter(Control())._register('a'*32,intent,tmp_path)=={'state':'ready'}
    assert len(calls)==2 and calls[0]==calls[1] and delays==[1,2]
    assert json.loads((tmp_path/'registration-progress.json').read_text())['state']=='ready'


@pytest.mark.parametrize('mode',['ordinary','wrong-operation','never-ready','inspection-fault'])
def test_unresolved_or_unrelated_failure_never_replays(tmp_path,monkeypatch,mode):
    calls=[]; polls=[]
    class Control:
        def register_build_root(self,**kw):
            calls.append(kw)
            if mode=='ordinary':raise RecoveryRequired('storage fault')
            try:raise RootControlReplyTimeout('build_start' if mode=='wrong-operation' else 'build_register',60)
            except RootControlReplyTimeout as exc:raise RecoveryRequired('unresolved') from exc
        def inspect_build_root(self,rid):
            polls.append(rid)
            if mode=='inspection-fault':raise RecoveryRequired('intent mismatch')
            return {'state':'importing'}
    monkeypatch.setattr('zog.image_build.box_control_adapter.time.sleep',lambda n:None)
    with pytest.raises(BuildRegistrationPending if mode=='never-ready' else RecoveryRequired):adapter(Control())._register('a'*32,{},tmp_path)
    assert len(calls)==1
    assert len(polls)==({'ordinary':0,'wrong-operation':0,'never-ready':8,'inspection-fault':1}[mode])


@pytest.mark.parametrize('waiting_state', ['importing', 'absent'])
def test_supervisor_revisits_durable_registration_without_resubmitting(tmp_path, monkeypatch, waiting_state):
    from zog.image_build.glibc_final import wait_for
    calls=[]; polls=[]; delays=[]
    class Control:
        def register_build_root(self, **kw):
            calls.append(kw)
            if len(calls)==1:
                try: raise RootControlReplyTimeout('build_register',60)
                except RootControlReplyTimeout as exc: raise RecoveryRequired('unresolved') from exc
            return {'state':'ready'}
        def inspect_build_root(self, rid):
            polls.append(rid)
            return {'state':waiting_state if len(polls)<11 else 'ready', 'phase':'sync-source'}
    control=Control(); intent={'input_manifest_id':'frozen'}; rid='a'*32
    monkeypatch.setattr('zog.image_build.box_control_adapter.time.sleep',lambda n:None)
    with pytest.raises(BuildRegistrationPending):adapter(control)._register(rid,intent,tmp_path)
    assert len(calls)==1 and len(polls)==8
    # New adapter models reconstruction after supervisor/client interruption.
    def sleep(n):
        progress=json.loads((tmp_path/'progress.json').read_text())
        assert progress['resource_id']==rid and progress['pending']=='registration'
        assert 'job_id' not in progress
        delays.append(n)
    monkeypatch.setattr('zog.image_build.glibc_final.time.sleep',sleep)
    assert wait_for(tmp_path,'native-packages',lambda:adapter(control)._register(rid,intent,tmp_path))=={'state':'ready'}
    assert calls==[dict(resource_id=rid,**intent)]*2
    assert delays==[15,15]
    assert not (tmp_path/'registration-pending.json').exists()


@pytest.mark.parametrize('mode', ['changed-intent','changed-resource','inspection-fault','released'])
def test_pending_registration_fails_closed(tmp_path, mode):
    from zog.image_build.errors import ImageBuildError
    rid='a'*32; intent={'input_manifest_id':'frozen'}
    (tmp_path/'registration-pending.json').write_text(json.dumps({'resource_id':rid,'registration':intent}))
    class Control:
        def register_build_root(self,**kw):pytest.fail('must not replay mutation')
        def inspect_build_root(self,resource_id):
            if mode=='inspection-fault':raise RecoveryRequired('controller fault')
            return {'state':'released'}
    if mode=='changed-intent':intent={'input_manifest_id':'changed'}
    if mode=='changed-resource':rid='b'*32
    with pytest.raises((ImageBuildError,RecoveryRequired)):
        adapter(Control())._register(rid,intent,tmp_path)
