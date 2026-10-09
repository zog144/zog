"""Expired managed-session checkpoint evidence, never a usable session token."""
import hashlib
import json
import time
import jwt
from . import managed, signatures

TYPE = 'zog-managed-expiry-evidence-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def verify(token, key, expected, now=None):
    try:return _verify(token,key,expected,now)
    except jwt.PyJWTError as exc:raise ValueError("Invalid evidence signature or claims") from exc


def _verify(token, key, expected, now=None):
    if type(token) is not str or len(token)>16384:raise ValueError('Invalid evidence')
    if jwt.get_unverified_header(token)!={'alg':'EdDSA','typ':TYPE,'kid':signatures.fingerprint(key)}:
        raise ValueError('Unexpected evidence header')
    value=jwt.decode(token,key,algorithms=['EdDSA'],issuer=expected['iss'],audience=expected['aud'],
        options={'require':['iss','aud','sub','iat','exp','jti'],'verify_iat':False,'verify_exp':False,'verify_nbf':False})
    if set(value)!=set(expected)|{'iat','exp','jti','epoch','checkpoint','session_expired_at'}:raise ValueError('Unexpected evidence fields')
    if any(value.get(k)!=v for k,v in expected.items()):raise ValueError('Evidence binding mismatch')
    now=time.time() if now is None else now
    for field in ('iat','exp','epoch','session_expired_at'):
        if type(value[field]) is not int:raise ValueError('Invalid evidence integer')
    if not value['iat']<=now<value['exp'] or not 0<value['exp']-value['iat']<=managed.LIFETIME:raise ValueError('Evidence expired or not yet valid')
    if value['session_expired_at']>value['iat'] or value['epoch']<1:raise ValueError('Session is not expired')
    for field in ('sub','jti','checkpoint'):managed.identifier(value[field])
    return value
