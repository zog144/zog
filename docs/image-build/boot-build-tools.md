# Boot-support build tools

Ninja and Meson are pinned to exact upstream master commits recorded on 2026-10-07
in the existing October monthly pin. Normal execution never resolves branch heads.
No patches or host RPM installations. Sources and top-level licensing evidence are
hash-bound; complete bundled-fixture licensing review remains pending.

The resolver builds Ninja before Meson. The accepted host-enrollment generation
supplies the self-hosted compiler, Python and Python build backends. New attempts
capture canonical provenance before execution. Installed verification compiles,
tests and installs a C program with Meson/Ninja in a temporary writable directory,
with the generation read-only and network disabled, then checks no-op rebuilding.

Coverage: upstream Ninja Python syntax tests; Meson import/bytecode smoke check;
installed end-to-end C build. Ninja GoogleTest C++ suite and the broad Meson project
suite are not run by this initial prerequisite pass. No blanket suite acceptance.

Systemd and its native dependency closure remain subsequent work, with networkd,
resolved and timesyncd selected explicitly. This generation is not boot acceptance.

Station-access, Django, Waitress and their application dependency closure belong
in a separately versioned read-only application mount, not the base root filesystem.
Application updates do not require a new base generation; target Python/native ABI
compatibility and dependency hashes must still be validated before activation.
