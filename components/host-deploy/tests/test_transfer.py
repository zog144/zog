import hashlib
import shlex
import subprocess

import pytest

from zog.host_deploy.runner import Host

class LocalHost(Host):
    def __init__(self):
        pass
    def command(self, script, seconds=120):
        return subprocess.check_output(script, shell=True, text=True).strip()

def test_binary_roundtrip_across_chunk_boundaries(tmp_path):
    data = bytes(range(256))*101
    path = str(tmp_path/'payload.bin')
    host = LocalHost()
    host.upload(data, path)
    assert host.download(path) == data

def test_truncated_download_rejected(tmp_path):
    path = tmp_path/'payload.bin'
    path.write_bytes(b'content')
    class TruncatedHost(LocalHost):
        def command(self, script, seconds=120):
            result = super().command(script, seconds)
            return '' if 'base64.b64encode' in script else result
    with pytest.raises(ValueError, match='length or hash'):
        TruncatedHost().download(str(path))

def test_transfer_failure_still_stops_host(tmp_path, monkeypatch):
    import zipfile
    from zog.host_deploy import runner
    events = []
    class Waiter:
        def wait(self, **kwargs):
            pass
    class EC2:
        def describe_instances(self, **kwargs):
            return {'Reservations':[{'Instances':[{'State':{'Name':'stopped'}}]}]}
        def start_instances(self, **kwargs):
            events.append('start')
        def stop_instances(self, **kwargs):
            events.append('stop')
        def get_waiter(self, name):
            return Waiter()
    class BrokenHost:
        def __init__(self, configuration):
            self.ec2 = EC2()
            self.instance = 'test'
            self.commands = []
        def online(self):
            pass
        def command(self, script):
            events.append('deadline')
        def upload(self, data, destination):
            raise RuntimeError('simulated upload failure')
    monkeypatch.setattr(runner, 'Host', BrokenHost)
    archive = tmp_path/'source.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('box-control/tests/test_systemd_integration.py', '')
    with pytest.raises(RuntimeError, match='simulated upload failure'):
        runner.execute({}, archive, tmp_path/'output')
    assert events == ['start', 'deadline', 'stop']

def test_recovery_rejects_different_host_before_aws(tmp_path):
    import json
    from zog.host_deploy.runner import recover
    identifier = 'a'*32
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps({'run_id':identifier,'remote_directory':'/var/lib/host-deploy/'+identifier,
                               'host':{'instance_id':'original','region':'us-east-1'}}))
    with pytest.raises(ValueError, match='host does not match'):
        recover({'instance_id':'different','region':'us-east-1'}, path)


def test_resumable_upload_after_lost_chunk_reply(tmp_path):
    from zog.host_deploy import transfer
    data=b'x'*17000
    class Interrupted(LocalHost):
        def __init__(self): self.writes=0
        def command(self,script,seconds=120):
            result=super().command(script,seconds)
            if 'base64.b64decode' in script:
                self.writes+=1
                if self.writes==1: raise TimeoutError('reply lost')
            return result
    host=Interrupted(); target=str(tmp_path/'remote')
    with pytest.raises(TimeoutError): transfer.upload(host,data,target)
    assert not (tmp_path/'remote').exists()
    transfer.upload(host,data,target)
    assert host.writes==3
    assert (tmp_path/'remote').read_bytes()==data


def test_resumable_download_skips_completed_payload(tmp_path):
    from zog.host_deploy import transfer
    data=b'x'*25000; source=tmp_path/'remote'; source.write_bytes(data)
    class Interrupted(LocalHost):
        def __init__(self): self.reads=0
        def command(self,script,seconds=120):
            if 'base64.b64encode' in script:
                self.reads+=1
                if self.reads==2: raise TimeoutError('disconnected')
            return super().command(script,seconds)
    host=Interrupted(); output=tmp_path/'result'
    with pytest.raises(TimeoutError): transfer.download(host,str(source),output)
    transfer.download(host,str(source),output)
    assert host.reads==4 and output.read_bytes()==data
