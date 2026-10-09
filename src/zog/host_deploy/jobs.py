"""Generic asynchronous jobs. Unknown submission outcomes are never blindly replayed."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import uuid

from .workspace import locked, save
from .provision import configuration, Cloud
from .runner import Host


def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''): result.update(block)
    return result.hexdigest()


def validate(recipe):
    if set(recipe)-{'command','timeout_seconds','outputs','environment','publication'}: raise ValueError('Unknown recipe field')
    if not isinstance(recipe.get('command'),list) or not recipe['command'] or not all(isinstance(s,str) and s and '\x00' not in s for s in recipe['command']): raise ValueError('command must be a nonempty argv list')
    if type(recipe.get('timeout_seconds')) is not int or not 1<=recipe['timeout_seconds']<=23*3600: raise ValueError('timeout_seconds must be 1..82800')
    if not isinstance(recipe.get('outputs'),list): raise ValueError('outputs must be a list of relative paths')
    for name in recipe['outputs']:
        if not isinstance(name,str) or not name or Path(name).is_absolute() or '..' in Path(name).parts: raise ValueError('Unsafe output path')
    environment=recipe.get('environment',{})
    if not isinstance(environment,dict) or not all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',k) and isinstance(v,str) and '\x00' not in v for k,v in environment.items()): raise ValueError('Invalid environment')
    if 'publication' in recipe:
        publication=recipe['publication']
        if set(publication)!={'store','retention_seconds'} or not Path(publication['store']).is_absolute():
            raise ValueError('Publication requires an absolute mounted store path and retention_seconds')
        if type(publication['retention_seconds']) is not int or not 60<=publication['retention_seconds']<=31536000:
            raise ValueError('Invalid publication retention')
    return recipe


def record_path(root,name):
    if not re.fullmatch('[a-zA-Z0-9_-]{1,80}',name): raise ValueError('Use a simple job name')
    return Path(root)/'jobs'/(name+'.json')


def shell_python(code):
    return 'python3 -c '+shlex.quote(code)


def remote_status(host,record):
    code=Path(__file__).with_name('remote_control.py').read_text().split("if __name__ == '__main__':")[0]
    code += '\nprint(json.dumps(status(Path(' + repr(record['remote_directory']) + '), ' + repr(record['unit']) + ')))'
    return json.loads(host.command(shell_python(code)))


def serialized(code):
    return 'flock -w 30 /run/host-deploy-control.lock ' + shell_python(code)


def submit(directory,name,source,recipe,transfer='ssm'):
    validate(recipe)
    source=Path(source).resolve()
    if not source.is_file(): raise ValueError('Source ZIP is required')
    if source.stat().st_size>1024**3: raise ValueError('Source archive exceeds 1 GiB')
    if transfer not in {'ssm','s3'}: raise ValueError('Unknown transfer backend')
    if transfer=='ssm' and source.stat().st_size>2*1024*1024: raise ValueError('Use S3 for sources above 2 MiB')
    with locked(directory) as root:
        workspace,config=configuration(root)
        path=record_path(root,name)
        fingerprint=sha(source)
        if path.exists():
            record=json.loads(path.read_text())
            if record['source_sha256']!=fingerprint or record['recipe']!=recipe or record['host']!=config:
                raise ValueError('Existing job is bound to different inputs or host')
        else:
            identity=uuid.uuid4().hex
            record={'schema':1,'name':name,'job_id':identity,'source_sha256':fingerprint,'recipe':recipe,'host':config,
                    'remote_directory':'/var/lib/host-deploy/jobs/'+identity,'unit':'host-deploy-job-'+identity+'.service',
                    'phase':'prepared','transfer':transfer}
            save(path,record)
        host=Host(config)
        if record['phase'] in {'submitted','submitting','collected','cancelled'}:
            record['observed']=remote_status(host,record)
            save(path,record)
            return record
        remote=record['remote_directory']
        host.command('install -d -m 700 '+remote)
        # Once dispatch starts, inputs are never overwritten through this API.
        if transfer=='s3':
            from .bulk import Bulk
            Bulk(root).send(host,source,remote+'/source.zip',record['job_id'])
        else: host.upload(source.read_bytes(),remote+'/source.zip')
        if host.command('sha256sum '+remote+'/source.zip').split()[0]!=fingerprint: raise ValueError('Remote source hash mismatch')
        host.upload(Path(__file__).with_name('job_worker.py').read_bytes(),remote+'/worker.py')
        if 'publication' in recipe:
            host.upload(Path(__file__).with_name('artifacts.py').read_bytes(),remote+'/artifacts.py')
        host.upload(json.dumps(record).encode(),remote+'/job.json')
        # Bound the job to remaining host uptime, keeping 120 seconds for shutdown.
        limit=json.loads((root/'launch.json').read_text())['specification']['maximum_uptime_minutes']*60
        uptime=float(host.command("cut -d ' ' -f 1 /proc/uptime"))
        if uptime+recipe['timeout_seconds']+120>=limit: raise ValueError('Insufficient remaining host uptime for this job')
        record['phase']='submitting'
        save(path,record)
        control=Path(__file__).with_name('remote_control.py').read_text().split("if __name__ == '__main__':")[0]
        code=control+f'''\nimport json,subprocess,sys,fcntl,os
from pathlib import Path
sys.path.insert(0,{remote!r})
from worker import save
p=Path({remote!r})
if reboot_busy(): raise RuntimeError('Reboot workflow owns this host')
if Path('/run/host-deploy-draining').exists(): raise RuntimeError('Host is draining for shutdown')
with (p/'dispatch.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if (p/'cancel.json').exists(): raise RuntimeError('Job was cancelled')
 if (p/'dispatch.json').exists():
  print('already recorded')
 else:
  save(p/'dispatch.json',{{'job_id':{record['job_id']!r},'state':'submitting'}})
  subprocess.run(['systemd-run','--quiet','--collect','--unit='+{record['unit']!r},'--property=Type=exec','--property=KillMode=control-group','--property=TimeoutStopSec=10','--property=RuntimeMaxSec={recipe['timeout_seconds']+90}','/usr/bin/python3',str(p/'worker.py'),'run',str(p)],check=True)
  save(p/'dispatch.json',{{'job_id':{record['job_id']!r},'state':'submitted'}})
  print('submitted')'''
        host.command(serialized(code))
        record['phase']='submitted'
        save(path,record)
        return record


def inspect(directory,name):
    with locked(directory) as root:
        _,config=configuration(root)
        path=record_path(root,name)
        record=json.loads(path.read_text())
        if record['host']!=config: raise ValueError('Job host mismatch')
        record['observed']=remote_status(Host(config),record)
        save(path,record)
        return record


def collect(directory,name,output,transfer='ssm'):
    with locked(directory) as root:
        _,config=configuration(root)
        path=record_path(root,name)
        record=json.loads(path.read_text())
        if record['host']!=config: raise ValueError('Job host mismatch')
        host=Host(config)
        status=remote_status(host,record)
        if status['state'] not in {'succeeded','failed','timed_out','interrupted','cancelled'} or status['unit_state'] in {'active','activating','deactivating'}:
            raise RuntimeError('Job is not terminal; inspect it again later')
        remote=record['remote_directory']
        # Record interruption diagnosis separately; do not replace original status.
        host.upload(json.dumps(status).encode(),remote+'/observation.json')
        # Cancellation may precede source/worker staging. Supply a separate collector
        # and create the evidence manifest only if dispatch never supplied one.
        host.command(shell_python('from pathlib import Path; p=Path('+repr(remote+'/job.json')+'); '+
            'p.exists() or p.write_text('+repr(json.dumps(record))+')'))
        host.upload(Path(__file__).with_name('job_worker.py').read_bytes(),remote+'/collector.py')
        metadata=json.loads(host.command('python3 '+remote+'/collector.py collect '+remote,seconds=300))
        output=Path(output)
        if output.exists(): raise ValueError('Output already exists')
        output.parent.mkdir(parents=True,exist_ok=True)
        temporary=output.with_name(output.name+'.partial')
        if transfer=='s3':
            from .bulk import Bulk
            Bulk(root).receive(host,remote+'/results.tar.gz',temporary,record['job_id'],metadata)
        elif transfer=='ssm':
            from .transfer import download
            download(host,remote+'/results.tar.gz',temporary)
        else: raise ValueError('Unknown transfer backend')
        if temporary.stat().st_size!=metadata['bytes'] or sha(temporary)!=metadata['sha256']:
            raise ValueError('Collected evidence hash/length mismatch')
        with temporary.open('rb') as stream: os.fsync(stream.fileno())
        os.link(temporary,output)
        temporary.unlink()
        descriptor=os.open(output.parent,os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        record.update(phase='collected',observed=status,result_sha256=metadata['sha256'],result_path=str(output.resolve()))
        save(path,record)
        return record


def cancel(directory, name):
    """Durable cancel intent followed by systemd cgroup termination; retry is safe."""
    with locked(directory) as root:
        _, config = configuration(root)
        path = record_path(root, name)
        record = json.loads(path.read_text())
        if record['host'] != config: raise ValueError('Job host mismatch')
        host = Host(config)
        remote = record['remote_directory']
        # Reconcile a possibly lost cancellation reply through remote evidence.
        record['cancel_requested'] = True
        save(path, record)
        code = Path(__file__).with_name('remote_control.py').read_text().split("if __name__ == '__main__':")[0]
        code += f"""
