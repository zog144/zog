import json
from uuid import uuid4
import pytest
from zog.host_deploy import station_remote as remote
from zog.host_deploy.station import StationDeployment, NotSubmitted
from unittest.mock import Mock

@pytest.fixture
def setup(tmp_path,monkeypatch):
    path=tmp_path/'destinations.json';path.write_text('{}')
    monkeypatch.setattr(remote,'DESTINATIONS',path)
    monkeypatch.setattr(remote,'RECEIPTS',tmp_path/'receipts')
    def guard():remote.RECEIPTS.mkdir(exist_ok=True)
    monkeypatch.setattr(remote,'guard_receipts',guard)
    target=dict(host_id=str(uuid4()),account_id='123456789012',region='us-east-1',instance_id='i-1234567890abcdef0',workspace_id='owned')
    row=dict(id=str(uuid4()),label='Primary',server='https://registry.example',enabled=True,ca_certificate='',revision=1)
    request=dict(id=str(uuid4()),action='apply',target=target,expected_sha256=remote.digest(path.read_bytes()),destinations=dict(version=1,destinations=[row]))
    monkeypatch.setattr(remote,'inspect_host',lambda target:dict(primary=row['server'],destinations_sha256=remote.digest(path.read_bytes()),apply_supported=True))
    return path,request

def test_compare_and_swap_idempotency_and_identity_preservation(setup):
    path,request=setup
    assert remote.handle(request)['status']=='installed'
    before=path.read_bytes()
    assert remote.handle(request)['status']=='installed'
    assert path.read_bytes()==before
    assert remote.handle(dict(request,action='recover'))['status']=='installed'
    altered=dict(request,destinations=dict(version=1,destinations=[]))
    with pytest.raises(ValueError):remote.handle(altered)

def test_concurrent_configuration_change_blocks_apply(setup):
    path,request=setup;path.write_text('{"changed":true}')
    assert remote.handle(request)['status']=='blocked'
    assert json.loads(path.read_text())=={'changed':True}

def test_recovery_without_receipt_does_not_mutate(setup):
    path,request=setup
    assert remote.handle(dict(request,action='recover'))['status']=='uncertain'
    assert path.read_text()=='{}' and not remote.RECEIPTS.exists()

def test_prepared_receipt_resolves_lost_completion_reply(setup,monkeypatch):
    path,request=setup
    original=remote.atomic
    def fail_receipt(path,data,*args):
        if path.name==request['id']+'.json' and json.loads(data).get('phase')=='installed':raise OSError('lost write')
        original(path,data,*args)
    monkeypatch.setattr(remote,'atomic',fail_receipt)
    with pytest.raises(OSError):remote.handle(request)
    assert remote.handle(dict(request,action='recover'))['status']=='installed'

def test_primary_cannot_be_disabled_and_private_keys_rejected(setup):
    path,request=setup;request['destinations']['destinations'][0]['enabled']=False
    with pytest.raises(ValueError):remote.handle(request)
    request['destinations']['destinations'][0].update(enabled=True,ca_certificate='PRIVATE KEY')
    with pytest.raises(ValueError):remote.handle(request)
    assert path.read_text()=='{}'

def test_symlink_destination_rejected(setup,tmp_path):
    path,request=setup;path.unlink();target=tmp_path/'real';target.write_text('{}');path.symlink_to(target)
    with pytest.raises(ValueError):remote.handle(request)
    assert target.read_text()=='{}'

def test_transport_account_mismatch_does_not_submit(setup):
    _,request=setup;client=StationDeployment.__new__(StationDeployment);client.target=request['target']
    client.ssm=Mock();client.ec2=Mock();client.sts=Mock()
    client.sts.get_caller_identity.return_value={'Account':'999999999999'}
    with pytest.raises(NotSubmitted):client.submit(request)
    client.ssm.send_command.assert_not_called()

def test_send_exception_is_not_retried_or_classified_not_submitted(setup):
    _,request=setup;client=StationDeployment.__new__(StationDeployment);client.target=request['target']
    client.ssm=Mock();client.ec2=Mock();client.sts=Mock()
    client.sts.get_caller_identity.return_value={'Account':request['target']['account_id']}
    client.ec2.describe_instances.return_value={'Reservations':[{'Instances':[{'InstanceId':request['target']['instance_id'],'State':{'Name':'running'},'Tags':[{'Key':'ZogWorkspace','Value':'owned'}]}]}]}
    client.ssm.send_command.side_effect=TimeoutError()
    with pytest.raises(TimeoutError):client.submit(request)
    assert client.ssm.send_command.call_count==1

def test_inspection_reads_installed_process_and_treats_missing_station_as_unknown(tmp_path,monkeypatch):
    import os
    config=tmp_path/'configuration.json';dest=tmp_path/'destinations.json'
    target=dict(host_id=str(uuid4()),account_id='123456789012',region='us-east-1',instance_id='i-1234567890abcdef0')
    config.write_text(json.dumps(dict(provider='aws',cloud={k:target[k] for k in ('account_id','region','instance_id')},server='https://registry.example')))
    row=dict(id=str(uuid4()),label='Primary',server='https://registry.example',enabled=True,revision=1,ca_certificate='')
    dest.write_text(json.dumps(dict(version=1,destinations=[row])));dest.chmod(0o600)
    monkeypatch.setattr(remote,'CONFIG',config);monkeypatch.setattr(remote,'DESTINATIONS',dest)
    pid=os.getpid();real_read=remote.read
    # The service PID is a fixture, not a process in the test runner's /proc mount.
    real_stat=remote.Path.stat
    monkeypatch.setattr(remote.Path,'stat',lambda path,*a,**kw: real_stat(dest) if str(path)==f'/proc/{pid}' else real_stat(path,*a,**kw))
    def read(path,*args):
        if str(path)==f'/proc/{pid}/cmdline':return ('python\0/opt/host-discover/venv/bin/host-discover\0--configuration\0'+str(config)+'\0--destinations\0'+str(dest)+'\0').encode()
        return real_read(path,*args)
    monkeypatch.setattr(remote,'read',read)
    monkeypatch.setattr(remote.subprocess,'run',lambda argv,**kwargs:Mock(returncode=0,stdout=f'ActiveState=active\nMainPID={pid}\n') if argv[2]=='host-discover.service' else Mock(returncode=1,stdout=''))
    observed=remote.inspect_host(target)
    assert observed['apply_supported'] and observed['station_state']=='unknown'
    assert observed['destinations_sha256']==remote.digest(dest.read_bytes())
    assert 'ca_certificate' not in observed['destinations'][0]
    target['account_id']='999999999999'
    with pytest.raises(ValueError,match='target-mismatch'):remote.inspect_host(target)
