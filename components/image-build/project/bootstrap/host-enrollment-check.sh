set -eu
python3 - <<'ZOG_ENROLLMENT'
import json, stat, tempfile, time, uuid
from pathlib import Path
from importlib.metadata import version, requires
from packaging.requirements import Requirement
from host_identify import initialization, signatures, managed
from http_message_signatures import InvalidSignature
assert version('host-identify') == '0.3.4'
for raw in requires('host-identify') or []:
    req = Requirement(raw)
    if req.marker is None or req.marker.evaluate({'extra':''}):
        assert version(req.name) in req.specifier, raw
with tempfile.TemporaryDirectory(prefix='zog-identity-check-') as scratch:
    root = Path(scratch)/'identity'; root.mkdir(mode=0o700)
    auth = {'schema':1,'kind':'zog-identity-initialization','authorization_id':str(uuid.uuid4()),
            'installation_id':str(uuid.uuid4()),'state_volume_id':str(uuid.uuid4()),
            'identity_directory':str(root),'account_profile':'zog-host-accounts-v1','expected_fingerprint':None}
    receipt = initialization.prepare(root, auth)
    before = {p.name:p.read_bytes() for p in root.iterdir()}
    assert initialization.prepare(root, auth) == receipt
    assert before == {p.name:p.read_bytes() for p in root.iterdir()}
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())
    key = initialization.load_existing(root, receipt)
    assert signatures.fingerprint(key.public_key()) == receipt['fingerprint']
    host = str(uuid.uuid4()); url = 'https://registry.example.invalid/api/hosts/enrollment/'
    body = b'{"fixture":"enrollment"}'
    request = signatures.sign(url, body, key, host)
    nonce, expiry = signatures.verify(url, 'POST', request.headers, body, key.public_key(), host)
    assert nonce and expiry.timestamp() > time.time()
    try:
        signatures.verify(url, 'POST', request.headers, b'{}', key.public_key(), host)
    except (ValueError, InvalidSignature):
        pass
    else:
        raise AssertionError('altered body accepted')
    now = int(time.time())
    expected = dict(iss='https://station.example.invalid',aud=host,sub=str(uuid.uuid4()),
        fingerprint=receipt['fingerprint'],installation_id=auth['installation_id'],state_volume_id=auth['state_volume_id'],
        registry_id='fixture',challenge=str(uuid.uuid4()),previous=None,boot_id=str(uuid.uuid4()))
    claims = dict(expected,iat=now,exp=now+120,jti=str(uuid.uuid4()),epoch=1,checkpoint=str(uuid.uuid4()),operations=['inspect'])
    envelope = managed.sign(claims,key,managed.SESSION_TYPE)
    assert managed.session(envelope,key.public_key(),expected) == claims
    try:
        managed.session(envelope,key.public_key(),dict(expected,challenge=str(uuid.uuid4())))
    except ValueError:
        pass
    else:
        raise AssertionError('incorrect session binding accepted')
    (root/'identity.pem').unlink()
    try:
        initialization.load_existing(root, receipt)
    except initialization.IdentityStateError:
        pass
    else:
        raise AssertionError('missing identity accepted')
    assert not (root/'identity.pem').exists()
print('ZOG_HOST_IDENTITY_INIT_SIGNATURE_SESSION_PASS')

import json, tempfile, uuid
from pathlib import Path
from unittest.mock import patch
from importlib.metadata import version, requires
from packaging.requirements import Requirement
from host_identify import storage, signatures
from host_discover.daemon import announce
import host_discover.beacon, host_discover.recovery, host_discover.supervisor
import host_install.state_contract
for name, expected in [('host-identify','0.3.4'),('host-install','0.4.3'),('host-discover','0.4.5')]:
    assert version(name) == expected
    for raw in requires(name) or []:
        req = Requirement(raw)
        if req.marker is None or req.marker.evaluate({'extra':''}):assert version(req.name) in req.specifier,raw
with tempfile.TemporaryDirectory(prefix='zog-enrollment-check-') as scratch:
    root=Path(scratch)/'identity';root.mkdir(mode=0o700)
    shared=Path(scratch)/'credentials';shared.mkdir(mode=0o750)
    config={'server':'https://registry.example.invalid','identity_directory':str(root),'credential_directory':str(shared),'provider':'generic'}
    key=storage.load_key(root);fp=signatures.fingerprint(key.public_key());host=str(uuid.uuid4());sent=[]
    class Response:
        def __init__(self,value,status=200):self.value=value;self.status=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,maximum):return json.dumps(self.value).encode()[:maximum]
    def open_request(request,**kwargs):
        sent.append(request)
        if len(sent)==1:return Response({'status':'pending','fingerprint':fp},202)
        if len(sent)==2:return Response({'status':'approved','fingerprint':fp,'host_id':host})
        return Response({'version':2,'host_id':host,'archive':None})
    with patch('urllib.request.OpenerDirector.open',side_effect=open_request):
        for _ in range(3):announce(config,{'version':1})
    assert len(sent)==3 and '/enrollment/' in sent[0].full_url
    assert f'/{host}/heartbeat/' in sent[2].full_url
    assert not any(request.has_header('Authorization') for request in sent)
    signatures.verify(sent[2].full_url,'POST',dict(sent[2].header_items()),sent[2].data,key.public_key(),host)
    assert json.loads((root/'binding.json').read_text())['host_id']==host
print('ZOG_HOST_ENROLLMENT_PENDING_APPROVED_HEARTBEAT_PASS')
print('ZOG_HOST_ENROLLMENT_INSTALLED_ACCEPTANCE_PASS')
ZOG_ENROLLMENT
