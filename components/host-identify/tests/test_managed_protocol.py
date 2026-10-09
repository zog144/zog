import time
import uuid
import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from zog.host_identify import managed,signatures


def fixture():
    key=Ed25519PrivateKey.generate();now=int(time.time())
    expected=dict(iss='https://station.example',aud=str(uuid.uuid4()),sub=str(uuid.uuid4()),
        fingerprint='1'*64,installation_id=str(uuid.uuid4()),state_volume_id=str(uuid.uuid4()),registry_id='primary',
        challenge=str(uuid.uuid4()),previous=None,boot_id=str(uuid.uuid4()))
    claims=dict(expected,iat=now,exp=now+300,jti=str(uuid.uuid4()),epoch=1,checkpoint=str(uuid.uuid4()),operations=['inspect'])
    return key,expected,claims


def test_session_and_restricted_command():
    key,expected,claims=fixture()
    assert managed.session(managed.sign(claims,key,managed.SESSION_TYPE),key.public_key(),expected)==claims
    command=dict(iss=claims['iss'],aud=claims['aud'],sub=claims['sub'],iat=claims['iat'],exp=claims['exp'],jti=str(uuid.uuid4()),session_id=claims['jti'],operation='inspect',runtime_id=str(uuid.uuid4()))
    token=managed.sign(command,key,managed.COMMAND_TYPE)
    assert managed.command(token,key.public_key(),claims)==command
    command['operation']='launch'
    with pytest.raises(ValueError):managed.command(managed.sign(command,key,managed.COMMAND_TYPE),key.public_key(),claims)


@pytest.mark.parametrize('field,value',[('iss','https://other.example'),('aud','other'),('challenge','other'),('exp',1),('epoch',True),('operations',['launch'])])
def test_session_binding_and_expiry(field,value):
    key,expected,claims=fixture();claims[field]=value
    with pytest.raises((ValueError,jwt.PyJWTError)):managed.session(managed.sign(claims,key,managed.SESSION_TYPE),key.public_key(),expected)


def test_algorithm_and_remote_key_headers_rejected():
    key,expected,claims=fixture()
    token=jwt.encode(claims,'x'*32,algorithm='HS256',headers={'typ':managed.SESSION_TYPE})
    with pytest.raises(ValueError):managed.session(token,key.public_key(),expected)
    token=jwt.encode(claims,key,algorithm='EdDSA',headers={'typ':managed.SESSION_TYPE,'kid':signatures.fingerprint(key.public_key()),'jku':'https://attacker.example/keys'})
    with pytest.raises(ValueError):managed.session(token,key.public_key(),expected)
