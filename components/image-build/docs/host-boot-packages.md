# Native host package completion

`project/bootstrap/host-boot-packages.py` builds additions on an accepted systemd
core generation. It does not mutate that generation or activate host services.

- util-linux 2.42.2: a separate nologin-only stage adds `/usr/sbin/nologin` while
  retaining the existing native util-linux output. Its refusal exit code is tested.
- D-Bus 1.16.2: the reference daemon is the selected system-bus provider, with
  libsystemd integration and system service files. No X11, security-module or
  documentation generator dependencies. Meson default available tests run;
  GLib-dependent modular tests are unavailable in this profile. A private session
  bus round trip is required after installation. This is not live system-bus acceptance.
- iproute2 7.1.0: native tools with BPF disabled and the dependencies available in
  the exact base. Optional Berkeley DB/libmnl functionality is not claimed. Version
  probes run; upstream tests that mutate network namespaces/routes require a separate
  privileged disposable-host test and are not run by this build.
- libseccomp 2.6.0: shared library, full default `make check`, and an installed C
  probe that loads a filter and verifies the selected syscall returns EPERM.
- e2fsprogs 1.47.4: shared libraries, ext4 tools, full `make check`, then creation
  and read-only checking of a disposable regular-file filesystem. Existing
  util-linux libblkid/libuuid/fsck remain the providers; no block device is touched.
  LFS reports possible environment-sensitive failures; none are waived here.

The exact release archives and inspected licensing evidence are SHA256-pinned.
No upstream source patch is applied. License status is declared, not release-reviewed.
The source archives and original notices must remain available for later audit.

The next stage rebuilds systemd with libseccomp enabled and verifies `+SECCOMP`;
installing libseccomp alone does not enable systemd syscall filtering. Coordinated
`zog.*` runtime packaging follows separately from this external-source batch.
Host-install owns account materialization (including messagebus), service enablement,
machine identity, kernel/initramfs and disk/mount/network composition.

References: LFS 13.1-systemd chapter 8 package pages for D-Bus, IPRoute2 and
E2fsprogs; BLFS libseccomp 2.6.0; exact release build definitions and notices.
