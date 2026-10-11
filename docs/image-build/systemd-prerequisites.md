# Systemd prerequisites

First batch: Gperf 3.3 from GNU, MarkupSafe and Jinja2 from exact upstream main
commits in October monthly pins (recorded_on 2026-10-07). Resolver dependency:
MarkupSafe -> Jinja2. Inherited compiler/Python/build backends are bound by the
accepted base generation; no network is enabled for compilation jobs.

Gperf runs make check. Python package wheels are validated/extracted in temporary
paths and exercised there, not imported from the source checkout. MarkupSafe must
build its native extension: CIBUILDWHEEL=1 disables silent pure-Python fallback.
Acceptance covers escaping, template inheritance, strict undefined handling and
unit-like text generation. The installed-root fixture also compiles and runs a
Gperf-generated C keyword lookup. Broad upstream pytest suites for MarkupSafe and
Jinja2 are not included; no all-suite acceptance is claimed. No patches or failed
test waivers. Licenses are source-bound declarations, not full release review.

Remaining planned native closure: Attr/ACL, libxcrypt, LZ4, PCRE2 and additional
libraries selected after exact systemd Meson option review (including capability
and module-loading support as appropriate). Then explicitly build journald, udev,
networkd, resolved and timesyncd. This batch is not systemd or boot acceptance.
Application-only Django/Waitress dependencies remain outside the base root, in
separately versioned read-only application mounts, per user direction.