import os, tempfile, time
root = Path({remote!r})
unit = {record['unit']!r}
root.mkdir(parents=True, exist_ok=True)
value = status(root, unit)
if value['state'] not in TERMINAL or value['unit_state'] in ACTIVE:
 descriptor, temporary = tempfile.mkstemp(dir=root)
 with os.fdopen(descriptor, 'w') as stream:
  json.dump({{'job_id': {record['job_id']!r}, 'requested_at': time.time()}}, stream)
  stream.flush(); os.fsync(stream.fileno())
 os.replace(temporary, root/'cancel.json')
 descriptor = os.open(root, os.O_DIRECTORY)
 os.fsync(descriptor); os.close(descriptor)
 if value['unit_state'] in ACTIVE:
  subprocess.run(['systemctl', 'stop', unit], check=True, timeout=45)
print(json.dumps(status(root, unit)))
"""
        record['observed'] = json.loads(host.command(serialized(code), seconds=90))
        record['phase'] = 'cancelled' if record['observed']['state'] == 'cancelled' else record['phase']
        save(path, record)
        return record


def publish(directory,name):
    with locked(directory) as root:
        _,config=configuration(root)
        record=json.loads(record_path(root,name).read_text())
        if record['host']!=config: raise ValueError('Job host mismatch')
        if 'publication' not in record['recipe']: raise ValueError('Job has no publication target')
        host=Host(config)
        status=remote_status(host,record)
        if status['unit_state'] in {'active','activating','deactivating'}: raise RuntimeError('Job still active')
        remote=record['remote_directory']
        return json.loads(host.command('python3 '+remote+'/worker.py publish '+remote,seconds=300))
