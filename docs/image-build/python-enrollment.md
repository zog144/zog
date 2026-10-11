# Python enrollment dependency stages

`project/bootstrap/python-enrollment.py` declares 24 source-built Python distributions,
including the packaging backends required to build them. The resolver orders build and
runtime dependencies; no pip dependency downloads occur inside build jobs. Sources are
publisher sdists pinned by SHA-256 in the October 2026 monthly selection. Upstream
repository links remain secondary references. Release sdists are deliberate bootstrap
inputs, not a claim to use the latest upstream Git commit.

Flit-core bootstraps itself with its upstream wheel builder and bootstrap installer.
Installer then builds from source using Flit and installs itself. Subsequent builds
use their declared PEP 517 backend and the source-built installer. Backend requirements
(including dynamic wheel-hook requirements) must already be installed and satisfy
version constraints. Missing requirements fail; the frontend never resolves or fetches
them. Backend source paths come from the hash-verified sdist and must remain within it.
All generated wheels stay in build storage, outside the implementation repository.

Each recipe checks wheel structure/version and imports its staged installation.
The composed-root check validates installed dependency versions and exercises CFFI,
IDNA, HMAC JWT, SQLite and default CA loading. These are bootstrap acceptance checks,
not full upstream optional test suites. Requests keeps upstream Certifi behavior;
consumers wanting Zog's Mozilla trust bundle must explicitly use `/etc/ssl/cert.pem`.
Installing Certifi does not silently change Requests to use the system bundle.

`python_enrollment` is a durable supervisor over existing box-control package jobs.
It freezes the monthly pin and recipe/material bytes through the canonical provenance
producer before package execution. Recovery keeps the same inputs, policy and attempt.
Composition preserves the accepted base package output/result bindings and retains
host-label omission evidence. It verifies installed behavior before publishing a new
immutable toolchain generation. The final toolchain is not automatically selected.
The existing `ensure` pipeline still activates its intermediate package-only image;
application consumers must continue to use their explicitly pinned generation during
this bootstrap. The separate HTTPS acceptance application pins its own image.

The caller supplies an exact `base-components` JSON mapping from the accepted base
manifest's package names to their retained output roots. Changed or missing component
inventories fail before execution. The historical Python base remains explicitly legacy;
adding dependencies does not reconstruct its producing attempt. Installed-check execution
is referenced through box-control; the canonical generation verification list is not
retroactively populated with a fabricated verification attempt.

Cryptography, Maturin and HTTP Message Signatures have pinned source/licensing inventory
but no executable recipe yet. Maturin 1.15 requires Rust 1.89, and source-building it also
needs setuptools-rust. A reviewed Rust/Cargo bootstrap and fully pinned Cargo dependency
closure must precede that stage. Host-identify, host-discover and host-install packaging,
Ed25519 acceptance and outbound HTTPS acceptance remain subsequent gates. The generated
root is not marked enrollment-complete or bootable.

The Installer and Setuptools sdists contain precompiled Windows launchers. Their
Linux recipes omit the 16 exact hash-bound `.exe` inputs before wheel construction;
the original archives and notices remain retained. No foreign launcher is installed
and the wheel's own RECORD is generated from the reduced Linux package contents.

`zog.zog.image_build.public_https` publishes a separate finite acceptance image and launches
it through box-control, without changing the active image. It tests a real public
TLS connection, wrong-hostname rejection and unknown-CA rejection. Its IP address
is resolved by the host and frozen before launch; target DNS is deliberately not
claimed. Every socket and the overall application have finite timeouts. Build jobs
remain network-isolated. Inspect the application invocation's terminal status and
journal before claiming acceptance; successful dispatch alone is not a passed test.

Wheel checks select the top-level `.dist-info/METADATA`; vendored distributions may
have their own nested metadata and must not be mistaken for the wheel's identity.
An explicit `--retry-of` mapping binds a new package attempt to the failed attempt's
canonical final failed/cancelled result record without changing that old attempt's frozen recipe or policy.

The HTTPS image declares empty `/dev`, `/proc`, `/sys`, `/root` and `/var/tmp`
mountpoints before publication, with their modes bound into its composition inputs.
This prevents systemd's mount preparation from adding unrecorded directories to a
published generation. The serializer still checks every recorded path and attribute.
