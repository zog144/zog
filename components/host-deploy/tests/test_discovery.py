import json
from unittest.mock import Mock
import pytest
from zog.host_deploy import discovery
from zog.host_deploy.beacon_install import candidate, IDENTITY, CREDENTIALS

CLOUD=dict(account_id='123456789012',region='us-east-1',instance_id='i-0123456789abcdef0')
SERVER='https://registry.example.test'
REGISTRY='i-0fedcba9876543210'
HOST='7379d8d3-257e-4f96-a1ef-7db62c814a81'
def request(**kw):return dict(cloud=CLOUD,settings={},server=None,migrate=False,system_ca=False,**kw)

def test_migrate_bearer_preserves_identity_and_requires_opt_in():
    old=dict(provider='aws',cloud=CLOUD,host_id=HOST,token='secret',server=SERVER)
    with pytest.raises(ValueError,match='--migrate'):candidate(old,request())
    r=request();r['migrate']=True;r['system_ca']=True
    old['ca_file']='/old.pem'
    c=candidate(old,r)
    assert c['host_id']==HOST and 'token' not in c and 'ca_file' not in c
    assert c['identity_directory']==IDENTITY and c['credential_directory']==CREDENTIALS

def test_signed_reinstall_preserves_custom_trust_and_role_settings():
    old=dict(provider='aws',cloud=CLOUD,host_id=HOST,server=SERVER,ca_file='/old.pem',mirror_box_control={'project':'/project'},station_login_file=IDENTITY+'/station-login.json')
    assert candidate(old,request())['mirror_box_control']==old['mirror_box_control']
    assert candidate(old,request())['ca_file']=='/old.pem'
    r=request();r['settings']={'mirror_box_control':{}}
    with pytest.raises(ValueError):candidate(old,r)

def test_identity_and_path_guards():
    with pytest.raises(ValueError):candidate({'cloud':{},'provider':'aws'},request())
    r=request();r['settings']={'token':'secret'}
    with pytest.raises(ValueError):candidate({},r)
    r['settings']={'identity_directory':'/copied'}
    with pytest.raises(ValueError):candidate({},r)
    r['settings']={'server':'http://bad'}
    with pytest.raises(ValueError):candidate({},r)

def test_fresh_explicit_server_has_no_archive_grant_or_bridge():
    r=request();r["server"]=SERVER
    c=candidate({},r)
    assert c['server']==SERVER
    assert not {'host_id','token','mirror_box_control','archive_mirror'} & c.keys()

def fake(tmp_path,monkeypatch):
    remote=Mock()
    remote.command.return_value=json.dumps(dict(server=SERVER,host_id=None,fingerprint='sha256:public',enrollment='pending',heartbeat='pending',daemon='installed'))
    monkeypatch.setattr(discovery,'owned_host',lambda _:({},CLOUD,remote))
    return remote

def test_requires_server_gate_before_remote(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='server-ready'):discovery.install(tmp_path/'w')
    remote.command.assert_not_called()

def test_pending_install_and_repeat_do_not_approve_or_download_secrets(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch)
    for _ in range(2):
        result=discovery.install(tmp_path/'w',server_ready=True)
        assert result['heartbeat']=='pending'
    receipt=json.loads((tmp_path/'w/host-discover-install.json').read_text())
    assert receipt['enrollment']=='pending' and 'token' not in receipt
    remote.download.assert_not_called()
    commands='\n'.join(c.args[0] for c in remote.command.call_args_list)
    assert 'enroll_host' not in commands and 'approve' not in commands
    assert 'Python 3.12 required' in commands

def test_preflight_failure_never_uploads(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch);remote.command.side_effect=RuntimeError('no interpreter')
    with pytest.raises(RuntimeError):discovery.install(tmp_path/'w',server_ready=True)
    remote.upload.assert_not_called()

def test_service_controls(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch);remote.command.return_value='ActiveState=active\n'
    assert discovery.service(tmp_path/'w','status')['service']['ActiveState']=='active'
    discovery.service(tmp_path/'w','stop')
    assert any('disable --now' in c.args[0] for c in remote.command.call_args_list)

def test_legacy_receipt_requires_migration_and_preserves_expected_uuid(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch);directory=tmp_path/'w';directory.mkdir()
    registry={'instance_id':REGISTRY}
    monkeypatch.setattr(discovery,'configuration',lambda _:({},registry))
    (directory/'host-discover-install.json').write_text(json.dumps({'phase':'installed','host_id':HOST,'registry_instance_id':registry['instance_id']}))
    with pytest.raises(ValueError,match='Legacy receipt requires'):discovery.install(directory,server_ready=True)
    remote.upload.assert_not_called()
    discovery.install(directory,server_ready=True,migrate=True,registry_directory=tmp_path/'registry')
    requests=[json.loads(call.args[0]) for call in remote.upload.call_args_list if call.args[1].endswith('/request.json')]
    assert requests[0]['expected_host_id']==HOST and requests[0]['cloud']==CLOUD

def test_present_conflicting_receipt_cloud_is_never_accepted(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch);directory=tmp_path/'w';directory.mkdir()
    (directory/'host-discover-install.json').write_text(json.dumps({'host_id':HOST,'account_id':'999999999999'}))
    with pytest.raises(ValueError,match='receipt target mismatch'):discovery.install(directory,server_ready=True,migrate=True)
    remote.upload.assert_not_called()

