import json
import os
import stat
import time
import uuid
import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import archive, storage, signatures

ISSUER='https://registry.example.test';AUDIENCE='mirror-1';MIRROR='https://mirror.example.test'
@pytest.fixture
def grant():
    key=Ed25519PrivateKey.generate();subject=str(uuid.uuid4())
    token,expiry=archive.issue(key,'one',ISSUER,AUDIENCE,subject,['download'],['sources'])
    return key,subject,{'version':1,'format':'zog-archive-jwt-v1','mirror':MIRROR,'issuer':ISSUER,'audience':AUDIENCE,'token':token,'expires_at':expiry}

def verify(token,key,**changes):
    return archive.verify(token,{'one':key.public_key()},changes.get('issuer',ISSUER),changes.get('audience',AUDIENCE),changes.get('operation','download'),changes.get('collection','sources'))

@pytest.mark.parametrize('change',[{'issuer':'wrong'},{'audience':'wrong'},{'operation':'upload'},{'operation':'list'},{'collection':'root-filesystems'}])
def test_scope_and_identity(grant,change):
    key,_,data=grant
    with pytest.raises(PermissionError):verify(data['token'],key,**change)

def test_expiry_clock_tolerance_and_lifetime(grant):
    key,subject,_=grant
    for age,accepted in [(899,True),(902,True),(906,False)]:
        token,_=archive.issue(key,'one',ISSUER,AUDIENCE,subject,['download'],['sources'],now=int(time.time())-age)
        if accepted:verify(token,key)
        else:
            with pytest.raises(PermissionError):verify(token,key)
    claims=jwt.decode(grant[2]['token'],options={'verify_signature':False});claims['exp']=claims['iat']+901
    with pytest.raises(PermissionError):verify(jwt.encode(claims,key,algorithm='EdDSA',headers={'kid':'one','typ':'at+jwt'}),key)

@pytest.mark.parametrize('algorithm',['HS256','none'])
def test_algorithm_confusion(grant,algorithm):
    key,_,data=grant;claims=jwt.decode(data['token'],options={'verify_signature':False})
    token=jwt.encode(claims,'synthetic-secret-with-at-least-32-characters' if algorithm=='HS256' else None,algorithm=algorithm,headers={'kid':'one','typ':'at+jwt'})
    with pytest.raises(PermissionError):verify(token,key)

@pytest.mark.parametrize('header',[{'jku':'https://attacker.test/keys'},{'jwk':{}},{'x5u':'https://attacker.test/key'},{'crit':['anything']},{'kid':'unknown'}])
def test_no_remote_or_header_selected_keys(grant,header):
    key,_,data=grant;claims=jwt.decode(data['token'],options={'verify_signature':False})
    token=jwt.encode(claims,key,algorithm='EdDSA',headers={'kid':'one','typ':'at+jwt',**header})
    with pytest.raises(PermissionError):verify(token,key)

def test_rotation(grant):
    first,subject,data=grant;second=Ed25519PrivateKey.generate()
    new,_=archive.issue(second,'two',ISSUER,AUDIENCE,subject,['download'],['sources'])
    keys={'one':first.public_key(),'two':second.public_key()}
    for token in (data['token'],new):archive.verify(token,keys,ISSUER,AUDIENCE,'download','sources')
    del keys['one']
    with pytest.raises(PermissionError):archive.verify(data['token'],keys,ISSUER,AUDIENCE,'download','sources')

def paths(tmp_path):
    # pytest parent paths are owner-only; state dir deliberately explicit.
    private=tmp_path/'identity';private.mkdir(mode=0o700)
    shared=tmp_path/'credentials';shared.mkdir(mode=0o750)
    return private,shared

def save(shared,subject,data):
    storage.save_response(shared,{'version':2,'host_id':subject,'archive':data},expected_host=subject,expected_mirror=MIRROR,expected_issuer=ISSUER,expected_audience=AUDIENCE)

