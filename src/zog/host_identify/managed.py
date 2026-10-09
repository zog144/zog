"""Managed admission v1: fixed Ed25519 JWT profiles, no remote key resolution."""
import time
import uuid
import jwt
from .signatures import fingerprint

SESSION_TYPE = 'zog-managed-session-v1'
COMMAND_TYPE = 'zog-managed-command-v1'
RESULT_TYPE = 'zog-managed-result-v1'
LIFETIME = 300
SCHEMA = 1


def identifier(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('Canonical UUID required')
    return value


def sign(claims, key, kind):
    return jwt.encode(claims, key, algorithm='EdDSA', headers={'typ':kind,'kid':fingerprint(key.public_key())})


def verify(token, key, kind, issuer, audience):
    if not isinstance(token,str) or len(token)>16384:raise ValueError('Invalid signed envelope')
    header=jwt.get_unverified_header(token)
    if header!={'alg':'EdDSA','typ':kind,'kid':fingerprint(key)}:
        raise ValueError('Unexpected envelope header')
    claims=jwt.decode(token,key,algorithms=['EdDSA'],issuer=issuer,audience=audience,
        options={'require':['iss','aud','sub','iat','exp','jti']},leeway=0)
    if type(claims['iat']) is not int or type(claims['exp']) is not int or not 0<claims['exp']-claims['iat']<=LIFETIME:
        raise ValueError('Invalid envelope lifetime')
    identifier(claims['jti']);identifier(claims['sub'])
    return claims


def session(token,key,expected):
    value=verify(token,key,SESSION_TYPE,expected['iss'],expected['aud'])
    if set(value)!=set(expected)|{'iat','exp','jti','epoch','checkpoint','operations'}:
        raise ValueError('Unexpected session fields')
    if any(value.get(k)!=v for k,v in expected.items()):raise ValueError('Session binding mismatch')
    if type(value['epoch']) is not int or value['epoch']<1:raise ValueError('Invalid epoch')
    identifier(value['checkpoint'])
    if value['operations']!=['inspect']:raise ValueError('Unsupported control scope')
    return value


def command(token,key,session_claims):
    value=verify(token,key,COMMAND_TYPE,session_claims['iss'],session_claims['aud'])
    if set(value)!={'iss','aud','sub','iat','exp','jti','session_id','operation','runtime_id'}:
        raise ValueError('Unexpected command fields')
    if value['sub']!=session_claims['sub'] or value['session_id']!=session_claims['jti'] or value['exp']>session_claims['exp']:
        raise ValueError('Command session mismatch')
    if time.time()>=session_claims['exp'] or value['operation']!='inspect' or value['operation'] not in session_claims['operations']:
        raise ValueError('Command not permitted')
    identifier(value['runtime_id'])
    return value
