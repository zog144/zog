import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from zog.host_deploy import remote_control, provision
from zog.host_deploy.workspace import initialize, save


def test_cancel_does_not_rewrite_completed_outcome(tmp_path, monkeypatch):
    (tmp_path/'cancel.json').write_text('{}')
    (tmp_path/'status.json').write_text(json.dumps({'state':'succeeded','return_code':0}))
    monkeypatch.setattr(remote_control.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='inactive', stderr=''))
    assert remote_control.status(tmp_path, 'unit')['state'] == 'succeeded'
    (tmp_path/'status.json').write_text(json.dumps({'state':'interrupted'}))
    assert remote_control.status(tmp_path, 'unit')['state'] == 'cancelled'


def test_uncertain_submission_remains_uncertain(tmp_path, monkeypatch):
    (tmp_path/'dispatch.json').write_text('{}')
    monkeypatch.setattr(remote_control.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='inactive', stderr=''))
    assert remote_control.status(tmp_path, 'unit')['state'] == 'submission_uncertain'


def test_systemd_inspection_error_never_becomes_inactive(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_control.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='Failed to connect to bus'))
    with pytest.raises(RuntimeError, match='Cannot inspect'):
        remote_control.status(tmp_path, 'unit')


def test_shutdown_guard_failure_prevents_ec2_mutation(tmp_path, monkeypatch):
    workspace = initialize(tmp_path, 'test', 'test', 'us-east-1')
    save(tmp_path/'host.json', workspace | {'instance_id':'i-test', 'account_id':'123'})
    class Cloud:
        def __init__(self, value): pass
        def owned(self, *a): return {'State':{'Name':'running'}}
        @property
        def ec2(self): raise AssertionError('EC2 mutation reached despite guard failure')
    class Host:
        def __init__(self, config): pass
        def command(self, *a): raise RuntimeError('Active or uncertain jobs prevent shutdown')
    monkeypatch.setattr(provision, 'Cloud', Cloud)
    monkeypatch.setattr('zog.host_deploy.runner.Host', Host)
    for action in ['stop','terminate']:
        with pytest.raises(RuntimeError, match='prevent shutdown'):
            provision.operate(tmp_path, action)


def test_start_wait_failure_attempts_owned_host_stop(tmp_path, monkeypatch):
    workspace = initialize(tmp_path, 'test', 'test', 'us-east-1')
    save(tmp_path/'host.json', workspace | {'instance_id':'i-test', 'account_id':'123'})
    calls = []
    class EC2:
        def start_instances(self, **kw): calls.append('start')
        def get_waiter(self, name): return self
        def wait(self, **kw): raise TimeoutError('start wait failed')
        def stop_instances(self, **kw): calls.append('stop')
    class Cloud:
        def __init__(self, value): self.ec2 = EC2()
        def owned(self, *a):
            calls.append('ownership')
            return {'State':{'Name':'stopped'}}
    monkeypatch.setattr(provision, 'Cloud', Cloud)
    with pytest.raises(TimeoutError): provision.operate(tmp_path, 'start')
    assert calls == ['ownership','start','ownership','stop']


def test_readiness_error_does_not_stop_preexisting_running_jobs(tmp_path, monkeypatch):
    workspace = initialize(tmp_path, 'test', 'test', 'us-east-1')
    save(tmp_path/'host.json', workspace | {'instance_id':'i-test', 'account_id':'123'})
    class EC2:
        def get_waiter(self, name): return self
        def wait(self, **kw): pass
        def stop_instances(self, **kw): raise AssertionError('Stopped a pre-existing running host')
    class Cloud:
        def __init__(self, value): self.ec2 = EC2()
        def owned(self, *a): return {'State':{'Name':'running'}}
    class Host:
        def __init__(self, config): pass
        def online(self): raise TimeoutError('SSM unavailable')
    monkeypatch.setattr(provision, 'Cloud', Cloud)
    monkeypatch.setattr('zog.host_deploy.runner.Host', Host)
    with pytest.raises(TimeoutError): provision.operate(tmp_path, 'start')


def test_reboot_reservation_blocks_shutdown_across_boot(tmp_path, monkeypatch):
    owner=tmp_path/'owner.json'
    state=tmp_path/'workflow'
    state.mkdir()
    owner.write_text(json.dumps({'remote_directory':str(state)}))
    (state/'progress.json').write_text(json.dumps({'phase':'reboot_wait'}))
    original=Path
    monkeypatch.setattr(remote_control,'Path',lambda p: owner if p=='/var/lib/host-deploy/reboot-owner.json' else original(p))
    with pytest.raises(RuntimeError,match='Reboot workflow'): remote_control.drain()
    (state/'progress.json').write_text(json.dumps({'phase':'succeeded'}))
    assert remote_control.reboot_busy() is False
