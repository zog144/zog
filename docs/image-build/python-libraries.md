# OpenSSL and SQLite foundation

`python -m zog.zog.image_build.source_libraries --project PROJECT --catalogue project/package
--controller CONTROLLER --selection ACCEPTED_GENERATION --work NEW_WORK_DIRECTORY`
runs a durable ordinary dependency pipeline using an accepted stage-2 toolchain.
Resume with the same arguments. Configure/build/test/install commands and the installed
library probe run through box-control; journal output is available to station-access.
OpenSSL is independent; SQLite declares a build/runtime edge to readline-final.
Readline 8.3 uses the existing October source/license pin and links to ncurses in
the accepted toolchain. Compiler, Perl/Tcl, zlib and ncurses are supplied by that
bound toolchain, not resolved from host RPMs at build time. Readline has no separate
upstream test target in this recipe; installed readline is exercised by SQLite and
the installed-library link check.

The October 2026 pins add upstream master snapshots as of the end of October 1 UTC,
recorded October 3: OpenSSL 7ef69a722c129fe446d7a1fef52ff8f12ccb010b (4.2.0-dev),
SQLite Fossil 99aab2c99220a3814124a57653e6627aa91c24459bf4eb87e69c9ed0b3378a0c
(3.54.0; GitHub mirror 9696acb0c77f1c1a7a400446686debc1312c94bc).
These are development snapshots pending live acceptance, not distro release versions.
All downloads require the pinned SHA-256. Existing monthly package entries are retained.

OpenSSL installs shared libraries, headers, CLI, and upstream legacy module, but does
not activate legacy by default. TLS 1.0/1.1 and SSLv3 are disabled; TLS minimum 1.2
and security level 2 are configured. Modern upstream default-provider algorithms,
including available post-quantum algorithms, remain enabled. MD2, RC5 and binary-field
EC are disabled. Camellia, RFC3779, x86-64 optimized EC, kTLS, PIE and zlib are enabled.
No FIPS validation is claimed. Distro FIPS, jitterentropy, system crypto-policy and
SCTP integrations are deferred; no distribution patches are applied. The config
contains no private keys or host identity. Public CA trust data is a separate pending
package/policy; the acceptance check uses an explicit disposable local trust anchor.

SQLite installs shared libraries, headers and CLI with legacy SONAME. FTS3/4/5,
R-tree, JSON and math (upstream defaults), sessions/preupdate hooks, column metadata,
unlock notification, dbstat, API armor and secure-delete default are selected.
Thread safety, readline and loadable-extension support are enabled. Extension
support does not automatically load or authorize arbitrary extensions in applications.
Directory syncing is retained. ICU and additional distributor tools are deferred.

OpenSSL runs its upstream `make test`. SQLite runs upstream `testrunner.tcl --jobs 8 veryquick` in isolated worker
processes/directories. The pinned upstream revision already propagates failed-job
status; the older Fedora exit-status patch is unnecessary. Acceptance additionally
queries testrunner.db for nonempty completed work, zero errors and inclusion of
sessionnoact, shell1 and zipfile. A successful runner exit alone is insufficient.
This is not the entire SQLite release qualification matrix. Installed checks exercise
certificate hostname verification (including rejection), provider activation policy,
SQL/WAL/FTS/JSON/R-tree and linking C code to both installed shared libraries.
Python is not rebuilt by this command; `_ssl`/`_sqlite3` acceptance is the next stage.
The enriched generation is recorded without changing `toolchain-active`.


## Distribution comparison

Exact retrieved spec hashes, URLs, dependency declarations and patch inventories
are in each project's `distribution-review.py`.

| Area | Fedora / openSUSE evidence | Zog choice |
|---|---|---|
| OpenSSL layout | Both distro-prefix builds; different trust-store layouts | /usr/lib and /etc/ssl |
| Crypto integration | Both carry PROFILE=SYSTEM and FIPS patches; SUSE adds jitterentropy | Upstream provider model and explicit TLS defaults; integration deferred |
| Legacy | Both explicitly enable MD2; Fedora RC5; SUSE patches legacy loading | No MD2/RC5, no automatic legacy activation |
| Acceleration | Both enable kTLS and optimized x86-64 EC | Enable both; kTLS availability still depends on kernel/runtime |
| Optional transport | Fedora SCTP requires lksctp-tools | Defer SCTP; not needed by Python HTTPS |
| SQLite feature set | Both FTS, R-tree, sessions, metadata, secure-delete | Adopt those plus API armor from SUSE |
| SQLite durability | Fedora disables directory sync | Retain upstream directory sync |
| SQLite tests | Fedora patches multiworker exit status and a corruption fixture | Run isolated upstream veryquick suite and verify job records; do not suppress failures |

Selected patch contents inspected: Fedora PROFILE=SYSTEM and SHA-1 control;
SUSE legacy auto-loading and trust-store relocation; Fedora SQLite testrunner exit
status and fts3corrupt4 fixture. These downstream changes are not silently applied
to the newer upstream development pins. A failing upstream test remains a blocker.
Fedora's lemon utility template/build patches are for the separately packaged tool;
Zog uses the bundled generator and does not install a separate system lemon here.

## SQLite Tcl prerequisite validation

Both distribution specs require Tcl development files. The accepted toolchain
already provides Tcl; merely finding `tclsh` is insufficient. Configure now checks
headers, shared library and `/usr/lib/tclConfig.sh`, compiles and runs a Tcl_Init
probe, supplies `--with-tcl=/usr/lib`, and rejects a generated Makefile with Tcl
disabled or a missing configuration path. Test commands bind TCL_CONFIG_SH
explicitly. These checks execute inside the actual box-control build root.

The source recipe uses the existing accepted Tcl generation; it does not install
an Amazon Linux Tcl RPM or introduce a redundant Tcl rebuild. The dependency
disposition inventory in `sqlite/distribution-review.py` accounts for every
BuildRequires from the two reviewed specs for the selected feature/test set.
It is not a claim to run every distribution sanitizer or ICU test variant.
Changing this recipe requires a new pipeline/work identity; existing frozen
recipes and failed test evidence must not be edited in place. Unchanged package
outputs remain eligible for normal content-verified reuse.
