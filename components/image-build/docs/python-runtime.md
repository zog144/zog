# Python runtime stage

`python-runtime.py` builds Expat, GDBM, libffi and pkgconf before Python through the
ordinary dependency resolver and durable box-control execution path. Its base must
be the accepted OpenSSL/SQLite self-hosted toolchain generation. Host RPMs do not
satisfy missing target dependencies. Tests and installed acceptance use journald.

The final Python stage pins the unmodified upstream 3.15.0rc2 release, also selected
by Fedora. Python 3.14.7 remains the bootstrap recipe. Fedora's 3.14 spec explicitly
excludes OpenSSL 4, and the exact 3.14.7 `_ssl.c` still calls removed protocol-method
APIs. Upstream support landed in 3.15 (CPython issue 146207); its proposed 3.14
backport was closed without merging. The final stage therefore has separate source
and license metadata and an explicit entry in the October monthly pin set. This is
a reviewed release exception, not a claim of an October 1 master snapshot. Ordinary
builds never follow a moving branch. No downstream Python patches are applied.

The dependency releases follow LFS 13.1; downloads are SHA256 pinned and their LFS
MD5 records were cross-checked. Required upstream license texts are recorded and
retained. Licensing is declared, not fully release-reviewed. GDBM has GPL terms;
this pass does not authorize binary redistribution.

## Configure and dependency decisions

The three fetched RPM specs and their hashes, BuildRequires, patch inventories and
Zog decisions are recorded in `project/package/python/distribution-review.py`.
The selected feature set includes shared libpython, PGO, LTO, IPv6, system Expat,
libffi and mpdecimal, GNU Readline, curses/panel, UUID, GDBM/ndbm, bzip2/xz/zlib/zstd,
SQLite loadable extensions, and OpenSSL's cipher policy. TLS policy is inherited
from the accepted OpenSSL generation and checked after installation. The GIL stays
enabled; experimental JIT, free-threaded variants, Tk/X11, Bluetooth headers,
DTrace/SystemTap and Valgrind support are deferred. No bundled pip wheels are
installed. Python application packaging and its own dependency closure follow later.

Generated release configure/build inputs avoid autoreconf, Git and documentation
regeneration requirements. RPM macros, distro install-path changes, wheel packages,
Sphinx, desktop metadata tools and distro-specific crypto-policy packages are not
part of this build. The compiler, test tools and existing library requirements come
from the recorded base. Libffi uses generic CPU targeting. Expat disables DocBook
regeneration. GDBM includes its compatibility API; the optional command-line
Readline interface is disabled. pkgconf 3.0.5 uses its own upstream C test runner.

Every selected Python native extension is required to have `STATE=yes` in the
configured Makefile, so a missing development library cannot silently downgrade
the runtime. The source test phase runs focused standard-library regressions,
including ssl, hashlib, SQLite, ctypes, sockets/select/urllib/HTTP servers,
accounts/locking/os, compression, decimal, curses/readline, XML and dbm. Other
platform/release tests and optional resource tests are not claimed as passed.

## Composition and installed acceptance

The `python_runtime` worker takes an explicit prior Python ownership manifest.
It verifies its package identity and compares every owned non-directory entry
against the selected base. Composition removes only those verified old Python
entries before merging new outputs. Unowned collisions and changed old bytes fail;
there is no general overwrite allowance. Old source/license metadata stays available.

After composition a separate box-control job uses the installed Python, shared
libraries and modules to test local HTTPS with an explicit test CA, rejection of
an untrusted certificate and wrong hostname, TLS minimum/security level, SQLite
WAL persistence/integrity/FTS/JSON, foreign calls, compression, XML and dbm. A public
CA store is still required for general Internet HTTPS; the test CA is not installed.
The worker publishes a new immutable toolchain generation only after controller
exit 0 and cleanup completion. It does not move toolchain-active.

Invoke `python -m zog.zog.image_build.python_runtime` with `--project`, `--catalogue`,
`--controller`, `--selection`, `--python-ownership` and `--work`. Resume with the same
arguments/work directory; it discovers its exact frozen pipeline. The explicit
`--maximum-generations` defaults to 32 (matching final compiler orchestration), is
bound in its intent, and does not imply automatic reclamation. Check capacity and
free space before launch. Never delete live dependencies to make room.

Generation publication enforces matching `kind` and toolchain `stage` in hashed
inputs and manifest details before writing the generation. The library and Python
publishers both supply these fields. An older library publication that omitted
them must be republished through the corrected library worker using the original
frozen work/catalogue/base; verified package outputs and installed-check evidence
are reused. Do not alter an immutable manifest or relax the strict reader.


## Services fixture and reviewed RDS exceptions

The final Python stage declares a files-only test fixture, composed into a
separately recorded test root. `/etc/services` includes domain 53/tcp and 53/udp
for offline libc service lookup; it does not start DNS or represent a complete
runtime services database. Accepted base and compilation roots are not edited.

Five exact, user-approved exceptions are bound to the Python 3.15.0rc2 archive
and its digest in integration.py: RDSTest.testPeek, testSelect, testSendAndRecv,
testSendAndRecvMsg and testSendAndRecvMulti. These supersede the earlier two
individual exceptions. BasicRDSTest and all other socket tests remain enabled.
No wildcard excludes the whole module or unrelated RDS classes.

The shared client fixture closes its sender immediately. Fresh-namespace Python
and independent C diagnostics reproduced startup/lifetime behavior; holding the
sender until reception made all five receiver tests pass. This is not a claim
that the original sender-close ordering works or that a particular vendor kernel
bug has been proven. The diagnostic report is linked from the metadata.

When RDS is available, a required pre-suite probe runs 100 rounds of all five
original receiver methods (500 checks), holding client teardown until receiver
completion. The original receive operations/assertions are unchanged. It checks
class membership, rejects skips/incomplete coverage, and uses a fatal 30-second
watchdog plus a five-second sender acknowledgement bound. Method substitutions
exist only in the probe process and are restored afterward; no CPython source
or runtime patch is applied. An unavailable RDS facility is reported explicitly,
consistent with upstream conditional tests. Services and bounded peek checks
also remain required. Any unexpected failure stops the pipeline.

Exceptions propagate into published generation/result metadata, require review
on each monthly Python pin and kernel change, and retire when an applicable
upstream fix or corrected environment passes the original cases. Recipe changes
require a new frozen pipeline after explicit controller-resource release; failure
records remain retained. Verified completed dependency artifacts may be reused,
but old command successes are not transplanted into changed recipes.
