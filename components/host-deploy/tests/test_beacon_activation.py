import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from zog.host_deploy import beacon_install as b

@pytest.fixture
def target(tmp_path,monkeypatch):
    base=tmp_path/'opt';base.mkdir()
    cfg=tmp_path/'etc/configuration.json';cfg.parent.mkdir()
    unit=tmp_path/'system/host-discover.service';unit.parent.mkdir()
    ident=tmp_path/'state/identity';cred=tmp_path/'state/credentials'
    monkeypatch.setattr(b,'BASE',base);monkeypatch.setattr(b,'CONFIG',cfg);monkeypatch.setattr(b,'UNIT',unit)
    monkeypatch.setattr(b,'IDENTITY',str(ident));monkeypatch.setattr(b,'CREDENTIALS',str(cred))
    monkeypatch.setattr(b,'safe_path',lambda _:None)
    def directories():
        ident.mkdir(parents=True,exist_ok=True);cred.mkdir(exist_ok=True)
        return SimpleNamespace(pw_gid=0)
    monkeypatch.setattr(b,'state_directories',directories)
    monkeypatch.setattr(b.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    release=base/'release';release.mkdir()
    template=release/'deployment/signed-identity';template.mkdir(parents=True)
    (template/'host-discover.service').write_text('ExecStart=/opt/host-discover/venv/bin/host-discover\n')
    old={'server':'https://registry.test','cloud':{'account_id':'1','instance_id':'i-1','region':'r'},'provider':'aws','host_id':'7379d8d3-257e-4f96-a1ef-7db62c814a81','token':'legacy-secret'}
    cfg.write_text(json.dumps(old));unit.write_text('old-unit')
    request={'cloud':old['cloud'],'migrate':True,'system_ca':True,'python':'python3.12','expected_host_id':old['host_id']}
    calls=[]
    def run(args,**kw):
        calls.append(args)
        if '--fingerprint' in args:
            key=ident/'identity.pem'
            if not key.exists():key.write_text('preserved-key')
            return 'public-fingerprint'
        if '-c' in args and b.PROBE in args:return json.dumps({'host_id':old['host_id'],'enrollment':'pending','heartbeat':'pending'})
        return ''
    monkeypatch.setattr(b,'run',run)
    return request,release,cfg,unit,ident,calls,run

def test_staging_failure_keeps_old_service_and_configuration(target,monkeypatch):
    req,release,cfg,unit,ident,calls,run=target
    before=cfg.read_bytes()
    def fail(args,**kw):
        if 'pip' in args:raise RuntimeError('dependency unavailable')
        return run(args,**kw)
    monkeypatch.setattr(b,'run',fail)
    with pytest.raises(RuntimeError):b.install(req,release)
    assert cfg.read_bytes()==before and unit.read_text()=='old-unit'
    assert not any('systemctl' in a for a in calls)

def test_failed_probe_restores_old_config_and_preserves_key(target,monkeypatch):
    req,release,cfg,unit,ident,calls,run=target;before=cfg.read_bytes()
    def fail(args,**kw):
        if b.PROBE in args:raise RuntimeError('TLS unavailable')
        return run(args,**kw)
    monkeypatch.setattr(b,'run',fail)
    with pytest.raises(RuntimeError):b.install(req,release)
    assert cfg.read_bytes()==before and unit.read_text()=='old-unit'
    assert (ident/'identity.pem').read_text()=='preserved-key'

def test_reinstall_twice_preserves_key_role_and_claim(target):
    req,release,cfg,unit,ident,calls,run=target
    first=b.install(req,release)
    (ident/'mirror-role.json').write_text('durable-request-id')
    second=b.install(req,release)
    assert first['fingerprint']==second['fingerprint']=='public-fingerprint'
    assert first['heartbeat']==second['heartbeat']=='pending'
    assert (ident/'mirror-role.json').read_text()=='durable-request-id'
    assert (ident/'identity.pem').read_text()=='preserved-key'
    assert 'token' not in json.loads(cfg.read_text())
    stops=[i for i,a in enumerate(calls) if a[:2]==['systemctl','stop']]
    probes=[i for i,a in enumerate(calls) if b.PROBE in a]
    assert all(s<p for s,p in zip(stops,probes))
    assert str(release/'venv') in unit.read_text()
