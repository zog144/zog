"""Controller-side two-phase reboot workflows; durable remote receipts own progress."""
import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid
from botocore.exceptions import ClientError, EndpointConnectionError, ConnectionClosedError, ReadTimeoutError, ConnectTimeoutError

from .workspace import locked, save
from .provision import configuration
from .runner import Host
from .jobs import sha, validate as validate_job, shell_python

FINAL = {'succeeded', 'failed', 'uncertain', 'abandoned'}


def validate(recipe):
    if set(recipe) - {'preparation','verification','reboot_timeout_seconds','outputs','environment'}:
        raise ValueError('Unknown reboot recipe field')
    for phase in ['preparation', 'verification']:
        item = recipe[phase]
        if set(item) != {'command','timeout_seconds'}: raise ValueError('Phase requires command and timeout_seconds')
        validate_job(dict(item, outputs=recipe['outputs'], environment=recipe.get('environment', {})))
    timeout = recipe['reboot_timeout_seconds']
    if type(timeout) is not int or not 60 <= timeout <= 1800:
        raise ValueError('reboot_timeout_seconds must be 60..1800')
    return recipe


def record_path(root, name):
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}', name): raise ValueError('Use a simple workflow name')
    return Path(root)/'reboots'/(name+'.json')


def call(host, record, action):
    remote = record['remote_directory']
    script = 'timeout 100 python3 '+shlex.quote(remote+'/reboot_remote.py')+' '+action+' '+shlex.quote(remote)
    return json.loads(host.command(script, seconds=110).splitlines()[-1])


def read_record(root, name):
    _, config = configuration(root)
    path = record_path(root, name)
    record = json.loads(path.read_text())
    if record['host'] != config: raise ValueError('Reboot workflow host mismatch')
    return path, record, Host(config)


def submit(directory, name, source, recipe, transfer='ssm'):
    validate(recipe)
    source = Path(source).resolve()
    if transfer not in {'ssm','s3'}: raise ValueError('Unknown transfer backend')
    if source.stat().st_size > (2*1024**2 if transfer == 'ssm' else 1024**3):
        raise ValueError('Source exceeds transfer size limit')
    with locked(directory) as root:
        _, config = configuration(root)
        path = record_path(root, name)
        fingerprint = sha(source)
        if path.exists():
            record = json.loads(path.read_text())
            if record['host'] != config or record['source_sha256'] != fingerprint or record['recipe'] != recipe:
                raise ValueError('Workflow name already bound to different source, recipe or host')
        else:
            identity = uuid.uuid4().hex
            record = {'schema':1, 'name':name, 'workflow_id':identity, 'host':config, 'recipe':recipe,
                      'source_sha256':fingerprint, 'remote_directory':'/var/lib/host-deploy/reboots/'+identity,
                      'phase':'staging', 'transfer':transfer,
                      'uptime_limit_seconds':json.loads((root/'launch.json').read_text())['specification']['maximum_uptime_minutes']*60}
            save(path, record)
        host = Host(config)
        remote = record['remote_directory']
        if record['phase'] == 'staging':
            # An older checkpoint may precede successful remote initialization.
            # Never overwrite a remotely initialized workflow, even from stale local state.
            probe = json.loads(host.command(shell_python('import json; from pathlib import Path; p=Path('+repr(remote)+'); print(json.dumps(json.loads((p/"workflow.json").read_text()) if (p/"progress.json").exists() else None))')))
            if probe is not None:
                if any(probe[key] != record[key] for key in ['workflow_id','host','recipe','source_sha256']):
                    raise ValueError('Remote workflow identity differs')
            else:
                host.command('install -d -m 700 '+remote)
                if transfer == 's3':
                    from .bulk import Bulk
                    Bulk(root).send(host, source, remote+'/source.zip', record['workflow_id'])
                else: host.upload(source.read_bytes(), remote+'/source.zip')
                for local, target in [('reboot_remote.py','reboot_remote.py'),('job_worker.py','common.py'),('remote_control.py','control.py')]:
                    host.upload(Path(__file__).with_name(local).read_bytes(), remote+'/'+target)
                host.upload(json.dumps(record).encode(), remote+'/workflow.json')
            record['phase'] = 'initializing'
            save(path, record)
        if record['phase'] == 'initializing':
            record['observed'] = call(host, record, 'initialize')
            record['phase'] = 'submitted'
            save(path, record)
        record['observed'] = call(host, record, 'observe')
        if record['observed']['phase'] == 'ready':
            record['observed'] = call(host, record, 'advance')
        save(path, record)
        return record


def inspect(directory, name):
    with locked(directory) as root:
        path, record, host = read_record(root, name)
        record['observed'] = call(host, record, 'observe')
        save(path, record)
        return record


def resume(directory, name, wait_seconds=900):
    if type(wait_seconds) is not int or not 0 <= wait_seconds <= 3600:
        raise ValueError('wait_seconds must be 0..3600')
    with locked(directory) as root:
        path, record, host = read_record(root, name)
        end = time.monotonic() + wait_seconds
        while True:
            try:
                record['observed'] = call(host, record, 'advance')
                record.pop('connection_error', None)
            except ClientError as error:
                if error.response['Error']['Code'] not in {'InvalidInstanceId','TargetNotConnected','InternalServerError','ThrottlingException'}: raise
                record['connection_error'] = error.response['Error']['Code']
            except (RuntimeError, TimeoutError, EndpointConnectionError, ConnectionClosedError, ReadTimeoutError, ConnectTimeoutError) as error:
                # A reboot can interrupt SSM delivery/replies. Receipt-based advance
                # is safe to repeat; it never repeats a test or reboot dispatch.
                record['connection_error'] = str(error)
            save(path, record)
            if record.get('observed', {}).get('phase') in FINAL or time.monotonic() >= end:
                return record
            time.sleep(min(5, max(0, end-time.monotonic())))


def abandon(directory, name):
    with locked(directory) as root:
        path, record, host = read_record(root, name)
        record['observed'] = call(host, record, 'abandon')
        save(path, record)
        return record


def collect(directory, name, output, transfer='ssm'):
    with locked(directory) as root:
        path, record, host = read_record(root, name)
        record['observed'] = call(host, record, 'observe')
        save(path, record)
        metadata = call(host, record, 'collect')
        output = Path(output)
        if output.exists(): raise ValueError('Output already exists')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name+'.partial')
        remote = record['remote_directory']+'/results.tar.gz'
        if transfer == 'ssm':
            from .transfer import download
            download(host,remote,temporary)
        elif transfer == 's3':
            from .bulk import Bulk
            Bulk(root).receive(host, remote, temporary, record['workflow_id'], metadata)
        else: raise ValueError('Unknown transfer backend')
        if temporary.stat().st_size != metadata['bytes'] or sha(temporary) != metadata['sha256']:
            raise ValueError('Reboot evidence hash/length mismatch')
        with temporary.open('rb') as stream: os.fsync(stream.fileno())
        os.link(temporary, output)
        temporary.unlink()
        descriptor = os.open(output.parent, os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        record.update(result_path=str(output.resolve()), result_sha256=metadata['sha256'])
        save(path, record)
        return record
