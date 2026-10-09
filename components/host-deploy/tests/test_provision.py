import json
from pathlib import Path
import pytest

from zog.host_deploy import provision as implementation
from zog.host_deploy.workspace import initialize, locked
from zog.host_deploy.bootstrap import import_credentials


def specification():
    return dict(image_id='ami-test',instance_type='t3.micro',subnet_id='subnet-test',security_group_id='sg-test',
                instance_profile='role',root_device='/dev/xvda',volume_gib=8,maximum_uptime_minutes=30)

class FakeEC2:
    def __init__(self):
        self.instances=[]
        self.calls=0
        self.lose_reply=False
    def get_paginator(self,name):
        return self
    def paginate(self,**kwargs):
        token=kwargs['Filters'][0]['Values'][0]
        return [{'Reservations':[{'Instances':[i for i in self.instances if i['ClientToken']==token]}]}]
    def run_instances(self,**request):
        self.calls+=1
        instance={'InstanceId':'i-'+str(self.calls),'State':{'Name':'running'},'ClientToken':request['ClientToken'],
                  'Tags':request['TagSpecifications'][0]['Tags']}
        self.instances.append(instance)
        if self.lose_reply:
            raise TimeoutError('lost reply')
        return {'Instances':[instance]}
    def describe_instances(self,**kwargs):
        return {'Reservations':[{'Instances':[i for i in self.instances if i['InstanceId'] in kwargs['InstanceIds']]}]}

@pytest.fixture
def cloud(monkeypatch):
    ec2=FakeEC2()
    class FakeCloud(implementation.Cloud):
        def __init__(self,workspace):
            self.workspace=workspace
            self.ec2=ec2
        def account(self):
            return '123456789012'
    monkeypatch.setattr(implementation,'Cloud',FakeCloud)
    return ec2


def test_two_workspaces_have_different_hosts_and_tokens(tmp_path,cloud):
    hosts=[]
    for name in ['box-control','image-build']:
        root=tmp_path/name
        initialize(root,name,'test','us-east-1')
        hosts.append(implementation.create_host(root,specification()))
    assert hosts[0]['instance_id'] != hosts[1]['instance_id']
    assert hosts[0]['workspace_id'] != hosts[1]['workspace_id']
    assert cloud.instances[0]['ClientToken'] != cloud.instances[1]['ClientToken']
    with pytest.raises(RuntimeError,match='another workspace'):
        implementation.Cloud({'workspace_id':hosts[0]['workspace_id']}).owned(hosts[1]['instance_id'],'123456789012')


def test_lost_reply_recovers_without_second_launch(tmp_path,cloud):
    initialize(tmp_path,'box','test','us-east-1')
    cloud.lose_reply=True
    with pytest.raises(TimeoutError):
        implementation.create_host(tmp_path,specification())
    assert json.loads((tmp_path/'launch.json').read_text())['phase']=='submitting'
    configuration=implementation.create_host(tmp_path,specification())
    assert configuration['instance_id']=='i-1'
    assert cloud.calls==1


def test_uncertain_launch_without_visible_instance_refuses_replay(tmp_path,cloud):
    initialize(tmp_path,'box','test','us-east-1')
    cloud.lose_reply=True
    with pytest.raises(TimeoutError):
        implementation.create_host(tmp_path,specification())
    cloud.instances=[]
    with pytest.raises(RuntimeError,match='refusing automatic replay'):
        implementation.create_host(tmp_path,specification())
    assert cloud.calls==1


def test_changed_specification_never_relaunches(tmp_path,cloud):
    initialize(tmp_path,'box','test','us-east-1')
    implementation.create_host(tmp_path,specification())
    changed=specification()
    changed['volume_gib']=16
    with pytest.raises(ValueError,match='differs'):
        implementation.create_host(tmp_path,changed)
    assert cloud.calls==1


def test_lock_blocks_other_local_operation(tmp_path):
    with locked(tmp_path):
        with pytest.raises(RuntimeError,match='workspace lock'):
            with locked(tmp_path):
                pass


def test_import_preserves_existing_profile_and_permissions(tmp_path):
    source=tmp_path/'input.txt'
    source.write_text('Access key ID: '+'A'*20+'\nSecret access key: synthetic-test-secret\n')
    destination=tmp_path/'aws/credentials'
    import_credentials(source,destination,'one')
    import_credentials(source,destination,'two')
    assert destination.stat().st_mode & 0o777 == 0o600
    text=destination.read_text()
    assert '[one]' in text and '[two]' in text
    source.write_text('Access key ID: '+'B'*20+'\nSecret access key: different\n')
    with pytest.raises(ValueError,match='Profile exists'):
        import_credentials(source,destination,'one')
    assert destination.read_text()==text


def test_storage_failure_prevents_launch(tmp_path,cloud,monkeypatch):
    initialize(tmp_path,'box','test','us-east-1')
    def broken_save(*args):
        raise OSError('disk failure')
    monkeypatch.setattr(implementation,'save',broken_save)
    with pytest.raises(OSError):
        implementation.create_host(tmp_path,specification())
    assert cloud.calls==0


def test_discovery_failure_retries_same_instance(tmp_path,cloud,monkeypatch):
    from zog.host_deploy import discovery
    root=tmp_path/'host'
    initialize(root,'reporter','test','us-east-1')
    monkeypatch.setattr(implementation,'operate',lambda *a:None)
    attempts=[]
    def install(directory,**options):
        attempts.append(directory)
        if len(attempts)==1: raise ConnectionError('unavailable')
        return {'host_id':'registered'}
    monkeypatch.setattr(discovery,'install',install)
    with pytest.raises(RuntimeError,match='discovery incomplete'): implementation.provision(root,specification(),registry_configuration={'server_ready':True,'server':'https://registry.example.test'})
    assert json.loads((root/'discovery-provision.json').read_text())['state']=='incomplete'
    result=implementation.provision(root,specification(),registry_configuration={'server_ready':True,'server':'https://registry.example.test'})
    assert cloud.calls==1 and result['discovery']['host_id']=='registered'


def test_discovery_opt_out(tmp_path,cloud,monkeypatch):
    from zog.host_deploy import discovery
    root=tmp_path/'host';initialize(root,'reporter','test','us-east-1')
    monkeypatch.setattr(discovery,'install',lambda *a,**k:pytest.fail('Unexpected enrollment'))
    assert implementation.provision(root,specification(),discovery=False)['instance_id']=='i-1'


def test_persistent_host_is_explicit():
    settings=specification()|{'lifetime':'persistent','maximum_uptime_minutes':None}
    request=implementation.make_request({'workspace_id':'test','name':'test'},settings,'token')
    assert 'poweroff' not in request['UserData']
    with pytest.raises(ValueError,match='require'): implementation.make_request({'workspace_id':'test','name':'test'},settings|{'maximum_uptime_minutes':30},'token')


def test_missing_discovery_server_never_creates_host(monkeypatch,tmp_path):
    from zog.host_deploy import provision as implementation
    from unittest.mock import Mock
    create=Mock();monkeypatch.setattr(implementation,'create_host',create)
    with pytest.raises(ValueError,match='Explicit server'):
        implementation.provision(tmp_path/'w',{},registry_configuration={'server_ready':True})
    create.assert_not_called()