def test_remote_candidate_rejects_legacy_uuid_or_cloud_substitution():
    old=dict(provider='aws',cloud=CLOUD,host_id=HOST,token='test-only',server=SERVER)
    r=request(expected_host_id='00000000-0000-0000-0000-000000000001');r['migrate']=True
    with pytest.raises(ValueError,match='UUID differs'):candidate(old,r)
    r['expected_host_id']=HOST;r['cloud']=dict(CLOUD,account_id='999999999999')
    with pytest.raises(ValueError,match='cloud identity mismatch'):candidate(old,r)

def test_missing_pinned_source_never_contacts_host(tmp_path, monkeypatch):
    owned = Mock()
    monkeypatch.setattr(discovery, 'owned_host', owned)
    with pytest.raises(ValueError, match='Missing pinned'):
        discovery.install(tmp_path/'workspace', source=tmp_path/'missing', server_ready=True)
    owned.assert_not_called()


def test_installer_probe_with_canonical_beacon_pending_binding_and_heartbeat(tmp_path, monkeypatch, capsys):
    """Run the actual remote probe against the selected beacon without network access."""
    import sys
    import uuid
    from zog.host_deploy.beacon_install import PROBE
    from zog.host_identify import storage, signatures
    private = tmp_path/'identity'; private.mkdir(mode=0o700)
    shared = tmp_path/'credentials'; shared.mkdir(mode=0o750)
    config = tmp_path/'configuration.json'
    config.write_text(json.dumps(dict(server='https://registry.example.test',
        identity_directory=str(private), credential_directory=str(shared), provider='generic')))
    fingerprint = signatures.fingerprint(storage.load_key(private).public_key())
    host = str(uuid.uuid4())
    responses = iter([
        {'status':'pending','fingerprint':fingerprint},
        {'status':'approved','fingerprint':fingerprint,'host_id':host},
        {'version':2,'host_id':host,'archive':None},
    ])
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, maximum): return json.dumps(next(responses)).encode()[:maximum]
    monkeypatch.setattr('urllib.request.OpenerDirector.open', lambda *args, **kwargs: Response())
    monkeypatch.setattr(sys, 'argv', ['probe', str(config)])
    for state in ['pending', 'binding-received', 'signed-accepted']:
        exec(compile(PROBE, '<remote-beacon-probe>', 'exec'), {})
        result = json.loads(capsys.readouterr().out)
        assert result['heartbeat'] == state
        assert result['fingerprint'] == fingerprint
        assert result['archive_access'] == 'not-granted'


def test_no_implicit_server_and_explicit_precedence():
    with pytest.raises(ValueError,match='explicit HTTPS server'):
        candidate({},request())
    r=request();r['settings']={'server':SERVER}
    assert candidate({},r)['server']==SERVER
    r['server']='https://override.example.test/'
    assert candidate({},r)['server']=='https://override.example.test'
    old=dict(provider='aws',cloud=CLOUD,server=SERVER)
    assert candidate(old,request())['server']==SERVER
    with pytest.raises(ValueError,match='--migrate'):candidate(old,r)


@pytest.mark.parametrize('settings',[[],{'password':'secret'},{'private_key':'secret'},{'server':''},{'server':'http://bad'},{'server':'https://registry.example.test:bad'},{'server':'https://bad host'}])
def test_invalid_configuration_rejected_before_host_contact(tmp_path,monkeypatch,settings):
    owned=Mock();monkeypatch.setattr(discovery,'owned_host',owned)
    config=tmp_path/'configuration.json';config.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        discovery.install(tmp_path/'w',configuration_file=config,server_ready=True)
    owned.assert_not_called()


def test_configuration_loaded_only_when_explicitly_selected(tmp_path):
    config=tmp_path/'configuration.json';config.write_text(json.dumps({'server':SERVER}))
    assert discovery.installer_settings()==({},None)
    assert discovery.installer_settings(config)==({'server':SERVER},None)


def test_bound_migration_requires_explicit_matching_registry(tmp_path,monkeypatch):
    remote=fake(tmp_path,monkeypatch);directory=tmp_path/'w';directory.mkdir()
    (directory/'host-discover-install.json').write_text(json.dumps(CLOUD|{'host_id':HOST,'registry_instance_id':REGISTRY}))
    with pytest.raises(ValueError,match='same command center'):
        discovery.install(directory,server_ready=True,migrate=True)
    monkeypatch.setattr(discovery,'configuration',lambda _:({}, {'instance_id':'i-other'}))
    with pytest.raises(ValueError,match='same command center'):
        discovery.install(directory,registry_directory='explicit',server_ready=True,migrate=True)
    remote.upload.assert_not_called()


def test_fresh_install_does_not_read_registry_workspace(tmp_path,monkeypatch):
    fake(tmp_path,monkeypatch)
    monkeypatch.setattr(discovery,'configuration',Mock(side_effect=AssertionError('implicit workspace read')))
    discovery.install(tmp_path/'w',server=SERVER,server_ready=True)
    receipt=json.loads((tmp_path/'w/host-discover-install.json').read_text())
    assert receipt['registry_instance_id'] is None
