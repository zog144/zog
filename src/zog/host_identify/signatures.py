"""Zog RFC 9421 Ed25519 profile v1; no custom signature canonicalization."""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from http_message_signatures import HTTPMessageSigner, HTTPMessageVerifier, HTTPSignatureKeyResolver, algorithms

COMPONENTS = ('@method', '@authority', '@target-uri', 'content-type', 'content-digest', 'x-host-id', 'x-host-key')
TAG = 'zog-host-v1'
WINDOW = 120
SKEW = 5


def origin(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise ValueError('An HTTPS origin is required')
    return value.rstrip('/')


def public_text(key):
    return base64.b64encode(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def public_key(value):
    raw = base64.b64decode(value, validate=True)
    if len(raw) != 32 or base64.b64encode(raw).decode() != value:
        raise ValueError('Invalid Ed25519 public key')
    return Ed25519PublicKey.from_public_bytes(raw)


def fingerprint(key):
    return hashlib.sha256(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest()


class Resolver(HTTPSignatureKeyResolver):
    def __init__(self, key, identifier):
        self.key, self.identifier = key, identifier
    def resolve_public_key(self, key_id):
        if key_id != self.identifier:
            raise ValueError('Key mismatch')
        return self.key
    resolve_private_key = resolve_public_key


def digest(body):
    return 'sha-256=:' + base64.b64encode(hashlib.sha256(body).digest()).decode() + ':'


def sign(url, body, key, host_id, *, now=None, nonce=None):
    stamp = now or datetime.now(timezone.utc)
    identifier = fingerprint(key.public_key())
    message = requests.Request('POST', url, data=body, headers={
        'Content-Type': 'application/json', 'Content-Digest': digest(body),
        'X-Host-Id': str(host_id), 'X-Host-Key': identifier}).prepare()
    HTTPMessageSigner(signature_algorithm=algorithms.ED25519, key_resolver=Resolver(key, identifier)).sign(
        message, key_id=identifier, created=stamp, expires=stamp+timedelta(seconds=WINDOW),
        nonce=nonce or secrets.token_urlsafe(24), label='host', tag=TAG, covered_component_ids=COMPONENTS)
    return message


def verify(url, method, headers, body, key, host_id):
    """Returns authenticated nonce and expiry; caller MUST persist nonce atomically."""
    identifier = fingerprint(key)
    message = requests.Request(method, url, data=body, headers=dict(headers)).prepare()
    verifier = HTTPMessageVerifier(signature_algorithm=algorithms.ED25519, key_resolver=Resolver(key, identifier))
    result, = verifier.verify(message, max_age=timedelta(seconds=WINDOW))
    if result.label != 'host' or set(result.covered_components) != {f'"{x}"' for x in COMPONENTS} | {'"@signature-params"'}:
        raise ValueError('Incorrect signature coverage')
    params = result.parameters
    if set(params) != {'created', 'expires', 'nonce', 'keyid', 'alg', 'tag'} or params['tag'] != TAG or params['alg'] != 'ed25519':
        raise ValueError('Incorrect signature profile')
    if type(params['created']) is not int or type(params['expires']) is not int or not 0 < params['expires']-params['created'] <= WINDOW:
        raise ValueError('Invalid signature lifetime')
    nonce = params['nonce']
    if not isinstance(nonce, str) or not re.fullmatch(r'[A-Za-z0-9_-]{22,64}', nonce):
        raise ValueError('Invalid nonce')
    if message.headers.get('X-Host-Id') != str(host_id) or message.headers.get('X-Host-Key') != identifier:
        raise ValueError('Host binding mismatch')
    if message.headers.get('Content-Type') != 'application/json' or not hmac.compare_digest(message.headers.get('Content-Digest', ''), digest(body)):
        raise ValueError('Body digest mismatch')
    return nonce, datetime.fromtimestamp(params['expires']+SKEW, timezone.utc)
