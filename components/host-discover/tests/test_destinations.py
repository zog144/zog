import json
from pathlib import Path
from unittest.mock import patch
import pytest
from zog.host_discover.destinations import configurations,withdraw
from zog.host_identify import storage,signatures


def prepare(tmp_path):
    tmp_path.chmod(0o700)
    identity=tmp_path/'identity';identity.mkdir(mode=0o700)
    credentials=tmp_path/'credentials';credentials.mkdir(mode=0o750)
    base=dict(server='https://primary.test',host_id='7379d8d3-257e-4f96-a1ef-7db62c814a81',identity_directory=str(identity),credential_directory=str(credentials),station_login_file='/private/password',mirror_box_control={'command':'private-adapter'},archive_mirror='https://mirror.test',archive_issuer='issuer',archive_audience='audience')
    path=tmp_path/'destinations.json'
    rows=[dict(id=str(i),label='Registry',server=server,enabled=True,revision=1,ca_certificate='') for i,server in enumerate(['https://primary.test','https://secondary.test'])]
    storage.atomic(path,json.dumps(dict(version=1,destinations=rows)).encode())
    return base,path,rows


def test_isolated_keys_binding_and_authority_survive_reinstall(tmp_path):
    base,path,rows=prepare(tmp_path)
    primary_key=storage.load_key(base['identity_directory'])
    pairs=configurations(base,path);primary=pairs[0][1];secondary=pairs[1][1]
    assert primary['identity_directory']==base['identity_directory'] and primary['host_id']==base['host_id']
    assert secondary['observer_only']
    for field in ['host_id','station_login_file','mirror_box_control','archive_mirror','archive_issuer','archive_audience']:assert field not in secondary
    key=storage.load_key(secondary['identity_directory']);fingerprint=signatures.fingerprint(key.public_key())
    assert fingerprint!=signatures.fingerprint(primary_key.public_key())
    repeated=configurations(base,path)[1][1]
    assert fingerprint==signatures.fingerprint(storage.load_key(repeated['identity_directory']).public_key())
    assert Path(secondary['identity_directory']).stat().st_mode&0o777==0o700
    assert Path(secondary['credential_directory']).stat().st_mode&0o777==0o750


def test_validate_whole_list_before_state_and_no_primary_omission(tmp_path):
    base,path,rows=prepare(tmp_path)
    for bad in [rows[1:],rows+rows[:1],[rows[0],rows[1]|{'server':'http://unsafe.test'}],[rows[0],rows[1]|{'ca_certificate':'invalid'}]]:
        storage.atomic(path,json.dumps(dict(version=1,destinations=bad)).encode())
        with pytest.raises(ValueError):configurations(base,path)
        assert not (Path(base['identity_directory'])/'primary-origin.json').exists()


def test_origin_change_requires_migration_and_file_permissions(tmp_path):
    base,path,rows=prepare(tmp_path);configurations(base,path)
    with pytest.raises(ValueError,match='origin changed'):configurations(base|{'server':'https://secondary.test'},path)
    path.chmod(0o644)
    with pytest.raises(PermissionError):configurations(base,path)


def test_disabled_secondary_clears_without_controller_action(tmp_path):
    base,path,rows=prepare(tmp_path);secondary=configurations(base,path)[1][1]
    with patch('zog.host_identify.storage.clear_credentials') as clear,patch('zog.host_discover.roles.Controller') as controller:
        withdraw(secondary);clear.assert_called_once_with(secondary['credential_directory']);controller.assert_not_called()


def test_secondary_signed_report_omits_password_and_roles(tmp_path):
    from zog.host_discover.daemon import announce
    base,path,rows=prepare(tmp_path);secondary=configurations(base,path)[1][1]
    key=storage.load_key(secondary['identity_directory']);host='7379d8d3-257e-4f96-a1ef-7db62c814a81'
    storage.atomic(Path(secondary['identity_directory'])/'binding.json',json.dumps({'host_id':host,'fingerprint':signatures.fingerprint(key.public_key())}).encode())
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'version':2,'host_id':host,'archive':{'untrusted':'ignored'},'mirror_roles':{'untrusted':'ignored'}}).encode()
    class Opener:
        def open(self,request,**kwargs):
            payload=json.loads(request.data)
            assert 'station_login' not in payload and 'mirror_status' not in payload
            return Response()
    with patch('urllib.request.build_opener',return_value=Opener()),patch('zog.host_discover.roles.Controller.tick') as tick:
        announce(secondary,{'hostname':'reported'});tick.assert_not_called()
    assert not (Path(secondary['credential_directory'])/'archive.json').exists()
