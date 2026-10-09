import copy
from types import SimpleNamespace
import pytest
from zog.host_install.state_contract import StateError
from zog.host_discover import admission,managed


class State:
    context=object()
    def __init__(self):self.events=[];self.fault=None
    def check(self):
        if self.fault:raise StateError(self.fault,'latched')
        self.events.append('check')
    def _identity(self,receipt):self.events.append('identity');self.receipt=receipt
    def fail(self,code):self.fault=self.fault or code;raise StateError(self.fault,'test')


def observation():
    return dict(recovery_hold=False,identity_action='verify-existing',receipt={'fingerprint':'a'*64},bindings={'boot_id':'test'},transport_enabled=False,control_authorized=False)


def test_two_fresh_observations_bracket_key_load(monkeypatch):
    state=State();calls=[]
    def observe(context):calls.append(context);state.events.append('root');return observation()
    monkeypatch.setattr(admission.state_admission,'request_live',observe)
    result=admission.verify_existing(state)
    assert len(calls)==2 and calls==[state.context,state.context]
    assert state.events.index('root')<state.events.index('identity')<len(state.events)-state.events[::-1].index('root')-1
    assert not result['transport_enabled'] and not result['control_authorized']


@pytest.mark.parametrize('when',[0,1])
def test_hold_before_or_after_loading_latches(monkeypatch,when):
    state=State();calls=[]
    def observe(context):
        value=observation()
        if len(calls)==when:value.update(recovery_hold=True,identity_action='block',receipt=None)
        calls.append(1);return value
    monkeypatch.setattr(admission.state_admission,'request_live',observe)
    with pytest.raises(StateError,match='recovery-required'):admission.verify_existing(state)
    assert ('identity' in state.events)==bool(when)
    with pytest.raises(StateError):admission.verify_existing(state)
    assert len(calls)==when+1


@pytest.mark.parametrize('change',['receipt','bindings','unavailable','missing-key'])
def test_changed_or_missing_evidence_blocks(monkeypatch,change):
    state=State();calls=[]
    def observe(context):
        value=observation()
        if calls:
            if change=='unavailable':raise OSError('server unavailable')
            if change in ('receipt','bindings'):value[change]={'different':True}
        calls.append(1);return value
    if change=='missing-key':state._identity=lambda _:(_ for _ in ()).throw(ValueError('missing key'))
    monkeypatch.setattr(admission.state_admission,'request_live',observe)
    with pytest.raises(StateError):admission.verify_existing(state)
    assert state.fault


def test_production_transport_remains_disabled():
    from zog.host_discover.managed_transport import Transport
    with pytest.raises(StateError,match='managed-transport-disabled'):Transport().post()
