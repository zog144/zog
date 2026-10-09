set -eu
python3 - <<'ZOG_CRYPTOGRAPHY'
import hashlib, pathlib, ssl, subprocess
import cryptography
from cryptography.hazmat.bindings import _rust
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.exceptions import InvalidSignature, InvalidTag
assert cryptography.__version__ == '50.0.2'
assert backend.openssl_version_text() == ssl.OPENSSL_VERSION
library = pathlib.Path(_rust.__file__)
assert library.is_file() and '.so' in library.name
needed = subprocess.check_output(['readelf', '-d', str(library)], text=True)
assert 'libcrypto.so.' in needed, needed
assert '.libs/' not in needed and 'RPATH' not in needed and 'RUNPATH' not in needed, needed
print('ZOG_CRYPTOGRAPHY_NATIVE_OPENSSL', backend.openssl_version_text(), library)
h = hashes.Hash(hashes.SHA256()); h.update(b'abc')
assert h.finalize().hex() == hashlib.sha256(b'abc').hexdigest()
# NIST SP 800-38D AES-128-GCM zero-key/IV, one-block known-answer case.
aead = AESGCM(bytes(16)); nonce = bytes(12)
expected = bytes.fromhex('0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf')
assert aead.encrypt(nonce, bytes(16), b'') == expected
assert aead.decrypt(nonce, expected, b'') == bytes(16)
try:
    aead.decrypt(nonce, expected[:-1]+bytes([expected[-1]^1]), b'')
except InvalidTag:
    pass
else:
    raise AssertionError('altered GCM tag accepted')
print('ZOG_CRYPTOGRAPHY_AESGCM_PASS')
# RFC 8032 section 7.1 test 1 (empty message).
seed = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
key = Ed25519PrivateKey.from_private_bytes(seed)
public = key.public_key()
assert public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex() == 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'
signature = key.sign(b'')
expected_signature = bytes.fromhex(
    'e5564300c360ac729086e2cc806e828a'
    '84877f1eb8e5d974d873e06522490155'
    '5fb8821590a33bacc61e39701cf9b46b'
    'd25bf5f0595bbe24655141438e7a100b'
)
assert len(expected_signature) == 64, 'invalid RFC 8032 fixture length'
assert signature == expected_signature, 'RFC 8032 signature mismatch'
public.verify(signature, b'')
try:
    public.verify(signature, b'altered')
except InvalidSignature:
    pass
else:
    raise AssertionError('altered signed message accepted')
encoded = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
assert serialization.load_pem_private_key(encoded, None).sign(b'') == signature
print('ZOG_CRYPTOGRAPHY_ED25519_PASS')
print('ZOG_CRYPTOGRAPHY_ACCEPTANCE_PASS')
ZOG_CRYPTOGRAPHY
