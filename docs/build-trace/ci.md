# GitHub Actions CI

Build-trace uses GitHub Actions as the regular repository-level test gate for behavior
that does not require a live Zog host.

The workflow runs on pushes and pull requests to `unstable`, plus manual dispatch.

## Core matrix

Repository-only tests run on both Python 3.10 and Python 3.13, covering the supported
version floor and a current interpreter:

```sh
python -m unittest discover -s tests -v
```

Optional companion-dependent tests skip when their libraries are absent. Repository-
only fixtures directly exercise snapshot projection/comparison, observation coverage,
caller-ordered verification histories, literal relationship traversal, cursor scope,
authorization, ordinary trace inspection and parsing behavior.

## Full private companion contract

The cross-repository job uses repository secret `ZOG_CROSS_REPO_READ_TOKEN` to
check out exact private companion revisions:

- build-record `d28d7fc71ec497754edb8a226f5a8c7baa8b6ee8`;
- image-build `967a21cd72eb2fa4e423a6a40814e2c50e90f9ea`;
- box-control `3a3699061371ff76207395050a6be1ceb56e11c9`;
- root-control `f9e527ab41f5532775d63ca9cb6602f9cf156459`;

The job uses Python 3.11, installs `dbus-next==0.2.3` and `pytest>=8`, exposes the
four migrated companion `src` trees only through `PYTHONPATH`, and runs the complete
build-trace unittest discovery. The shell gate fails if unittest reports any skipped tests.

Actions run 37533287006 established the full contract:

- 132 tests run;
- 132 passed;
- 0 skipped.

This now executes the tests that the repository-only matrix intentionally skips:
canonical build-record joins, image-build owner-capture fixtures, and the
image-build/box-control integration contract.

The repository-only Python 3.10/3.13 matrix remains useful because it proves
build-trace's standalone behavior without companion availability. The full private
companion job is the stronger cross-program contract gate.

No EC2 host or live systemd manager is required by this CI boundary. Real host tests
remain separate and should be requested only when correctness depends on actual
systemd, journald, root-control, runtime filesystem, reboot/recovery or networking.


## Independent consumer gate

A separate Python 3.10/3.13 matrix installs `build-trace` with `pip install .`,
changes the working directory to the runner temporary directory, and executes
`tests/test_independent_consumer.py`.

The consumer source lives at `acceptance/integrate_observe_consumer.py`. Its source is
mechanically checked to ensure it imports the public `zog.build_trace` package only. It
must not import `build_record`, `image_build`, or any `build_trace.*` internal
module.

The gate exercises the public snapshot, snapshot-comparison, verification-history and
relationship-traversal methods through an installed package. Controlled fixture wiring
belongs only to the test harness. The consumer itself receives a public `BuildTrace`
object and has no knowledge of canonical record schemas or producer layouts.

This job is intentionally separate from ordinary unit tests. A green core matrix proves
repository behavior; a green independent-consumer matrix additionally proves that the
documented public observation surface is sufficient for the early integrate-observe
read-only workflow.


Build-trace 0.12 canonical-only/completeness coverage is included in the same gates.
Actions run 37623308430 passed:

- core Python 3.10: 132 discovered / 71 executed / 61 optional-companion skips;
- core Python 3.13: 132 discovered / 71 executed / 61 optional-companion skips;
- independent consumer Python 3.10: 5/5 passed with no image-build owner state;
- independent consumer Python 3.13: 5/5 passed with no image-build owner state;
- full private companion Python 3.11: **132/132 passed, zero skips**.

The new controlled cases cover canonical-only snapshot inspection/comparison/history/
traversal, complete closure with declared gaps, missing references, complete
zero-observation coverage, partial/unavailable coverage, and independent comparison of
closure/gaps/coverage.


## Namespace migration gate

Core CI installs the component from `src/zog/build_trace` before running tests.
The namespace regression test rejects the obsolete top-level `build_trace` import,
legacy cross-component module paths, stale patch/dynamic-import targets, and old module-execution examples.

The full private companion job uses migrated namespace sources for build-record,
image-build, box-control and root-control. No compatibility package is introduced.


## Final Zog namespace migration evidence

Actions run `37816416527` is the final migration gate:

- core Python 3.10: 135 discovered / 74 executed / 61 optional-companion skips, all executed passed;
- core Python 3.13: 135 discovered / 74 executed / 61 optional-companion skips, all executed passed;
- independent consumer Python 3.10: 5/5 passed from the installed component;
- independent consumer Python 3.13: 5/5 passed from the installed component;
- full private migrated-companion Python 3.11: **135/135 passed, zero skips**;
- namespace wheel/sdist artifact audit: passed.

The artifact job builds both wheel and sdist. It verifies that the wheel contains
`zog/build_trace/__init__.py`, omits `zog/__init__.py`, omits developer-only
`tests/` and `acceptance/` content, and publishes the development entry point
`build-trace = zog.build_trace.cli:main`. It also verifies that the sdist retains
tests, acceptance fixtures, documentation, and `COPYRIGHT`.

The namespace regression test additionally verifies that the old top-level Python
package cannot be imported and scans maintained Python code for obsolete component
imports, patch/dynamic-import strings, and module-execution targets.
