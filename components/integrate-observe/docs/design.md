# World/Comparison design — v0.2

## World

A World is not a release. It is a caller-selected immutable observation snapshot plus
its build-trace projection. Selection establishes the *role* of baseline/candidate for
one comparison; it does not establish historical chronology.

The World stores build-trace's canonical generation and observation identities rather
than copying image-build or build-record internals.

## Evidence completeness

The first real-host acceptance showed that one aggregate completeness boolean was
insufficient. Version 0.2 therefore treats three dimensions independently.

### Reference closure

`reference_closure_complete` answers only whether every canonical reference reachable
from the selected snapshot is present. Missing records are graph-integrity facts.

### Declared gaps

`declared_gap_free`, counts and summaries describe reachable canonical records that
are present but explicitly say some fact is unknown, external or otherwise incomplete.
A declared gap does not make reference closure incomplete.

The `declared-gaps` collection is projected by build-trace and is included in factual
WorldComparison set changes. The exact canonical reason text is evidence; the category
is a build-trace presentation classification.

### Observation coverage

Coverage describes whether a collector examined its declared scope and with what
outcome. Complete zero-count coverage is different from unavailable, partial,
not-performed or absent coverage. Coverage is not canonical-reference integrity and is
not equivalent to declared provenance completeness.

## Comparison

Comparison is deterministic over two explicitly selected Worlds. It has four layers:

1. **Canonical set changes** — exact added/removed record identities from build-trace,
   including declared-gap rows.
2. **Safe pairings** — package source observations are paired only when unique on each
   side; verification executions are grouped by logical check ID and definition digest
   without choosing a representative execution.
3. **Evidence-completeness comparison** — baseline/candidate reference closure,
   declared gaps and observation coverage remain separate factual state.
4. **Interpretation boundaries** — explicit flags remain false for chronology,
   provider resolution, regression, causation, blast radius, severity and policy.

A later integration-analysis layer may interpret these facts, but v0.2 remains a
reliable answer to the narrower question: *what recorded observations and evidence
conditions differ between these two caller-selected worlds?*

## Schema boundary

integrate-observe output schema 2 requires build-trace's schema-1 v0.12 completeness
contract. It intentionally rejects the older v0.11 snapshot shape containing only
`metadata_closure_complete`; that field mixed reference closure with declared gaps and
must not be reconstructed under the old name.
