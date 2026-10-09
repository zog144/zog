import json
import uuid
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import pytest
from zog.host_discover.daemon import announce, main
from zog.host_identify import storage, signatures

@pytest.fixture
def configuration(tmp_path):
    private=tmp_path/'identity';private.mkdir(mode=0o700)
    shared=tmp_path/'credentials';shared.mkdir(mode=0o750)
    return {'server':'https://registry.example.test','identity_directory':str(private),'credential_directory':str(shared),'provider':'generic'}

class Response:
    def __init__(self,value,status=200):self.value=value;self.status=status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,maximum):return json.dumps(self.value).encode()[:maximum]

def test_pending_then_binding_then_signed_heartbeat(configuration):
    key=storage.load_key(configuration['identity_directory']);fp=signatures.fingerprint(key.public_key());host=str(uuid.uuid4())
    sent=[]
    def open_request(request,**kwargs):
        sent.append(request)
        if len(sent)==1:return Response({'status':'pending','fingerprint':fp},202)
        if len(sent)==2:return Response({'status':'approved','fingerprint':fp,'host_id':host})
        return Response({'version':2,'host_id':host,'archive':None})
    with patch('urllib.request.OpenerDirector.open',side_effect=open_request):
        for _ in range(3):announce(configuration,{'version':1})
    assert '/enrollment/' in sent[0].full_url
    assert f'/{host}/heartbeat/' in sent[2].full_url
    assert not any(request.has_header('Authorization') for request in sent)
    signatures.verify(sent[2].full_url,'POST',dict(sent[2].header_items()),sent[2].data,key.public_key(),host)

@pytest.mark.parametrize('failure',[URLError('network'),HTTPError('https://registry.example.test',503,'unavailable',{},None)])
def test_outage_preserves_unexpired_credential(configuration,failure):
    from pathlib import Path
    import time
    key=storage.load_key(configuration['identity_directory'])
    storage.atomic(Path(configuration['identity_directory'])/'binding.json',json.dumps({'host_id':str(uuid.uuid4()),'fingerprint':signatures.fingerprint(key.public_key())}).encode())
    root=Path(configuration['credential_directory'])
    storage.atomic(root/'archive.json',json.dumps({'expires_at':int(time.time())+300,'token':'synthetic-local-value'}).encode(),0o640)
    with patch('urllib.request.OpenerDirector.open',side_effect=failure):
        with pytest.raises(type(failure)):announce(configuration,{'version':1})
    assert (root/'archive.json').exists()

@pytest.mark.parametrize('status',[401,403])
def test_explicit_denial_clears_credential(configuration,status):
    from pathlib import Path
    import time
    key=storage.load_key(configuration['identity_directory'])
    storage.atomic(Path(configuration['identity_directory'])/'binding.json',json.dumps({'host_id':str(uuid.uuid4()),'fingerprint':signatures.fingerprint(key.public_key())}).encode())
    root=Path(configuration['credential_directory'])
    storage.atomic(root/'archive.json',json.dumps({'expires_at':int(time.time())+300}).encode(),0o640)
    with patch('urllib.request.OpenerDirector.open',side_effect=HTTPError('https://registry.example.test',status,'denied',{},None)):
        with pytest.raises(HTTPError):announce(configuration,{'version':1})
    assert not (root/'archive.json').exists()

def test_no_error_payload_secrets_in_logs(configuration,tmp_path,caplog):
    config=tmp_path/'configuration.json';config.write_text(json.dumps(configuration))
    with patch('sys.argv',['host-discover','--configuration',str(config),'--once']),patch('zog.host_discover.daemon.collect',return_value={'version':1}),patch('zog.host_discover.daemon.announce',side_effect=ValueError('DO-NOT-LOG-SECRET')):
        with pytest.raises(SystemExit):main()
    assert 'DO-NOT-LOG-SECRET' not in caplog.text
    assert 'ValueError' in caplog.text

def test_replacement_key_returns_to_pending_without_overwriting_binding(configuration):
    from pathlib import Path
    root=Path(configuration['identity_directory']);old=storage.load_key(root)
    host=str(uuid.uuid4())
    storage.atomic(root/'binding.json',json.dumps({'host_id':host,'fingerprint':signatures.fingerprint(old.public_key())}).encode())
    (root/'identity.pem').unlink()  # explicit loss/replacement scenario
    fresh=storage.load_key(root);fp=signatures.fingerprint(fresh.public_key())
    with patch('urllib.request.OpenerDirector.open',return_value=Response({'status':'pending','fingerprint':fp},202)) as opener:
        announce(configuration,{'version':1})
    request=opener.call_args.args[0]
    assert request.full_url.endswith('/enrollment/')
    assert json.loads(request.data)['claimed_host_id']==host
    assert json.loads((root/'binding.json').read_bytes())['fingerprint']!=fp

def test_optional_custom_ca_is_passed_to_tls(configuration):
    configuration['ca_file']='/operator-selected/ca.pem'
    with patch('ssl.create_default_context',side_effect=ValueError('test stop')) as tls:
        with pytest.raises(ValueError):announce(configuration,{'version':1})
    tls.assert_called_once_with(cafile='/operator-selected/ca.pem')
