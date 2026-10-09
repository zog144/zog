# Native systemd dependency batch

Attr, ACL, libxcrypt, LZ4, PCRE2 and Kmod use exact LFS 13.1 release archives
added to October pins on 2026-10-07. Sources/notices are hash-bound. No patches.
ACL follows Attr through declared dependency resolution. Existing compilers and
build systems and compression/OpenSSL libraries come from the accepted base.

Attr/ACL/libxcrypt run upstream make check, LZ4 make check, PCRE2 CTest. Upstream
root/NFS/environment skips remain visible, not silently converted to passes.
Kmod's privileged/kernel-fixture suite is not enabled: package CLI and installed
libkmod creation/destruction are checked without loading any host kernel module.
Kmod compression (zstd/xz/zlib) and OpenSSL signature support explicitly enabled;
documentation generators disabled. PCRE2 8/16/32-bit shared libraries and JIT are
enabled. libxcrypt uses strong/glibc hashes, obsolete API disabled.

Installed verification checks filesystem xattrs/ACLs on scratch files, compression
roundtrip, pkg-config providers, compiled shared-library calls and Kmod context.
This is prerequisite acceptance, not systemd or kernel/boot acceptance. Complete
per-file license review remains open; library/tool notices are retained.

The current upstream systemd Meson build was inspected for libacl, libcrypt,
liblz4, libpcre2 and libkmod feature dependencies. Final systemd source revision
and all option choices must be pinned/reviewed separately before its build.
No live portal/controller replacement or disk operation belongs to this pass.

## ACL test bootstrap (2026-10-07)

The inherited Coreutils `cp` does not preserve ACLs. ACL 2.4.0's unchanged
`test/cp.run` therefore failed despite successful setfacl/getfacl operations.
The build graph now explicitly orders Attr, an ACL test-bootstrap library,
Coreutils ACL test tools, then final ACL. The bootstrap library is staged under
`/opt/zog/acl-test-bootstrap`; pinned Coreutils 9.11 builds with ACL explicitly
enabled and requires `USE_ACL=1`. Only cp/ls are installed into its private test
prefix. The final ACL suite uses these tools and the just-built final ACL library.
No test is waived or edited. Bootstrap stages are build dependencies, excluded
from the published runtime target closure. Coreutils' own full test suite is not
run for this fixture; ACL's complete upstream suite supplies its scoped acceptance.

This corrects the test environment, not the inherited `/usr/bin/cp`. Replacing
Coreutils inside the aggregated accepted-python-base output requires a later
explicit provenance-bound composition transition; do not silently overwrite it.
The original failed attempt and its exact frozen inputs remain unchanged.

The Coreutils fixture declares its private ACL library path for all phases,
including make's help2man invocations. Configure-only or test-only settings are
insufficient because the build executes newly linked programs to generate manuals.
This declaration does not change the host loader configuration or final ACL's
explicit choice of its just-built library.

Libxcrypt 4.5.2 uses unmodified upstream commit 174c24d6e87aeae631bc0a7bb1ba983cf8def4de
for C23 strchr qualifier compatibility. The downloaded patch is SHA256-pinned, with
author attribution, affected-file before/after hashes, and retained original license
notices. Prepare applies it with zero fuzz before configure. Warnings-as-errors and
the upstream test suite remain enabled. Remove the patch when a pinned release
already includes the change.

LZ4 uses uppercase `LIBDIR` internally for its source directory (`../lib`).
Use lowercase `libdir=/usr/lib` for the install destination; overriding uppercase
`LIBDIR` on the make command line also changes source/header lookup in programs.
The recipe preserves upstream source layout and the unchanged `make check` suite.
