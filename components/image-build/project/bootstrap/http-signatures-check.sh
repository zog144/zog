set -eu
python3 - <<'ZOG_HTTP_SIGNATURES'
import copy, hashlib
from importlib.metadata import version
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from http_message_signatures import HTTPMessageSigner, HTTPMessageVerifier, HTTPSignatureKeyResolver, InvalidSignature, algorithms, http_sfv
assert version('http-message-signatures') == '2.0.1'
private = Ed25519PrivateKey.generate()
class Resolver(HTTPSignatureKeyResolver):
    def resolve_private_key(self, key_id):
        assert key_id == 'zog-acceptance'
        return private
    def resolve_public_key(self, key_id):
        assert key_id == 'zog-acceptance'
        return private.public_key()
request = requests.Request('POST', 'https://example.invalid/enroll', data=b'public acceptance fixture').prepare()
def digest(message):
    return str(http_sfv.Dictionary({'sha-256': hashlib.sha256(message.body).digest()}))
request.headers['Content-Digest'] = digest(request)
covered = ('@method', '@authority', '@target-uri', 'content-digest')
signer = HTTPMessageSigner(signature_algorithm=algorithms.ED25519, key_resolver=Resolver())
verifier = HTTPMessageVerifier(signature_algorithm=algorithms.ED25519, key_resolver=Resolver())
signer.sign(request, key_id='zog-acceptance', covered_component_ids=covered)
results = verifier.verify(request)
assert len(results) == 1 and results[0].parameters['keyid'] == 'zog-acceptance'
assert all('"'+name+'"' in results[0].covered_components for name in covered)
assert request.headers['Content-Digest'] == digest(request)
for field, value in [('method', 'DELETE'), ('url', 'https://example.invalid/other')]:
    changed = copy.deepcopy(request); setattr(changed, field, value)
    try:
        verifier.verify(changed)
    except InvalidSignature:
        pass
    else:
        raise AssertionError('altered signed component accepted: '+field)
changed = copy.deepcopy(request); changed.body = b'altered body'
# The application must compare the signed digest with the received body.
assert changed.headers['Content-Digest'] != digest(changed)
changed.headers['Content-Digest'] = digest(changed)
try:
    verifier.verify(changed)
except InvalidSignature:
    pass
else:
    raise AssertionError('altered signed digest accepted')
print('ZOG_HTTP_SIGNATURES_ED25519_PASS')
print('ZOG_HTTP_SIGNATURES_TAMPER_REJECTION_PASS')
print('ZOG_HTTP_SIGNATURES_ACCEPTANCE_PASS')
ZOG_HTTP_SIGNATURES
