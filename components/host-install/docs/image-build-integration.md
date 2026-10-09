# image-build integration handoff

Prepared 2026-09-30 against the supplied `host-install-artifact-v1.md` document.
The tested dependency is now pinned below and in version-share-handoff.json.

## Implemented consumer boundary

- Import `zog.image_build.host_export.verify` and call it with the trusted ID supplied
  by the caller. Preserve canonical identity verification in image-build.
- Require artifact schema 1, kind `host-install-artifact`, all-root-v1 ownership.
- Copy the documented envelope (`manifest.json`, `rootfs.tar`, optional
  `boot.tar`) into an exclusive private operation directory and reverify the copy.
- Extract regular files/directories/symlinks only. Validate all member names,
  parent kinds, duplicate names, modes, ownership, types and expansion bounds
  before extraction. Create real directories/files first and symlinks last.
  Preserve absolute symlink targets without traversing them. Reject hardlinks,
  devices, set-ID modes and extended archive headers.
- Compare installed tree inventory, modes, bytes and link targets with the
  verified archive. Preserve submitted readiness/security information explicitly.
- Optionally build an ext4 root fixture using the verified root tree under
  uid/gid 0. Report filesystem integrity and bootability as separate results.

No code interprets kernel/module ABI, accepts caller evidence as independent
verification, clears image-build readiness blockers, or treats a copied artifact
ID as an independently trusted ID. The initial/current exporter never supplies
a boot-ready artifact and staging reports `installable=false` unconditionally.

## Coordination needed next

1. Completed: retrieve, pin and test the real exporter plus all four fixtures.
   Retain this integration suite when either side changes.
2. Preserve the existing tar contract. host-install's separate raw image fixture
   plan is internal testing infrastructure, not a requested exporter change.
3. Decide where the kernel/initramfs/modules are installed and how EFI loader
   binaries/configuration are supplied. The host-install layer must generate or
   verify root arguments against the allocated HOST-A PARTUUID before any boot
   candidate may be described as complete. No bootloader format is selected yet.
4. Set runtime mount composition and writable paths jointly with box-control and
   host-identify. No host keys or administrator credentials are created here.
5. Keep foreign boot provenance and blockers attached to all installation results.
   A future UKI/verity provider should replace the boot-provider contract while
   retaining ESP/HOST-A/HOST-B/STATE/APPLICATIONS partition roles.

## Current test status — 2026-10-01

Retrieved and tested image-build unstable commit
`1e5fa28d1713afb3640ebe762a2e792f56bd8694`. The real verifier and committed
fixtures now run successfully: valid, corrupt-payload, unsafe-path and
false-readiness. All fixture IDs come from that reviewed commit's
`expectations.json`; the positive ID also matches the supplied handoff:
`98b3240f21ececf7f4100950a18b769f0c5fb485971a15587af2987697d6c658`.

The first real run exposed the sticky-mode mismatch: the consumer rejected
01777 on tmp. The supported mode mask now matches artifact-v1's 01777;
set-UID and set-GID remain rejected. Upstream ImageBuildError is converted to
host-install InstallError, so CLI rejection is structured JSON with exit 2.

The complete suite passes 34 tests, with no skips in this environment. Beyond
the four fixture outcomes, real integration checks populate ext4, run e2fsck,
read a fixture file through debugfs, verify tmp retains 01777 inside ext4, and
check structured CLI rejection. No stub is used in those six integration tests.

```sh
HOST_INSTALL_FIXTURES=/path/to/image-build/examples/host-install/fixtures \
PYTHONPATH=/path/to/image-build/src:src \
python3 -m unittest discover -s tests -v
```

Source-only testing remains distinct from boot acceptance. The synthetic
artifact stays installable=false. No kernel or EFI image is executed.
The host package planning inventory does not establish an installable host.
