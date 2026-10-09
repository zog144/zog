import copy
import json
import os
from pathlib import Path
import pytest
from zog.host_discover import managed, daemon
from zog.host_install.state_contract import StateError

B=json.loads((Path(__file__).parent/'fixtures/host-install/bundle.json').read_text())


class Inspection:
    def __init__(self):
        self.bundle=copy.deepcopy(B)
        self.closed=False
        self.fault=None
    def recheck(self):
        if self.fault: raise StateError(self.fault,'test')
    def close(self): self.closed=True


@pytest.fixture
def inspected(monkeypatch):
    context=Inspection(); events=[]
    monkeypatch.setattr(managed.os,'geteuid',lambda:970)
    monkeypatch.setattr(managed.os,'getegid',lambda:970)
    monkeypatch.setattr(managed.os,'getgroups',lambda:[972,973])
    def inspect(): events.append('inspect');return context
    def probe(): events.append('probe');return {'status':'probe-passed'}
    monkeypatch.setattr(managed.state_inspect,'inspect_live',inspect)
    monkeypatch.setattr(managed.state_probe,'probe_live',probe)
    return context, events


def test_production_boundary_no_private_read(inspected,monkeypatch):
    monkeypatch.setattr(managed.initialization,'load_existing_fd',lambda *a:pytest.fail('private read'))
    result=managed.report()
    assert result['code']=='admission-unavailable'
    assert not result['live_admission'] and not result['remote_control_enabled']
    assert inspected[1]==['inspect','probe'] and inspected[0].closed


@pytest.mark.parametrize('code',['mount-changed','storage-probe-failed','state-read-only'])
def test_faults_latch_and_no_read_or_reentry(inspected,monkeypatch,code):
    context,_=inspected
    monkeypatch.setattr(managed.initialization,'load_existing_fd',lambda *a:pytest.fail('private read'))
    state=managed.ManagedState()
    with state:
        context.fault=code
        with pytest.raises(StateError,match=code):state.check()
        context.fault=None
        with pytest.raises(StateError,match=code):state.decision()
    with pytest.raises(StateError,match=code):state.__enter__()
    assert context.closed


def test_probe_failure_closes_before_evidence(inspected,monkeypatch):
    def fail():raise OSError('fsync failed')
    monkeypatch.setattr(managed.state_probe,'probe_live',fail)
    assert managed.report()['code']=='state-io-failure'
    assert inspected[0].closed


def test_unknown_schema_before_probe(inspected,monkeypatch):
    inspected[0].bundle['bootstrap']['schema']=9
    monkeypatch.setattr(managed.state_probe,'probe_live',lambda:pytest.fail('write before schema validation'))
    assert managed.report()['code']=='unsupported-schema'
    assert inspected[0].closed


class Coordinator:
    def recovery_hold(self,c):return False
    def schemas(self,c):return dict(identity=1,trust=1,control=1,controller=1)
    def consumption(self,c):return None


def test_missing_consumption_never_loads_private_key(inspected,monkeypatch):
    monkeypatch.setattr(managed.initialization,'load_existing_fd',lambda *a:pytest.fail('private read'))
    with managed.ManagedState() as state:
        with pytest.raises(StateError,match='consumption-unavailable'):state.decision(Coordinator())


@pytest.mark.parametrize('fault',['hold','schemas'])
def test_unavailable_protected_evidence_blocks(inspected,monkeypatch,fault):
    coordinator=Coordinator()
    if fault=='hold':coordinator.recovery_hold=lambda c:None
    else:coordinator.schemas=lambda c:dict(identity=2,trust=1,control=1,controller=1)
    coordinator.consumption=lambda c:pytest.fail('must not read identity')
    with managed.ManagedState() as state:
        with pytest.raises(StateError):state.decision(coordinator)


def test_even_completed_fixture_does_not_establish_station_session(inspected,monkeypatch):
    coordinator=Coordinator()
    monkeypatch.setattr(managed.ManagedState,'_identity',lambda *a:dict(status='complete',initialization_id=B['bootstrap']['initialization']['authorization_id'],candidates=1,matches_expected=True))
    with managed.ManagedState() as state:
        result=state.decision(coordinator)
    assert result['identity_action']=='load-existing'
    assert result['code']=='fresh-session-required'
    assert not result['control_allowed'] and not result['live_admission']


def test_managed_daemon_never_falls_through(inspected,monkeypatch):
    import sys
    from zog.host_discover import roles
    monkeypatch.setattr(sys,'argv',['host-discover','--managed-state','--once'])
    monkeypatch.setattr(daemon,'announce',lambda *a:pytest.fail('network'))
    monkeypatch.setattr(roles.Controller,'tick',lambda *a:pytest.fail('role dispatch'))
    with pytest.raises(SystemExit) as exc:daemon.main()
    assert exc.value.code==2


def test_retained_state_to_consumed_identity(tmp_path,monkeypatch):
    """Real key/receipt/files; synthetic mount and translated service ownership."""
    from zog.host_identify import initialization as init
    import hashlib
    home=tmp_path/'host-discover';home.mkdir(mode=0o700)
    root=home/'identity';root.mkdir(mode=0o700)
    b=copy.deepcopy(B);boot=b['bootstrap']
    auth=dict(schema=1,kind='zog-identity-initialization',
        authorization_id=boot['initialization']['authorization_id'],installation_id=boot['installation_id'],
        state_volume_id=boot['state']['state_volume_id'],identity_directory=str(root),
        account_profile='zog-host-accounts-v1',expected_fingerprint=None)
    receipt=init.prepare(root,auth)
    auth['identity_directory']=boot['state']['identity_directory']
    receipt['authorization_sha256']=hashlib.sha256(init.encode(auth)).hexdigest()
    (root/'initialization.json').write_bytes(init.encode(auth))
    (root/'receipt.json').write_bytes(init.encode(receipt))
    context=Inspection();context.fd=os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY)
    state=managed.ManagedState();state.context=context
    coordinator=Coordinator();coordinator.consumption=lambda _:receipt
    original=managed.state_inspect.metadata
    monkeypatch.setattr(managed.state_inspect,'metadata',lambda fd,u,g,m:original(fd,os.geteuid(),os.getegid(),m))
    try:
        result=state.decision(coordinator)
        assert result['identity_action']=='load-existing' and not result['live_admission']
        (root/'identity.pem').write_bytes(b'corrupt')
        with pytest.raises(StateError,match='identity-state-invalid'):state.decision(coordinator)
        assert state.fault_code=='identity-state-invalid'
    finally:os.close(context.fd)


def test_offline_report_cannot_be_coordinator(inspected):
    with managed.ManagedState() as state:
        with pytest.raises(StateError):state.decision({'recovery_hold':False})
    assert state.fault_code=='identity-state-invalid'
