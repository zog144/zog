# Integration observations for `integrate-observe`

Build-trace 0.11 is the read-only query boundary between canonical build evidence and
future cross-release interpretation. It exposes facts and caller-selected sequences;
it does not choose releases, baselines, chronology, regressions, severity, causes,
blast radius or findings.

## Current companion contract

The preferred canonical boundary is build-record 0.7's immutable
`generation-observation-snapshot`.

Current compatible build-record:

`07431fcaab52d8f619efb8f332616329bc32c486` (0.7.1)

The original image-build producer foundation remains:

`6ef51f2d498159b7d667be0322a977563de994c5`

Direct image-build envelope queries remain compatibility/validation surfaces. New
integrate-observe consumers should use canonical snapshot roots whenever available.

## Canonical snapshot inspection

```sh
build-trace --project-root PROJECT --host-id HOST \
  --record-store RECORDS --record-project-id PROJECT_ID \
  observation-snapshot sha256:SNAPSHOT
```

A snapshot supplies the exact immutable generation observation set. Build-trace does
not select a latest snapshot. Collections are independently pageable:

- verification checks;
- verification executions;
- relationships;
- source provenance;
- observation coverage.

Coverage preserves `complete`, `partial`, `unavailable`, `not-performed` and
`not-applicable`. A complete family with zero observations is distinct from missing
coverage. Metadata closure completeness is reported separately.

Two explicit roots can be compared factually with
`compare-observation-snapshots`. Added/removed canonical records are not labeled
regressions or causes.

## Verification history

`verification-history` accepts a logical check ID followed by **1–100 canonical
snapshot IDs in caller order**:

```sh
build-trace ... verification-history image-build/trust/command/0 \
  sha256:SNAPSHOT_A sha256:SNAPSHOT_B sha256:SNAPSHOT_C

build-trace ... verification-history image-build/trust/command/0 \
  sha256:SNAPSHOT_A sha256:SNAPSHOT_B \
  --definition-digest sha256:DEFINITION
```

Each returned point contains:

- the caller position and exact snapshot;
- canonical generation/root-inventory identity;
- every matching verification-check definition in that snapshot;
- every matching verification execution in that snapshot;
- canonical `verification-commands` coverage;
- metadata-closure availability.

No execution is selected as representative. Repeated PASS/FAIL/ERROR/SKIP results
remain separate. A changed definition digest stays distinct while retaining the same
logical check ID.

The sequence order is presentation supplied by the caller. Build-trace reports
`order: caller-supplied` and `chronology: not-inferred`; it does not claim that
snapshot B was built or observed after snapshot A.

History cursors bind the exact ordered snapshot sequence, logical check,
definition filter, authorization scope and record store.

## Relationship traversal

`relationship-traversal` performs literal matching over canonical
`relationship-observation` records at each caller-ordered snapshot point.

Examples:

```sh
# Forward: facts whose recorded subject belongs to package glibc.
build-trace ... relationship-traversal forward package glibc \
  sha256:SNAPSHOT_A sha256:SNAPSHOT_B

# Reverse: facts whose literal target is SONAME libc.so.6.
build-trace ... relationship-traversal reverse soname libc.so.6 \
  sha256:SNAPSHOT_A sha256:SNAPSHOT_B

# Narrow to one relationship type.
build-trace ... relationship-traversal reverse soname libc.so.6 \
  sha256:SNAPSHOT_A sha256:SNAPSHOT_B --relation needs-library
```

Forward selectors:

- `package`: package subject or artifact ownership list;
- `package-output`: exact package subject output record;
- `artifact-path`: exact artifact subject path;
- `artifact-digest`: exact artifact subject digest.

Reverse selectors:

- `package`: exact declared package target, or the package label carried by an exact
  `package-output` target;
- `package-output`: exact canonical output target;
- `soname`: exact SONAME target;
- `path`: exact interpreter path target.

Reverse lookup is **not provider resolution**. For example, finding both
`needs-library libc.so.6` and `provides-soname libc.so.6` returns two literal facts;
build-trace does not assert that the provider satisfies the need.

