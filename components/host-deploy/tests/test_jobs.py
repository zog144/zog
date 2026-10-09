import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

import pytest
from zog.host_deploy.jobs import validate,sha
from zog.host_deploy.job_worker import run,collect,unpack


def prepare(root,command,timeout=5):
    root.mkdir()
    with zipfile.ZipFile(root/'source.zip','w') as source:
        source.writestr('input','hello')
    (root/'job.json').write_text(json.dumps({'job_id':uuid.uuid4().hex,'source_sha256':sha(root/'source.zip'),
        'recipe':{'command':command,'timeout_seconds':timeout,'outputs':['result']}}))


def test_worker_executes_once_and_preserves_failure(tmp_path):
    root=tmp_path/'job'
    prepare(root,[sys.executable,'-c',"from pathlib import Path; Path('result').write_text('once'); raise SystemExit(3)"])
    run(root)
    first=json.loads((root/'status.json').read_text())
    run(root)
    assert json.loads((root/'status.json').read_text())==first
    assert first['state']=='failed' and first['return_code']==3
    evidence=collect(root)
    assert evidence['sha256']==sha(root/'results.tar.gz')


def test_worker_timeout_is_distinct(tmp_path):
    root=tmp_path/'job'
    prepare(root,[sys.executable,'-c','import time; time.sleep(10)'],timeout=1)
    run(root)
    assert json.loads((root/'status.json').read_text())['state']=='timed_out'


def test_worker_rejects_corrupt_source_before_command(tmp_path):
    root=tmp_path/'job'
    prepare(root,[sys.executable,'-c',"raise RuntimeError('should not run')"])
    (root/'source.zip').write_bytes(b'corrupt')
    run(root)
    result=json.loads((root/'status.json').read_text())
    assert result['state']=='failed' and 'hash mismatch' in result['error']


def test_zip_traversal_rejected(tmp_path):
    archive=tmp_path/'source.zip'
    with zipfile.ZipFile(archive,'w') as source: source.writestr('../outside','bad')
    with pytest.raises(ValueError,match='Unsafe'): unpack(archive,tmp_path/'source')
    assert not (tmp_path/'outside').exists()


def test_recipe_cannot_collect_parent_paths():
    with pytest.raises(ValueError,match='Unsafe'):
        validate({'command':['true'],'timeout_seconds':10,'outputs':['../etc']})


def test_collect_cancelled_job_before_worker_staging(tmp_path, monkeypatch):
    from zog.host_deploy import jobs
    from zog.host_deploy.workspace import save
    root = tmp_path/'workspace'
    remote = tmp_path/'remote'
    remote.mkdir()
    config = {'instance_id':'i-test'}
    record = {'name':'early', 'job_id':uuid.uuid4().hex, 'host':config,
              'remote_directory':str(remote), 'phase':'cancelled',
              'recipe':{'command':['true'],'timeout_seconds':5,'outputs':[]}}
    save(root/'jobs/early.json', record)
    monkeypatch.setattr(jobs, 'configuration', lambda root: ({}, config))
    monkeypatch.setattr(jobs, 'remote_status', lambda *a: {'state':'cancelled', 'unit_state':'inactive'})
    class LocalHost:
        def __init__(self, config): pass
        def upload(self, data, name): Path(name).write_bytes(data)
        def download(self, name): return Path(name).read_bytes()
        def command(self, command, **kwargs):
            return subprocess.check_output(command, shell=True, text=True).strip()
    monkeypatch.setattr(jobs, 'Host', LocalHost)
    output = tmp_path/'cancelled.tar.gz'
    result = jobs.collect(root, 'early', output)
    assert result['phase'] == 'collected'
    assert result['result_sha256'] == jobs.sha(output)
    import tarfile
    with tarfile.open(output) as archive:
        assert json.load(archive.extractfile('observation.json'))['state'] == 'cancelled'
        assert json.load(archive.extractfile('job.json'))['job_id'] == record['job_id']


def test_collection_freezes_bytes_for_transfer_resume(tmp_path):
    root=tmp_path/'job'
    prepare(root,[sys.executable,'-c',"from pathlib import Path; Path('result').write_text('first')"])
    run(root)
    first=collect(root)
    (root/'source/result').write_text('subsequent external change')
    assert collect(root)==first
