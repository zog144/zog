# Distribution seed and first source build

This pass implements an Amazon Linux 2023 seed from the package catalogue, verifies it through box-control, builds GNU M4 1.4.21 from source, and verifies that binary in a fresh root.

## Run

Prepare the host prerequisites and Bison-compatible `/usr/bin/yacc` as documented in TOOLCHAIN-CATALOGUE.md. Run root-control and supply the same explicit nonzero execution UID/GID and controller configuration used by image-build. The project must be dedicated to this seed operation.

From `image-build-source`:

```sh
python3.11 -m image_build.developer.seed_build \
  --project /absolute/project \
  --package-dir /absolute/image-build-source/project/package \
  --controller-config /absolute/controller.json
```

Exit 75 means a controller job remains pending. Repeat the exact command, including from a new process. Exit 0 returns the seed and M4 generation identifiers. Other errors retain evidence and require inspection; a recorded failed command is not silently rerun. Build jobs use box-control/systemd, nonzero UID/GID, a read-only root, writable source/output mounts, disabled external network access, finite timeouts and explicit resource limits.

The standalone assembly operation is available as:

```sh
python3.11 -m image_build.developer.seed --package-dir project/package --directory /absolute/assembly
```

It only produces an **assembled-unverified** root. It does not publish or certify a usable seed.

## Assembly policy

The developer module reads catalogue-selected seed RPM names and resolves their installed dependency closure. It records exact installed versions and selected file ownership. The initial closure is conservative and includes interpreter modules and compiler support files; this is not a claim of a minimal seed. GNU File and Bzip2 are included as explicit probe/source-handling tools.

Selected `/usr` entries, legacy `/bin`, `/sbin`, `/lib`, `/lib64` entries and required root aliases are copied into the canonical layout. Directories are shallow: listing a directory never copies unlisted host children. Documentation, translated message catalogs and build-id links are excluded by policy. Missing RPM entries, dangling links and links into excluded host data/configuration are recorded as omissions. The seed probes establish fitness for this initial build, not every program in the RPM closure.

Symbolic links are normalized to in-root canonical targets. Set-ID bits are stripped from copied regular files and original modes are recorded. Minimal passwd/group/NSS files are generated for the configured build UID/GID. Host `/root`, `/etc` secrets, machine identity, RPM database and credentials are not imported.

The assembly records per-file SHA-256 values and reasons, verifies copied bytes, and rejects installed-version changes during assembly. These hashes identify observed host inputs; they are not an independent attestation that the original host binaries were trustworthy.

## Publication and recovery

State is retained under `PROJECT/state/image-build/seed-bootstrap`. A durable operation intent binds catalogue, recipe and execution policy. Assembly may be retried before controller registration. Once prepared, changed catalogue/root data is rejected. Verification retains typed controller completions and validates its outputs before reuse. The existing image-build pipeline owns M4 command resumption and package results.

The seed is published only after isolated C/C++ execution, prerequisite command checks, read-only-root/network checks and PTY checks succeed. Its kind is `host-bootstrap`; “generation 1 — distribution seed” is a display description, not a numeric storage identity. The first source M4 artifact has kind `seed-check`. It is not promoted to a self-hosted toolchain.

M4's fresh verification root starts from the recorded seed runtime and replaces the seed's M4 binary with the source-built result. It does not use the compiler workspace. The binary still depends on the distribution seed libc. Full source-built libc/compiler independence remains a later milestone.

## Source recipe and evidence

`package/m4/stages/native-seed` contains executable source, dependency, build/test/install and output definitions. The stage depends on the complete seed contract rather than pretending that its compiler and libc have already been source-built as Zog packages. Its bounded output is `/usr/bin/m4` plus the upstream COPYING file; documentation and translations are omitted intentionally. The upstream `make check` suite runs before installation.

The GNU tarball is pinned to SHA-256 `f25c6ab51548a73a75558742fb031e0625d6485fe5f9155949d6486a2408ab66`. Its detached signature was verified using the GNU keyring downloaded over HTTPS; the signing key fingerprint is `71C2CC22B1C4602927D2F3AAA7A16B4A2527436A`. This establishes the verification procedure and trust source, not a Zog security-network attestation.

Image-build emits package/phase progress. Controller records and `.execution.json` files preserve runtime, invocation and journal identities. Configure/compiler/test output remains in journald; the acceptance fixture collects it for review. It does not invent ordinary application-runtime identities for these finite build jobs.

Source references:

- https://ftp.gnu.org/gnu/m4/m4-1.4.21.tar.xz
- https://ftp.gnu.org/gnu/m4/m4-1.4.21.tar.xz.sig
- https://ftp.gnu.org/gnu/gnu-keyring.gpg
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter02/hostreqs.html
