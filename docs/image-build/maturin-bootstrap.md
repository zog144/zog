# Maturin source bootstrap

The next native package after accepted Rust/Cargo is Maturin 1.15.0.
`project/bootstrap/maturin.py` materializes its pinned executable stage.
The publisher sdist remains the primary source. Its unmodified Cargo.lock fixes
472 registry archives; each is independently retrieved and SHA256 checked.
The October 1 monthly pin gains this executable recipe and exact closure without
changing the previously selected Maturin release. Existing frozen operations are
not modified by this catalogue extension.

The initial build uses Cargo directly to bootstrap the Maturin executable, then
uses that executable to create Maturin's own Python wheel. This avoids adding
setuptools-rust merely to break the bootstrap cycle. The wheel is installed by
the already accepted Python installer. Build jobs have Cargo offline/frozen mode
and a checksummed directory source generated solely from declared archives.
No prebuilt wheel, rustup, or registry version resolution is used.

Default Cargo features are disabled: this build supplies local native wheel
building and the Python build backend. Optional uploading, credential storage,
cross-compilation, scaffolding, SBOM and platform repair integrations are not
part of this acceptance. Linux-native wheels intentionally use compatibility
`linux` and skip portable-wheel repair; the target's libraries remain explicit
image dependencies. Do not interpret this as manylinux portability acceptance.

The source sdist excludes the upstream test fixtures. Verification covers the
CLI, built wheel metadata and contents, and a separate installed-root test that
uses the Python backend to build, install and execute a dependency-free Rust
binary wheel offline. This does not claim the complete upstream test suite or
PyO3-extension/cryptography acceptance. Cryptography is the next separate target.

The operation uses native_tools canonical provenance: exact monthly pin, source
archives, recipe bytes, build policy, accepted inherited outputs and installed
verification are frozen and connected to the resulting generation. Inherited
Rust/Cargo and Python packages are reused, not rebuilt.

Per-crate license declarations and hash-bound notices are retained. Optional and
non-target crates appear in the lock closure; their presence does not prove they
are linked. Unknown expressions/notices remain unresolved and public-release
review remains incomplete. No downstream source patches are applied.
