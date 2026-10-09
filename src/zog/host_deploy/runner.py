"""Bounded SSM runner. Credentials are resolved by boto3, never bundled."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import time
import io
import tarfile
import uuid
import zipfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Host:
    def __init__(self, configuration):
        self.instance = configuration['instance_id']
        session = boto3.Session(profile_name=configuration.get('profile'), region_name=configuration['region'])
        options = Config(connect_timeout=10, read_timeout=30, retries={'mode':'standard','total_max_attempts':3})
        self.ec2 = session.client('ec2', config=options)
        self.ssm = session.client('ssm', config=options)
        if configuration.get('workspace_id'):
            from .provision import Cloud
            Cloud(configuration).owned(self.instance, configuration['account_id'])
        self.commands = []
        self.on_command = None
        self.ssm_mutation = session.client('ssm', config=Config(connect_timeout=10, read_timeout=30, retries={'total_max_attempts':1}))

    def command(self, script, seconds=120):
        response = self.ssm_mutation.send_command(InstanceIds=[self.instance], DocumentName='AWS-RunShellScript', TimeoutSeconds=60,
            Parameters={'commands':[script], 'executionTimeout':[str(seconds)]})
        identifier = response['Command']['CommandId']
        self.commands.append(identifier)
        if self.on_command is not None:
            self.on_command()
        deadline = time.monotonic() + seconds + 90
        while time.monotonic() < deadline:
            try:
                result = self.ssm.get_command_invocation(CommandId=identifier, InstanceId=self.instance)
            except ClientError as error:
                if error.response['Error']['Code'] != 'InvocationDoesNotExist':
                    raise
            else:
                if result['Status'] in {'Success','Failed','Cancelled','TimedOut'}:
                    if result['Status'] != 'Success':
                        raise RuntimeError('SSM command '+identifier+' '+result['Status']+': '+result.get('StandardErrorContent','')[-2000:])
                    return result['StandardOutputContent'].strip()
            time.sleep(2)
        raise TimeoutError('SSM completion unknown: '+identifier)

    def upload(self, data, destination):
        from .transfer import upload
        upload(self,data,destination)

    def download(self, source):
        code = f"import os,hashlib; p={source!r}; print(os.path.getsize(p),hashlib.sha256(open(p,'rb').read()).hexdigest())"
        size, expected = self.command('python3 -c '+shlex.quote(code)).split()
        if int(size) > 20*1024*1024:
            raise ValueError('result exceeds first-pass 20 MiB transfer limit; retained on host')
        data = bytearray()
        for offset in range(0, int(size), 12000):
            code = f"import base64; f=open({source!r},'rb'); f.seek({offset}); print(base64.b64encode(f.read(12000)).decode())"
            data.extend(base64.b64decode(self.command('python3 -c '+shlex.quote(code)), validate=True))
        if len(data) != int(size) or digest(data) != expected:
            raise ValueError('download length or hash mismatch')
        return bytes(data)

    def online(self):
        deadline = time.monotonic()+360
        while time.monotonic()<deadline:
            items = self.ssm.describe_instance_information(Filters=[{'Key':'InstanceIds','Values':[self.instance]}])['InstanceInformationList']
            if items and items[0]['PingStatus']=='Online':
                return
            time.sleep(5)
        raise TimeoutError('SSM did not become online')


def execute(configuration, archive, output):
    data = Path(archive).read_bytes()
    if len(data)>2*1024*1024:
        raise ValueError('first-pass source transfer limit is 2 MiB')
    with zipfile.ZipFile(archive) as source:
        if 'box-control/tests/test_systemd_integration.py' not in source.namelist():
            raise ValueError('expected Zog source bundle')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    host = Host(configuration)
    run_id = uuid.uuid4().hex
    remote = '/var/lib/host-deploy/'+run_id
    manifest = {'run_id':run_id, 'host':configuration, 'source_sha256':digest(data), 'remote_directory':remote}
    def record():
        manifest['command_ids'] = host.commands
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    host.on_command = record
    record()
    state = host.ec2.describe_instances(InstanceIds=[host.instance])['Reservations'][0]['Instances'][0]['State']['Name']
    if state != 'stopped':
        raise RuntimeError('first pass requires a stopped disposable instance')
    try:
        print('Starting test host', flush=True)
        host.ec2.start_instances(InstanceIds=[host.instance])
        host.ec2.get_waiter('instance_running').wait(InstanceIds=[host.instance], WaiterConfig={'Delay':5,'MaxAttempts':60})
        host.online()
        # This survives loss of the Work session after this command succeeds.
        host.command('set -eu\nshutdown -P +30\ninstall -d -m 700 '+remote)
        manifest['shutdown_deadline_armed'] = True
        record()
        print('Transferring and verifying source', flush=True)
        host.upload(data, remote+'/source.zip')
        host.upload(Path(__file__).with_name('remote.py').read_bytes(), remote+'/remote.py')
        print('Preparing host and running tests', flush=True)
        host.command('timeout --signal=TERM --kill-after=20s 900s python3 '+remote+'/remote.py '+remote+' > '+remote+'/runner.log 2>&1 || true', seconds=940)
        print('Collecting evidence', flush=True)
        host.command('cd '+remote+' && tar --exclude=rootfs --exclude=root.sock -czf results.tar.gz results runner.log')
        evidence = host.download(remote+'/results.tar.gz')
        (output/'results.tar.gz').write_bytes(evidence)
        manifest['collected'] = True
        with tarfile.open(fileobj=io.BytesIO(evidence), mode='r:gz') as bundle:
            status = json.load(bundle.extractfile('results/status.json'))
        manifest['test_status'] = status
        if status.get('baseline') != 0 or status.get('integration') != 0 or 'error' in status:
            raise RuntimeError('Remote tests or preparation failed; see collected evidence')
    except BaseException as error:
        manifest['error'] = str(error)
        raise
    finally:
        # Failure to write local evidence must not prevent stopping this test VM.
        print('Stopping test host', flush=True)
        try:
            host.ec2.stop_instances(InstanceIds=[host.instance])
            host.ec2.get_waiter('instance_stopped').wait(InstanceIds=[host.instance], WaiterConfig={'Delay':5,'MaxAttempts':60})
            manifest['final_state'] = 'stopped'
        except Exception as error:
            manifest['stop_error'] = str(error)
            raise
        finally:
            record()


def recover(configuration, manifest_path):
    """Collect a completed remote run after a lost client session; never rerun tests."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    remote = manifest['remote_directory']
    run_id = uuid.UUID(manifest['run_id']).hex
    if remote != '/var/lib/host-deploy/' + run_id:
        raise ValueError('unexpected recovery directory')
    if configuration['instance_id'] != manifest['host']['instance_id'] or configuration['region'] != manifest['host']['region']:
        raise ValueError('recovery host does not match manifest')
    host = Host(configuration)
    state = host.ec2.describe_instances(InstanceIds=[host.instance])['Reservations'][0]['Instances'][0]['State']['Name']
    if state != 'stopped':
        raise RuntimeError('recovery requires a stopped disposable instance')
    try:
        host.ec2.start_instances(InstanceIds=[host.instance])
        host.ec2.get_waiter('instance_running').wait(InstanceIds=[host.instance], WaiterConfig={'Delay':5,'MaxAttempts':60})
        host.online()
        host.command('shutdown -P +15')
        host.command('cd '+remote+' && tar --exclude=rootfs --exclude=root.sock -czf recovered-results.tar.gz results runner.log')
        evidence = host.download(remote+'/recovered-results.tar.gz')
        (manifest_path.parent/'results.tar.gz').write_bytes(evidence)
        manifest['collected'] = True
        with tarfile.open(fileobj=io.BytesIO(evidence), mode='r:gz') as bundle:
            status = json.load(bundle.extractfile('results/status.json'))
        manifest['test_status'] = status
        if status.get('baseline') != 0 or status.get('integration') != 0 or 'error' in status:
            raise RuntimeError('Recovered run did not pass; see collected evidence')
    finally:
        try:
            host.ec2.stop_instances(InstanceIds=[host.instance])
            host.ec2.get_waiter('instance_stopped').wait(InstanceIds=[host.instance], WaiterConfig={'Delay':5,'MaxAttempts':60})
            manifest['final_state'] = 'stopped'
        except Exception as error:
            manifest['stop_error'] = str(error)
            raise
        finally:
            manifest['recovery_command_ids'] = host.commands
            manifest_path.write_text(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source')
    mode.add_argument('--recover', metavar='MANIFEST')
    parser.add_argument('--output')
    arguments = parser.parse_args()
    configuration = json.loads(Path(arguments.host).read_text())
    if arguments.recover:
        recover(configuration, arguments.recover)
    else:
        if not arguments.output:
            parser.error('--output is required with --source')
        execute(configuration, arguments.source, arguments.output)

if __name__ == '__main__':
    main()
