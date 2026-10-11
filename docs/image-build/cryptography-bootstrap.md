# Python cryptography bootstrap

`project/bootstrap/cryptography.py` builds cryptography 50.0.2 on the accepted
Maturin/Rust/Python generation. It uses the unchanged pinned publisher source
distribution and 32 registry archives named by its Cargo.lock, each SHA256
verified. Workspace path crates are already in the publisher archive. No source
patches, binary wheels or network dependency resolution are used.

The October 1 pin gains this executable recipe/closure without changing the
already selected release. Known repository locations are recorded separately;
unknown Git revisions are not inferred from release names. Licensing records
retain publisher and dependency notice hashes, with unresolved review scopes
remaining explicit. This is not public-release acceptance.

Build requirements from the pinned pyproject.toml are checked before compilation.
The inherited environment supplies Maturin 1.15.0, Rust/Cargo, Python 3.15,
CFFI 2.1.1, setuptools, packaging, installer, GCC, pkgconf and the target OpenSSL
and libffi development files. Exact base output/canonical bindings are retained.

Build policy: Cargo frozen/offline; OPENSSL_DIR=/usr; OPENSSL_STATIC=0;
OPENSSL_NO_VENDOR=1; CRYPTOGRAPHY_BUILD_OPENSSL_NO_LEGACY=1. Maturin produces a
native Linux wheel without manylinux repair or bundled OpenSSL. No new crypto
algorithm configuration or FIPS certification is implied. See upstream build
requirements at https://cryptography.io/en/latest/installation/; the pinned
archive remains authoritative for this version's actual requirements.

Checks run against the unpacked source-built wheel and again inside the composed
installed root: native extension import, dynamic libcrypto dependency and no
embedded search path, matching OpenSSL version with Python ssl, SHA256,
AES-128-GCM zero-key/IV known-answer encryption/decryption plus altered-tag
rejection, RFC 8032 section 7.1 Ed25519 test 1 plus altered-message rejection and
PKCS8 key serialization. This is a focused host-identity prerequisite acceptance,
not the upstream full test suite. The upstream test group additionally requires
cryptography_vectors 50.0.2, pytest, pytest-benchmark, pytest-cov, pytest-xdist,
pretend and certifi; those test dependencies are not installed by this pass.

Canonical inputs are frozen before dispatch; verification and outputs are bound
to the final generation. Source preparation uses declared-notice-read-bits-v1
from the license readability fix. Existing accepted Maturin/Rust outputs are
reused. The previous runtime generation remains accepted until the new one passes.
