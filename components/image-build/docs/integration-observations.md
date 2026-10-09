# Integration observations: producer contract v1

This read-only interface supplies build facts to build-record and build-trace.
It performs no regression analysis, compatibility judgment, release policy or
human decision tracking. JSON Schemas live in `docs/schemas/`.

## Export and consumption

```
python -m zog.zog.image_build.integration_observations \
  --state /path/to/project/state \
  --provenance-config /path/to/frozen-operation/intent.json \
  --selection /path/to/generation \
  --output /path/to/integration-observations.json
```

The config argument accepts either a provenance configuration or an owner intent
containing `provenance`. Scope must match the canonical generation. The exporter
verifies canonical closure, retained material hashes and current generation bytes.
It does not read the current recipe catalogue or monthly branch head. `--readelf`
selects a trusted inspection-host tool; target executables are never run.

`--candidate <64-hex-owner-generation>` instead of `--selection` exports captured
verification outcomes, including failed candidates that were never published.
A candidate identifier is `identity(frozen owner inputs)`, not a published root
assertion. Python APIs are `export_generation(provenance, selection)` and
`export_candidate(provenance, candidate_id)`.

The generation export context binds canonical generation ID/record and root
inventory digest. It is explicitly a **post-build inspection**, not a retrofit of
pre-execution evidence. Import this envelope as a producer artifact in build-record
or expose it read-only in build-trace; do not invent a canonical record kind until
build-record owns that schema. Existing canonical generations remain unchanged.

## Named verification

For newly executed installed checks under `image-build-installed-verification-v1`,
`seed_build.verify` captures terminal outcomes automatically. The stable logical
ID is `image-build/<frozen verification_check>/command/<ordinal>`; absent check
names use the existing `installed-trust` default. Identity is scoped to a named
command check, not each individual upstream test hidden inside its shell command.
Recipe authors must preserve logical names and ordinal meaning; a new logical
check requires a new name. Compare `definition_digest` separately: a recognizable
logical check can change its command definition between generations.

Each observation includes a content-derived `id`, check ID, command-definition
digest, candidate generation and exact root inventory, host/project/attempt
identity, command sequence, execution identity, policy digest and evidence refs.
`PASS` means a cleaned-up exit 0; `FAIL` means a terminal nonzero exit; `ERROR`
means a terminal signal/timeout/controller fault/cancellation. Pending/unknown
execution produces **no terminal observation**. `SKIP` is reserved by the schema;
this producer does not currently emit it. Absence never means SKIP or test removal.
Sequence orders commands within an attempt. New captures freeze an `observed_at`
timestamp for observation ordering, explicitly distinct from execution time.
Execution timestamps are null
when not present in owner evidence; consumers must not invent chronology from
hash IDs or filenames. Canonical attempt/job records provide further ordering.
Historical report projections have null observation time; no historical timestamp
is manufactured.

Material is retained in the existing build-record artifact store. A descriptor
is saved beside the verification attempt and indexed by candidate identity under
`build-record/observation-index`. Consumers use the export API, not that layout.
Repeated capture reuses exact bytes; a conflicting outcome for a saved command
fails closed. Runtime IDs, invocation IDs, journal references and build-trace
references identify execution evidence; log contents are not copied into reports.

Existing canonical installed-verification reports can be projected to PASS
observations without claiming new pre-execution capture. Their descriptor and
canonical generation remain evidence. New captures take precedence for the same
check/invocation; conflicting outcomes are rejected. Legacy generations without
named reports carry an explicit gap. Initial coverage excludes package upstream
suite subcases and anonymous old verification jobs.

## Artifact and package relationships

ELF inspection emits `needs-library` (DT_NEEDED), `provides-soname` (DT_SONAME),
and `elf-interpreter` (PT_INTERP). Shebang inspection emits `script-interpreter`
and preserves the optional argument. `/usr/bin/env python3` reports `/usr/bin/env`
plus its argument; it does not resolve the command using the inspection host PATH.
Subjects include installed path, content SHA256 and matching package owners.
Symlinks are not followed. Missing readelf, malformed ELF, inspection limits and
unsupported shebangs produce explicit gaps. Readelf executable digest identifies
the inspection implementation. No loader search, dlopen, RPATH resolution, ABI
judgment or service analysis is claimed. An empty relation list is not proof of
no dependencies: consumers must inspect coverage/gaps.

Frozen recipe dependencies produce `declares-build-dependency`,
`declares-test-dependency`, and `declares-runtime-dependency`. Canonical resolved
input bindings independently produce `used-build-output`, retaining exact output
record references. Declarations and resolved build inputs are not interchangeable.

## Sources

Each source observation identifies package/project (where recorded), exact output,
build-input and source-selection records, monthly pin, archive name/hash/size,
frozen download declaration, and upstream repository/revision declarations.
`revision_type` distinguishes full Git commits, explicit tags, opaque strings and
unknowns. Explicit `tag` is now supported in source-provenance.py and exported in
`release_tags`; opaque values are not guessed to be tags. Canonical build-record's
current narrower upstream fields remain unchanged; the complete declaration is
retained in frozen recipe bytes. Unknown origins remain unknown.

Archive bytes are authoritative. Repository/revision association is a reviewed
metadata declaration, not independently verified reproduction from Git. No current
catalogue origin is substituted for legacy records. Patch records remain in the
canonical closure; this export does not interpret patch semantics.

## Identity and evolution

Schema names ending in `v1` are the dispatch key. Reject unsupported versions.
IDs are `sha256:` plus image-build `identity(payload-without-id)` (sorted compact
JSON, Python's default ASCII escaping). Reference strings and artifact descriptors
retain build-record's own contract. Producer implementation digest covers the
three observation modules. Required structures are described by JSON Schema;
opaque canonical references are validated by the owning build-record reader.

This version is sufficient for early consumer development, not exhaustive test
coverage or a complete dependency graph. Further observations should use explicit
new schema versions or separately dispatched observation types.
