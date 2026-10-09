import io
from pathlib import Path
import shlex
from types import SimpleNamespace

from zog.host_deploy.bulk import Bulk


def test_bulk_transfer_streams_bytes_without_persisting_url(tmp_path,monkeypatch):
    import urllib.request
    import subprocess
    objects={}
    active={}
    class S3:
        def upload_file(self,path,bucket,key): objects[key]=Path(path).read_bytes()
        def download_file(self,bucket,key,path): Path(path).write_bytes(objects[key])
        def generate_presigned_url(self,operation,Params,ExpiresIn):
            assert ExpiresIn==900
            active['key']=Params['Key']
            return 'https://example.invalid/transfer?token=synthetic'
    class LocalHost:
        def command(self,script,seconds):
            arguments=shlex.split(script)
            exec(compile(arguments[2],'<transfer>','exec'),{})
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:io.BytesIO(objects[active['key']]))
    def curl(arguments):
        config=Path(arguments[arguments.index('--config')+1])
        assert config.stat().st_mode & 0o777 == 0o600
        assert 'synthetic' in config.read_text()
        objects[active['key']]=Path(arguments[-1]).read_bytes()
        active['config']=config
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess,'run',curl)
    bulk=Bulk.__new__(Bulk)
    bulk.bucket='bucket'
    bulk.prefix='workspace/'
    bulk.s3=S3()
    original=tmp_path/'original'
    original.write_bytes(bytes(range(256))*12000)
    remote=tmp_path/'remote'
    bulk.send(LocalHost(),original,str(remote),'job')
    assert remote.read_bytes()==original.read_bytes()
    output=tmp_path/'collected'
    try:
        bulk.receive(LocalHost(),str(remote),output,'job')
    except SystemExit as exit:
        # The remote python process normally exits here; emulate its shell exit.
        assert exit.code==0
        bulk.s3.download_file(bulk.bucket,active['key'],str(output))
    assert output.read_bytes()==original.read_bytes()
    assert not active['config'].exists()
