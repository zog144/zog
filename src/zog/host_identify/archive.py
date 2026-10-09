"""Archive-mirror contract: locally configured Ed25519 keyring; no remote key lookup."""
import re
import time
import uuid
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

LIFETIME = 900
TOLERANCE = 5
OPERATIONS = {'download', 'list'}


def permissions(operations, collections):
    if not isinstance(operations, list) or not isinstance(collections, list) or len(operations) > 2 or len(collections) > 100:
        raise ValueError('Invalid archive policy')
    if any(not isinstance(x, str) or x not in OPERATIONS for x in operations):
        raise ValueError('Unknown archive operation')
    if any(not isinstance(x, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', x) for x in collections):
        raise ValueError('Invalid collection identifier')
    return sorted(set(operations)), sorted(set(collections))


def issue(private_key, key_id, issuer, audience, subject, operations, collections, *, now=None):
    operations, collections = permissions(operations, collections)
    if not operations or not collections:
        raise ValueError('Empty grant')
    stamp = int(time.time() if now is None else now)
    claims = {'iss':issuer, 'aud':audience, 'sub':str(uuid.UUID(str(subject))), 'iat':stamp,
              'exp':stamp+LIFETIME, 'jti':str(uuid.uuid4()), 'version':1,
              'operations':operations, 'collections':collections}
    token = jwt.encode(claims, private_key, algorithm='EdDSA', headers={'kid':key_id, 'typ':'at+jwt'})
    return token, claims['exp']


def verify(token, public_keys, issuer, audience, operation, collection):
    """Called for EVERY request, before resolving a collection to a filesystem path."""
    try:
        if not isinstance(token, str) or len(token) > 16384:
            raise ValueError('Invalid token size')
        header = jwt.get_unverified_header(token)
        if set(header) != {'alg','kid','typ'} or header['alg'] != 'EdDSA' or header['typ'] != 'at+jwt':
            raise ValueError('Invalid header')
        key = public_keys[header['kid']]
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError('Ed25519 verification key required')
        claims = jwt.decode(token, key, algorithms=['EdDSA'], issuer=issuer, audience=audience, leeway=TOLERANCE,
                            options={'require':['iss','aud','sub','iat','exp','jti','version','operations','collections'], 'strict_aud':True})
        if type(claims['iat']) is not int or type(claims['exp']) is not int or not 0 < claims['exp']-claims['iat'] <= LIFETIME or claims['version'] != 1:
            raise ValueError('Invalid lifetime or version')
        uuid.UUID(claims['sub']); uuid.UUID(claims['jti'])
        permissions(claims['operations'], claims['collections'])
        if operation not in OPERATIONS or operation not in claims['operations'] or collection not in claims['collections']:
            raise ValueError('Permission denied')
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise PermissionError('Archive authorization denied') from None
