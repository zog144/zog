# HTTP message signatures bootstrap

The pinned http-message-signatures 2.0.1 publisher sdist is built offline on the
accepted cryptography generation using hatchling/hatch-vcs. This is a pure Python
library implementing HTTP message signing/verification, separate from Python and
HTTPS. Host-identify uses it; this pass does not deploy enrollment services.

The accepted base provides the exact canonical outputs for Python, cryptography,
Requests and build backends. The recipe checks declared backend/runtime versions
before invoking the PEP 517 backend, and performs no implicit dependency install.
All 11 upstream unittest methods are run unchanged, alongside wheel integrity.
Lint/type-check tooling is not included. The installed-root fixture checks Ed25519
signing, covered fields, method/URL/digest tampering, and the application's separate
body-digest comparison. The library itself does not validate HTTP body digests or
supply application replay policy; those remain host-identify responsibilities.

LICENSE declares Apache-2.0; embedded http_sfv has an MIT notice. Both, plus NOTICE,
are hash-bound in license.py, correcting the previous MIT-only catalogue label.
No upstream source patches or pin changes. Full public redistribution review is
still incomplete. Sources and tests remain in the external pinned archive.

Canonical provenance freezes the monthly pin, recipes, source and accepted base
inputs before dispatch; installed verification binds the immutable generation.
