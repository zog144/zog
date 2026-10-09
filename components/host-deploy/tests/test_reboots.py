import json
from pathlib import Path
import time
import uuid

import pytest
from zog.host_deploy import reboot_remote as remote
from zog.host_deploy.workspace import save
from zog.host_deploy.reboots import validate


def recipe():
    return {'preparation':{'command':['true'],'timeout_seconds':30},
            'verification':{'command':['true'],'timeout_seconds':30},
            'reboot_timeout_seconds':120,'outputs':['.']}


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    root=tmp_path/uuid.uuid4().hex
    root.mkdir()
    save(root/'workflow.json',{'recipe':recipe(),'uptime_limit_seconds':10**12})
    save(root/'progress.json',{'phase':'ready','before_boot_id':'boot-one'})
    monkeypatch.setattr(remote,'boot_id',lambda:'boot-one')
    monkeypatch.setattr(remote,'active',lambda name:False)
    monkeypatch.setattr(remote.os,'sync',lambda:None)
    return root


def test_lost_preparation_dispatch_is_never_replayed(workflow,monkeypatch):
    calls=[]
    def lost(*a,**k):
        calls.append(a)
        raise TimeoutError('lost systemd response')
    monkeypatch.setattr(remote.subprocess,'run',lost)
    with pytest.raises(TimeoutError): remote.advance(workflow)
    state=remote.advance(workflow)
    assert state['phase']=='uncertain' and len(calls)==1


def test_lost_reboot_dispatch_is_never_replayed(workflow,monkeypatch):
    save(workflow/'progress.json',{'phase':'prepared','before_boot_id':'boot-one'})
    calls=[]
    def lost(*a,**k):
        calls.append(a)
        raise TimeoutError('lost reboot response')
    monkeypatch.setattr(remote.subprocess,'run',lost)
    with pytest.raises(TimeoutError): remote.advance(workflow)
    assert remote.advance(workflow)['phase']=='reboot_submitting'
    assert len(calls)==1


def test_changed_boot_and_active_timer_required(workflow,monkeypatch):
    save(workflow/'progress.json',{'phase':'reboot_wait','before_boot_id':'boot-one','reboot_requested_at':time.time()})
    assert remote.observe(workflow)['phase']=='reboot_wait'
    monkeypatch.setattr(remote,'boot_id',lambda:'boot-two')
    monkeypatch.setattr(remote,'facts',lambda: {'boot_id':'boot-two','expiry_active':True,'expiry_enabled':True,'observed_at':time.time(),'uptime_seconds':10})
    assert remote.observe(workflow)['phase']=='rebooted'
    assert json.loads((workflow/'after.json').read_text())['boot_id']=='boot-two'


def test_missing_timer_blocks_verification(workflow,monkeypatch):
    save(workflow/'progress.json',{'phase':'reboot_wait','before_boot_id':'boot-one','reboot_requested_at':time.time()})
    monkeypatch.setattr(remote,'boot_id',lambda:'boot-two')
    monkeypatch.setattr(remote,'facts',lambda: {'expiry_active':False,'expiry_enabled':True,'observed_at':time.time(),'uptime_seconds':10})
    assert remote.observe(workflow)['phase']=='uncertain'


def test_reboot_timeout_never_reissues_request(workflow):
    save(workflow/'progress.json',{'phase':'reboot_wait','before_boot_id':'boot-one','reboot_requested_at':time.time()-121})
    assert remote.advance(workflow)['phase']=='uncertain'
    assert remote.advance(workflow)['phase']=='uncertain'


def test_delayed_controller_can_recognize_timely_reboot(workflow,monkeypatch):
    save(workflow/'progress.json',{'phase':'reboot_wait','before_boot_id':'boot-one','reboot_requested_at':time.time()-500})
    monkeypatch.setattr(remote,'boot_id',lambda:'boot-two')
    monkeypatch.setattr(remote,'facts',lambda: {'expiry_active':True,'expiry_enabled':True,'observed_at':time.time(),'uptime_seconds':480})
    assert remote.observe(workflow)['phase']=='rebooted'


def test_unexpected_reboot_before_request_blocks_mutation(workflow,monkeypatch):
    monkeypatch.setattr(remote,'boot_id',lambda:'unexpected-boot')
    assert remote.advance(workflow)['phase']=='uncertain'


def test_preparation_failure_preserves_failure_without_reboot(workflow):
    save(workflow/'progress.json',{'phase':'preparation_submitting','before_boot_id':'boot-one'})
    save(workflow/'preparation.json',{'state':'failed','return_code':7})
    state=remote.advance(workflow)
    assert state['phase']=='failed' and state['preparation']['return_code']==7
    assert 'reboot_requested_at' not in state


def test_completed_verification_is_not_dispatched_again(workflow):
    save(workflow/'progress.json',{'phase':'verification_submitting','before_boot_id':'boot-zero','after_boot_id':'boot-one'})
    save(workflow/'verification.json',{'state':'succeeded','return_code':0})
    assert remote.advance(workflow)['phase']=='succeeded'
    assert remote.advance(workflow)['phase']=='succeeded'


def test_abandon_cannot_release_pending_reboot_on_same_boot(workflow):
    save(workflow/'progress.json',{'phase':'uncertain','before_boot_id':'boot-one','reboot_requested_at':time.time()})
    with pytest.raises(RuntimeError,match='still be queued'): remote.abandon(workflow)


def test_recipe_rejects_unsafe_state_paths():
    value=recipe(); value['outputs']=['../elsewhere']
    with pytest.raises(ValueError): validate(value)


def test_persistence_failure_prevents_dispatch(workflow,monkeypatch):
    calls=[]
    monkeypatch.setattr(remote.subprocess,'run',lambda *a,**k:calls.append(a))
    def fail(*args): raise OSError('storage failed')
    monkeypatch.setattr(remote,'save',fail)
    with pytest.raises(OSError): remote.advance(workflow)
    assert calls==[]


def test_lost_verification_dispatch_is_not_replayed(workflow,monkeypatch):
    save(workflow/'progress.json',{'phase':'rebooted','before_boot_id':'boot-zero','after_boot_id':'boot-one'})
    calls=[]
    def lost(*a,**k):
        calls.append(a)
        raise TimeoutError('lost verification reply')
    monkeypatch.setattr(remote.subprocess,'run',lost)
    with pytest.raises(TimeoutError): remote.advance(workflow)
    assert remote.advance(workflow)['phase']=='uncertain'
    assert len(calls)==1


def test_abandoned_workflow_collects_remaining_checkpoint(workflow):
    import io
    import tarfile
    save(workflow/'progress.json',{'phase':'abandoned','before_boot_id':'boot-one'})
    (workflow/'state').mkdir()
    (workflow/'state'/'checkpoint.json').write_text('{"retained":true}')
    result=remote.collect(workflow)
    assert result['sha256']==remote.sha(workflow/'results.tar.gz')
    with tarfile.open(workflow/'results.tar.gz') as bundle:
        data=bundle.extractfile('recovery-state.tar.gz').read()
        with tarfile.open(fileobj=io.BytesIO(data)) as state:
            assert json.load(state.extractfile('state/checkpoint.json'))['retained']
