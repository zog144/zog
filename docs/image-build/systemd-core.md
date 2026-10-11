# Source-built systemd host component

`project/bootstrap/systemd-core.py` selects systemd 261.2, matching the LFS 13.1
reference used for the preceding native dependency batch. The upstream Git commit
and downloaded archive SHA256 are recorded in the catalogue, source provenance,
and October pin. No source modifications or downstream patches are applied.

The exact accepted base must provide the self-hosted C compiler, Meson/Ninja,
Gperf, Python/Jinja2, libmount/blkid, ACL, libxcrypt, Kmod, LZ4, PCRE2, OpenSSL,
zlib, xz and zstd. Version 261.2 does not require external libcap. Base components
must bind original package outputs, not substitute a composed generation for an
individual package. Native-tools verifies their inventories and provenance.

The initial headless profile builds the manager, journal, udev, networkd,
resolved, timesyncd, sysusers, tmpfiles and hardware database support. Required
libraries are explicitly enabled; Meson automatic optional features are disabled.
This deliberately leaves PAM/logind, polkit, SELinux/AppArmor, seccomp, BPF,
TPM, homed, userdb, machine/portable/namespace managers, systemd-boot, UKI tooling,
sysupdate and partition/image managers outside this build's acceptance scope.
Such features require subsequent dependency and deployment review. Documentation
and translation generators are disabled. Original licensing notices remain.
DNSSEC, mDNS and LLMNR default off; OpenSSL DNS-over-TLS support is compiled,
without enabling it by default. Host network/time-server policy is separate.

Compilation and testing execute through box-control with the existing isolated,
network-disabled build policy. `meson test` runs the upstream default selection:
it excludes integration-tests and analysis-tool suites as upstream defines;
slow tests default off. There is no downstream exclusion list, success masking,
or waiver of unexpected failures. Privileged/full-boot integration remains a
separate gate. An upstream skip is not a successful exercise of that feature.

Installation uses DESTDIR and SYSTEMD_OFFLINE=1, without host service activation,
preset-all, machine-id generation or udev triggering. The accepted base and host
systemd installation are not modified. New files become a separately published
immutable generation only after package tests and installed verification pass.

Installed checks run version commands, require the planned daemons, compile and
execute a libsystemd/libudev API probe, and verify a synthetic unit offline.
They do not start PID 1, contact the host manager or load kernel modules.
Boot, D-Bus service operation, enrollment, persistent identity, mount policy and
network acceptance must be tested separately before host-install promotion.

Licensing remains declared, with LGPL systemd/library and GPL udev scopes and
upstream exceptions retained. This build is not a public-release license audit.
References: upstream v261.2 README, meson_options.txt, LICENSES/README.md;
https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter08/systemd.html.

## Test environment

IANA tzdata 2026d is a declared build/runtime dependency, compiled with the
accepted Glibc zic. Its own check parses every generated zone and verifies Berlin
DST and UTC offsets. No host timezone data is copied. The timezone selection for
a booted host remains a host-install decision.

Build explicitly generates all 12 Meson directive fixtures before --no-rebuild
testing. Tests use C.UTF-8 and an 8 MiB soft stack limit: the upstream fiber guard
probe traverses only 64 MiB, while the compiler policy permits a 256 MiB stack.
A build-only build-environment package supplies an explicitly named Zog
build-environment os-release, with original private copyright and exact source
hashes. Normal package provenance records its output and the systemd dependency
edge. It is excluded from runtime composition and creates no host identity. No upstream tests are excluded or masked.
