# License and source boundaries

Original Zog implementation, documentation and artwork in this public export use
`BSD-3-Clause OR GPL-3.0-only`; see [LICENSE](LICENSE). This grant applies to this
reviewed public export, not to every historical private component revision.

## Retained GCC-derived source

`third-party/gcc/patches/strchr-c23.patch` and `cpython-gcc15.patch` are GCC-derived
testsuite source under `GPL-3.0-or-later`, independently of Zog's first-party choice.
The existing [GCC attribution and adaptation record](third-party/gcc/README.md)
identifies the upstream authors, commits, exact hashes and GCC 15 adaptation.
[The full GPL version 3 text](third-party/gcc/COPYING) accompanies them; the
or-later permission for these patches is preserved. They are source-build inputs,
not part of the Python wheel. Image-build retrieves their exact bytes through
immutable public commit URLs and verifies SHA-256.

## Dependencies obtained separately

The wheel declares Django, PyJWT, boto3, cryptography, dbus-next, dnspython,
http-message-signatures, requests, typing_extensions and waitress. Their code is
installed separately with its own notices and terms, not included or relicensed
in the Zog wheel. Their transitive dependencies likewise retain their own terms.

Station-access frontend dependencies are pinned by its npm lockfile. The frontend
license-evidence data and build plugin inspect the dependencies actually bundled,
verify reviewed notice bytes and emit full license notices next to the built assets.
Keep these notices with any deployed bundle. The frontend source is included here;
node_modules and compiled assets are not. noVNC/TurboVNC are separate software.

Image-build recipe license records describe the exact upstream versions and build
inputs. A record marked declared or unresolved is not a completed review of a
redistributable root filesystem. This source promotion does not publish a rootfs,
claim all rootfs license gates passed, or waive corresponding-source obligations.

## Historical recipe inputs and fixture exception

The catalogue includes version-bound host-identify, host-discover and host-install
recipes pointing at earlier private source revisions. Their private-license
records remain honest provenance for those exact inputs. Those old sources are
not copied here or relicensed by this export. A fully public rootfs build needs
new recipes using reviewed public aggregate sources; private repository access
must not be mistaken for a public download path.

The exact file
`components/image-build/project/package/build-environment/stages/systemd-test/fixtures/COPYRIGHT`
is retained as a hash-bound historical build/test fixture. Its private-development
wording is fixture content, not this repository's license declaration. Its bytes,
source hash and version-bound recipe evidence are deliberately preserved so the
existing recorded input does not silently change. The public first-party grant
above covers original Zog material in this export; it does not retroactively
rewrite the identity or license record of an already produced generation.
