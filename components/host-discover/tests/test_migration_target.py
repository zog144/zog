import json,uuid,time
from pathlib import Path
from unittest.mock import patch
import pytest
from zog.host_identify import signatures,storage
from zog.host_discover.daemon import announce,MigrationBindingError
from test_signed_daemon import configuration,Response


def binding(configuration,host):
    root=Path(configuration['identity_directory']);key=storage.load_key(root)
    value={'host_id':host,'fingerprint':signatures.fingerprint(key.public_key())}
    storage.atomic(root/'binding.json',json.dumps(value).encode());return value


def test_wrong_approval_response_preserves_key_and_does_not_bind(configuration):
    root=Path(configuration['identity_directory']);key=storage.load_key(root);before=(root/'identity.pem').read_bytes()
    configuration['host_id']=str(uuid.uuid4())
    response={'status':'approved','fingerprint':signatures.fingerprint(key.public_key()),'host_id':str(uuid.uuid4())}
    with patch('urllib.request.OpenerDirector.open',return_value=Response(response)):
        with pytest.raises(MigrationBindingError):announce(configuration,{'version':1})
    assert not (root/'binding.json').exists();assert (root/'identity.pem').read_bytes()==before


def test_existing_misbinding_blocks_posts_and_clears_grant(configuration):
    wrong=binding(configuration,str(uuid.uuid4()));configuration['host_id']=str(uuid.uuid4())
    credentials=Path(configuration['credential_directory']);storage.atomic(credentials/'archive.json',json.dumps({'expires_at':int(time.time())+100}).encode(),0o640)
    with patch('urllib.request.OpenerDirector.open') as network,patch('zog.host_discover.roles.Controller.tick') as role:
        with pytest.raises(MigrationBindingError):announce(configuration,{'version':1})
        network.assert_not_called();role.assert_called_once_with(withdraw=True)
    assert json.loads((Path(configuration['identity_directory'])/'binding.json').read_bytes())==wrong
    assert not (credentials/'archive.json').exists()


def test_correct_migration_binding_remains_usable(configuration):
    host=str(uuid.uuid4());saved=binding(configuration,host);configuration['host_id']=host
    with patch('urllib.request.OpenerDirector.open',return_value=Response({'version':2,'host_id':host,'archive':None})) as network:
        announce(configuration,{'version':1})
    assert '/'+host+'/heartbeat/' in network.call_args.args[0].full_url
    assert json.loads((Path(configuration['identity_directory'])/'binding.json').read_bytes())==saved


def test_matching_migration_approval_is_saved(configuration):
    root=Path(configuration['identity_directory']);key=storage.load_key(root);configuration['host_id']=str(uuid.uuid4())
    response={'status':'approved','fingerprint':signatures.fingerprint(key.public_key()),'host_id':configuration['host_id']}
    with patch('urllib.request.OpenerDirector.open',return_value=Response(response)):announce(configuration,{'version':1})
    assert json.loads((root/'binding.json').read_bytes())['host_id']==configuration['host_id']