Every traversal point carries the relevant canonical coverage families. With an exact
relation filter only that relation's coverage family is included; without one,
relationship traversal carries ELF interface, script interpreter, declared package
dependency and used-build-output coverage. Zero matches therefore remain interpretable
alongside what was or was not examined.

Traversal/history are reconstructed from caller-supplied immutable roots. There is no
persistent reverse index or new datastore.

## Raw producer compatibility

`generation-observations` and `candidate-verifications` can still validate/read
image-build v1 exports through an injected provider or the trusted one-shot
`--observation-file` CLI option. They do not supersede stored canonical snapshots.

## CI boundary

Repository-only Actions run on Python 3.10 and 3.13. They exercise canonical snapshot
projection, S1/S2 comparison, caller-ordered verification history, coverage handling,
literal relationship traversal, cursor binding and authorization with controlled
read-only fixtures.

A separate optional job probes the exact private build-record companion. The automatic
repository `GITHUB_TOKEN` cannot currently read that separate private repository, so
the probe is non-blocking unless `ZOG_CI_TOKEN` is configured. Build-record runs its
own repository-local Actions matrix independently.

No EC2, systemd, root-control or live host is required for these query semantics.

## Deliberate limits

Build-trace still does not:

- choose or discover an ordered release sequence for the caller;
- infer chronology from snapshot contents;
- choose a verification result as representative;
- call a changed outcome a regression;
- resolve SONAME/path observations to providers;
- compute transitive dependency reachability or blast radius;
- assign severity or policy meaning;
- persist findings or decisions.

Those are integrate-observe responsibilities.


## Independent consumer stopping gate

The repository includes `acceptance/integrate_observe_consumer.py`, a deliberately
small downstream consumer that imports only:

```python
from zog.build_trace import BuildTrace
```

It uses exactly the four public observation methods needed by the early
integrate-observe design:

- `observation_snapshot`;
- `compare_observation_snapshots`;
- `verification_history`;
- `relationship_traversal`.

The consumer produces only factual data and explicitly records that it has not selected
a baseline, inferred chronology, selected a representative execution, resolved an
interface provider, classified a regression, or computed blast radius.

Actions installs the package and runs this consumer acceptance from outside the source
checkout on Python 3.10 and 3.13. The acceptance source is AST-checked so importing
build-record/image-build or a `build_trace.*` internal module fails the gate.

Passing this gate is the planned coherence/stopping point for the initial build-trace
foundation required by integrate-observe. Further build-trace features should be driven
by a demonstrated consumer gap rather than speculative interpretation logic.


## 0.12 completeness contract for integrate-observe

The real two-generation acceptance exposed that build-record 0.7 aggregate
`complete = not missing_records and not gaps` was previously surfaced as
`metadata_closure_complete`. Build-trace no longer exposes that aggregate under a
closure name.

Consumers should model these independently:

```text
reference_closure_complete
missing_record_count

declared_gap_free
declared_gap_count
declared_gap_reason_count
declared_gap_summary

coverage
```

Detailed declared gaps are available through:

```sh
build-trace ... observation-snapshot sha256:SNAPSHOT \
  --collection declared-gaps

build-trace ... observation-snapshot sha256:SNAPSHOT \
  --collection declared-gaps --gap-category upstream-identity
```

No image-build state directory is required for canonical snapshot, comparison,
verification-history or relationship-traversal queries. This supports isolated release
evidence, Work containers and services separated from the original build host.

Build-trace still performs no snapshot discovery. Snapshot identities remain explicit
caller/owner inputs until image-build publishes an owner-defined discovery contract.


## Aggregate Python namespace

Downstream Python consumers import the public surface as:

```python
from zog.build_trace import BuildTrace
```

Cross-component implementation imports use `zog.build_record`,
`zog.image_build`, `zog.box_control`, and `zog.root_control` where applicable.
The old top-level module names are not compatibility aliases.
