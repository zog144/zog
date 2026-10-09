"""Standalone remote job worker, run as a systemd service on a trusted test VM."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile


def save(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as output:
            json.dump(value,output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary,path)
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): value.update(chunk)
    return value.hexdigest()


def unpack(archive, destination):
    destination.mkdir()
    with zipfile.ZipFile(archive) as source:
        if sum(item.file_size for item in source.infolist()) > 4*1024**3:
            raise ValueError('Expanded source exceeds 4 GiB')
        for item in source.infolist():
            target=(destination/item.filename).resolve()
            if not target.is_relative_to(destination.resolve()) or (item.external_attr>>16)&0o170000 == 0o120000:
                raise ValueError('Unsafe source archive path')
        source.extractall(destination)


def run(root):
    manifest=json.loads((root/'job.json').read_text())
    status_path=root/'status.json'
    # A second invocation of this worker must never execute the command again.
    with (root/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if status_path.exists(): return
        status={'job_id':manifest['job_id'],'state':'running','boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'started_at':time.time(),'source_sha256':manifest['source_sha256']}
        save(status_path,status)
        child=None
        def interrupted(signum, frame):
            raise InterruptedError('Worker received signal '+str(signum))
        signal.signal(signal.SIGTERM,interrupted)
        signal.signal(signal.SIGINT,interrupted)
        try:
            if sha(root/'source.zip') != manifest['source_sha256']: raise ValueError('Source hash mismatch')
            unpack(root/'source.zip',root/'source')
            environment=os.environ.copy()
            environment.update(manifest['recipe'].get('environment',{}))
            with (root/'output.log').open('wb') as output:
                child=subprocess.Popen(manifest['recipe']['command'],cwd=root/'source',env=environment,
                    stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    code=child.wait(timeout=manifest['recipe']['timeout_seconds'])
                    status.update(state='succeeded' if code==0 else 'failed',return_code=code)
                except subprocess.TimeoutExpired:
                    status['state']='timed_out'
        except Exception as error:
            status.update(state='interrupted' if isinstance(error,InterruptedError) else 'failed',error=str(error))
        finally:
            if child is not None:
                # Also drain descendants after a shell exits successfully.
                try: os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
            status['finished_at']=time.time()
            save(status_path,status)
            if 'publication' in manifest['recipe']:
                publish_result(root)


def collect(root):
    manifest=json.loads((root/'job.json').read_text())
    source=root/'source'
    destination=root/'results.tar.gz'
    if destination.exists():
        return {'bytes':destination.stat().st_size,'sha256':sha(destination)}
    with tarfile.open(destination.with_suffix('.partial'),'w:gz',dereference=False) as archive:
        for name in ['job.json','status.json','observation.json','output.log']:
            if (root/name).exists(): archive.add(root/name,arcname=name)
        for name in manifest['recipe']['outputs']:
            path=source/name
            if path.exists() and path.resolve().is_relative_to(source.resolve()):
                archive.add(path,arcname='outputs/'+name)
    os.replace(destination.with_suffix('.partial'),destination)
    return {'bytes':destination.stat().st_size,'sha256':sha(destination)}


def publish_result(root):
    try:
        try: from .artifacts import publish
        except ImportError: from artifacts import publish
        manifest=json.loads((root/'job.json').read_text())
        settings=manifest['recipe']['publication']
        artifact=root/'publication.tar.gz'
        if not artifact.exists():
            collect(root)
            os.link(root/'results.tar.gz',artifact)
        receipt=publish(artifact,settings['store'],manifest['job_id'],settings['retention_seconds'],
                        {'source_sha256':manifest['source_sha256'],'outcome':json.loads((root/'status.json').read_text())})
        result={'state':'published','receipt':receipt}
    except Exception as error:
        result={'state':'publication_failed','error':str(error)}
    save(root/'publication.json',result)
    return result


if __name__ == '__main__':
    action, directory=sys.argv[1:3]
    root=Path(directory)
    if action=='run': run(root)
    elif action=='collect': print(json.dumps(collect(root)))
    elif action=='publish': print(json.dumps(publish_result(root)))
