import json
import os
from pathlib import Path
import pytest
from zog.host_deploy import artifacts
from zog.host_deploy.job_worker import run,publish_result
from test_jobs import prepare


def test_interrupted_publication_reuses_chunks_and_hides_partial(tmp_path,monkeypatch):
    store=tmp_path/'store'; artifacts.initialize(store)
    source=tmp_path/'data'; source.write_bytes(os.urandom(artifacts.CHUNK*2+7))
    original=artifacts.Store.put; count=[]
    def broken(self,path,data):
        original(self,path,data); count.append(path)
        if len(count)==1: raise TimeoutError('lost reply')
    monkeypatch.setattr(artifacts.Store,'put',broken)
    with pytest.raises(TimeoutError): artifacts.publish(source,store,'one')
    assert not (store/'artifacts/one/published.json').exists()
    first=count[0]; stamp=first.stat().st_mtime_ns
    monkeypatch.setattr(artifacts.Store,'put',original)
    receipt=artifacts.publish(source,store,'one')
    assert first.stat().st_mtime_ns==stamp
    source.unlink()
    artifacts.fetch(store,'one',tmp_path/'recovered')
    assert (tmp_path/'recovered').stat().st_size==receipt['binding']['bytes']


def test_changed_input_rejected_and_expiry_does_not_resurrect(tmp_path):
    store=tmp_path/'store'; artifacts.initialize(store)
    source=tmp_path/'data'; source.write_bytes(b'original')
    receipt=artifacts.publish(source,store,'one',60)
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='bound'): artifacts.publish(source,store,'one',60)
    assert artifacts.prune(store,receipt['expires_at']+1)==['one']
    with pytest.raises(ValueError,match='pruned'): artifacts.publish(source,store,'one',60)


def test_fetch_repairs_partial_and_rejects_corrupt_store(tmp_path):
    store=tmp_path/'store'; artifacts.initialize(store)
    source=tmp_path/'data'; source.write_bytes(b'correct'*100)
    receipt=artifacts.publish(source,store,'one')
    (tmp_path/'out.partial').write_bytes(b'wrong'*140)
    artifacts.fetch(store,'one',tmp_path/'out')
    assert (tmp_path/'out').read_bytes()==source.read_bytes()
    chunk=next((store/'artifacts/one').glob('0-*')); chunk.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='corrupted'): artifacts.fetch(store,'one',tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_worker_publication_failure_preserves_job_and_retries_without_execution(tmp_path):
    import sys
    root=tmp_path/'job'; store=tmp_path/'store'
    prepare(root,[sys.executable,'-c',"from pathlib import Path; Path('result').write_text('once')"])
    manifest=json.loads((root/'job.json').read_text())
    manifest['recipe']['publication']={'store':str(store),'retention_seconds':60}
    (root/'job.json').write_text(json.dumps(manifest))
    run(root)
    before=json.loads((root/'status.json').read_text())
    assert before['state']=='succeeded'
    assert json.loads((root/'publication.json').read_text())['state']=='publication_failed'
    artifacts.initialize(store)
    assert publish_result(root)['state']=='published'
    assert json.loads((root/'status.json').read_text())==before
    import shutil
    shutil.rmtree(root)
    artifacts.fetch(store,manifest['job_id'],tmp_path/'result.tar.gz')
    assert (tmp_path/'result.tar.gz').exists()
