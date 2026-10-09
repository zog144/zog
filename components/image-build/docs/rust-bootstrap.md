# Rust/Cargo bootstrap

The October 2026 pin adds publisher Rust 1.99.0 source (released October 1),
CMake 4.4.4 and cURL 8.22.0. These are explicit reviewed release inputs, not a
claim that the catalogue tracks moving master. The existing Pkgconf 3.0.5 pin
is retained. GitHub project URLs are secondary references; normal builds use
only the pinned archive URLs and SHA-256 hashes.

`project/bootstrap/rust-toolchain.py` resolves Pkgconf, CMake, cURL and Rust.
CMake builds its bundled libraries, using the accepted OpenSSL. cURL uses
OpenSSL and the system CA path; HTTP/2, HTTP/3, SSH, IDN2, PSL and LDAP optional
integrations are not enabled in this bootstrap profile. Cargo may compile its
shipped libgit2/libssh2 dependencies from the Rust source archive. These choices
do not claim distribution feature parity or complete bundled license review.

Rust builds its shipped LLVM for X86 and a stage2 compiler, std and Cargo.
The Rust source's `src/stage0` hashes authorize three **build-only foreign binary
seed** components: Rustc, std and Cargo 1.98.0. They are explicit recipe inputs,
with retained notices and provenance. They install only under the writable build
source directory, never into the target output. `download-rustc` and LLVM binary
downloads are disabled. Vendored crates, locked dependencies and Cargo offline
mode prevent dependency resolution from silently acquiring new sources.

Acceptance includes upstream stage2 standard-library tests and an installed
compiler/Cargo test of an offline local crate. It does not claim the full rustc
UI or Cargo integration suites. Prerequisites use targeted offline C/C++ and
libcurl/OpenSSL checks. No failure is waived automatically.

`python -m zog.zog.image_build.native_tools` accepts an explicit stage plan and installed
check, frozen monthly pins, base package output bindings and controller policy.
It preserves canonical package records, composes the inherited Python root with
new outputs, and requires the installed-verification report contract before
publishing the resulting generation. Old operations keep their original code and
contracts. Commands and logs remain box-control/build-trace references.

Use a new work directory for changed inputs. Long supervisors survive client
interruption; resume the same operation, never dispatch a duplicate on timeout.
The package pipeline publishes an intermediate package-only image; applications
must continue to pin their selected complete generation explicitly.

Compilation still requires completion of Rust and then the Python native signing
stack. This pass alone does not assert enrollment or boot readiness.

For a recipe correction that leaves the monthly pin unchanged, `--pin-revision`
may identify the earlier commit containing those exact pin bytes. The separate
`--source-revision` records the current implementation. This does not permit
changing a frozen operation or its execution policy. Explicitly release an old
pipeline and import its completed, verified package artifacts before reuse;
unfinished outputs are not eligible. Output recovery checks both canonical
output/result bindings and the installed inventory, including restored copies.
Cargo's `/etc/bash_completion.d/cargo` is an explicitly required installed output.

Rust also generates `etc/target-spec-json-schema.json` from the built compiler
(`src/bootstrap/src/core/build_steps/dist.rs`). The final recipe explicitly
allows and requires that file; it does not allow arbitrary files under `etc`.
Changing this acceptance declaration requires a new attempt. An earlier attempt
that failed output acceptance keeps its frozen recipe and failure record.
