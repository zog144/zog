import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from zog.host_deploy import bulk
from zog.host_deploy.workspace import initialize, save


def setup_storage(tmp_path, monkeypatch):
    root=tmp_path/'workspace'
    workspace=initialize(root,'test','profile','us-east-1')
    objects={}
    class S3:
        def head_bucket(self, **kwargs): return {'BucketRegion':'us-east-1'}
        def get_paginator(self, name):
            return SimpleNamespace(paginate=lambda **kw:[{'Contents':[{'Key':k} for k in objects if k.startswith(kw['Prefix'])]}])
        def get_object(self, **kwargs): return {'Body':io.BytesIO(objects[kwargs['Key']])}
        def download_file(self,bucket,key,path): Path(path).write_bytes(objects[key])
        def delete_object(self, **kwargs): objects.pop(kwargs['Key'],None)
        def delete_bucket(self, **kwargs): raise AssertionError('Shared bucket deleted')
    s3=S3()
    monkeypatch.setattr(bulk,'Cloud',lambda workspace:SimpleNamespace(account=lambda:'123'))
    monkeypatch.setattr(bulk.boto3,'Session',lambda **kw:SimpleNamespace(client=lambda *a,**k:s3))
    return root,workspace,objects,s3


def test_auto_attach_and_scoped_cleanup(tmp_path,monkeypatch):
    root,w,objects,s3=setup_storage(tmp_path,monkeypatch)
    client=bulk.Bulk(root)
    assert client.bucket=='zog-host-deploy-1'
    objects[client.prefix+'job/source.zip']=b'ours'
    objects['another-workspace/job/source.zip']=b'theirs'
    bulk.delete(root)
    assert objects=={'another-workspace/job/source.zip':b'theirs'}
    with pytest.raises(ValueError,match='not ready'): bulk.Bulk(root)


def test_verified_fetch_without_host_and_no_overwrite(tmp_path,monkeypatch):
    root,w,objects,s3=setup_storage(tmp_path,monkeypatch)
    client=bulk.Bulk(root)
    source=tmp_path/'source'; source.write_bytes(b'evidence')
    key=client.prefix+'job/results.tar.gz'
    receipt=bulk.digest(source)|{'schema':1,'job_id':'job','key':key}
    objects[key]=source.read_bytes()
    objects[client.prefix+'job/receipt.json']=json.dumps(receipt).encode()
    source.unlink()
    assert bulk.results(root)['results']==['job']
    output=tmp_path/'result'
    bulk.fetch(root,'job',output)
    assert output.read_bytes()==b'evidence'
    with pytest.raises(FileExistsError): bulk.fetch(root,'job',output)
    objects[key]=b'corrupt'
    with pytest.raises(ValueError,match='hash/length'): bulk.fetch(root,'job',tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
    receipt['key']='another-workspace/job/results.tar.gz'
    objects[client.prefix+'job/receipt.json']=json.dumps(receipt).encode()
    with pytest.raises(ValueError,match='receipt'): bulk.fetch(root,'job',tmp_path/'bad')
    with pytest.raises(ValueError,match='identifier'): bulk.fetch(root,'../other',tmp_path/'bad')


def test_attach_refuses_rebinding(tmp_path,monkeypatch):
    root,w,objects,s3=setup_storage(tmp_path,monkeypatch)
    bulk.attach(root)
    with pytest.raises(ValueError,match='already'): bulk.attach(root,'different')