def test_key_survives_restarts_and_mode_checks(tmp_path):
    private,_=paths(tmp_path)
    first=signatures.fingerprint(storage.load_key(private).public_key())
    assert signatures.fingerprint(storage.load_key(private).public_key())==first
    assert stat.S_IMODE((private/'identity.pem').stat().st_mode)==0o600
    (private/'identity.pem').chmod(0o644)
    with pytest.raises(PermissionError):storage.load_key(private)

def test_symlink_and_unsafe_directory_rejected(tmp_path):
    private,shared=paths(tmp_path)
    (private/'identity.pem').symlink_to(tmp_path/'missing')
    with pytest.raises(PermissionError):storage.load_key(private)
    shared.chmod(0o777)
    with pytest.raises(PermissionError):storage.clear_credentials(shared)

def test_atomic_storage_reader_expiry_and_withdrawal(tmp_path,grant):
    _,shared=paths(tmp_path);key,subject,data=grant
    save(shared,subject,data);p=shared/'archive.json'
    assert stat.S_IMODE(p.stat().st_mode)==0o640
    value=storage.read_credentials(p,{'one':key.public_key()},ISSUER,AUDIENCE,'download','sources',MIRROR)
    assert value['token']==data['token']
    save(shared,subject,None);assert not p.exists()
    save(shared,subject,data)
    expired=dict(data,expires_at=int(time.time())-1)
    storage.atomic(p,json.dumps(expired).encode(),0o640)
    with pytest.raises(PermissionError):storage.read_credentials(p,{'one':key.public_key()},ISSUER,AUDIENCE,'download','sources',MIRROR)
    storage.purge_expired(shared);assert not p.exists()

def test_malformed_response_keeps_last_unexpired_credential(tmp_path,grant):
    _,shared=paths(tmp_path);_,subject,data=grant;save(shared,subject,data)
    old=(shared/'archive.json').read_bytes()
    for malformed in [dict(data,mirror='https://attacker.test'),dict(data,expires_at='never'),{},dict(data,token=12)]:
        with pytest.raises((ValueError,KeyError)):save(shared,subject,malformed)
        assert (shared/'archive.json').read_bytes()==old

def test_no_partial_replacement_on_write_failure(tmp_path,grant,monkeypatch):
    _,shared=paths(tmp_path);_,subject,data=grant;save(shared,subject,data)
    old=(shared/'archive.json').read_bytes()
    monkeypatch.setattr(os,'replace',lambda *args:(_ for _ in ()).throw(OSError('simulated full disk')))
    with pytest.raises(OSError):save(shared,subject,data)
    assert (shared/'archive.json').read_bytes()==old
    assert not list(shared.glob('.new-*'))

def test_mirror_boundary_fixture(grant):
    from zog.host_identify.mirror_fixture import application
    key,_,data=grant;app=application({'one':key.public_key()},ISSUER,AUDIENCE)
    def call(path):
        statuses=[]
        app({'REQUEST_METHOD':'GET','PATH_INFO':path,'HTTP_AUTHORIZATION':'Bearer '+data['token']},lambda status,headers:statuses.append(status))
        return statuses[0]
    assert call('/collections/sources/archives/example.tar.xz')=='200 OK'
    assert call('/collections/sources/')=='403 Forbidden'
    assert call('/collections/root-filesystems/archives/example.tar.xz')=='403 Forbidden'

def test_world_readable_credential_rejected(tmp_path,grant):
    _,shared=paths(tmp_path);key,subject,data=grant;save(shared,subject,data)
    p=shared/'archive.json';p.chmod(0o644)
    with pytest.raises(PermissionError):storage.read_credentials(p,{'one':key.public_key()},ISSUER,AUDIENCE,'download','sources',MIRROR)

def test_malformed_jwt_response_does_not_replace_valid_file(tmp_path,grant):
    _,shared=paths(tmp_path);_,subject,data=grant;save(shared,subject,data)
    old=(shared/'archive.json').read_bytes()
    with pytest.raises(ValueError):save(shared,subject,dict(data,token='not.a.jwt'))
    assert (shared/'archive.json').read_bytes()==old
