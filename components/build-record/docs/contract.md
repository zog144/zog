# Build provenance contract, schema 1

Status: experimental schema-1 contract, build-record 0.7.2. Implementations must
reject unsupported versions and unknown fields. Coordinate incompatible changes
with consumers and introduce a new schema version; never reinterpret old records.
`zog.build_record.model.validate` is the executable schema. This document specifies
semantics. `Record` is the Python envelope type; payloads are validated dictionaries.

## Encoding and identity

A record has exactly `schema_version: 1`, `kind`, `data`, and `gaps` (a list of
nonempty reasons, empty when no known gaps). Its ID is `sha256:` followed by the
lowercase SHA256 hex digest of its canonical bytes. IDs are external to the record.

Canonical bytes are Python-compatible sorted-key compact ASCII JSON:
`json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
allow_nan=False).encode('ascii')`. No final newline. Object keys are strings;
arrays retain order. Unicode is not normalized; lone surrogates are rejected.
Floats, NaN/infinity, duplicate JSON keys and integers outside ±(2^53−1) are rejected.
Depth is at most 32. This is a Zog encoding, not a claim of compliance with a
separate JSON canonicalization standard. Reordering an array changes identity.
Producers should keep source/dependency inventories in stable order.

One record is at most 1 MiB canonical JSON. One bundle is at most 32 MiB and 10,000
records. JSON readers check bytes before parsing; nesting limits are also checked.
These bound serialized data, not exact Python memory. Artifact bytes are streamed
separately and are not subject to the metadata byte cap.

An artifact descriptor has exactly `{name, digest, size}`: a nonempty descriptive
name, a SHA256 byte digest, and nonnegative integer byte count. Names are not paths
to open. Recipe/build-root manifests are themselves artifacts; their digests bind
the bytes of those manifests. A digest of a manifest does not automatically verify
all files mentioned inside it. Producers must define and retain their inventories.

## Records

All listed fields are required. Nullable fields are explicitly identified.

| Kind | Data fields |
|---|---|
| `source-selection` | `package`, `pin`, `upstream`, `archives` |
| `build-inputs` | `package`, `step`, `purpose`, `sources`, `recipe`, `patches`, `target`, `options`, `environment`, `materials`, `dependencies` |
| `attempt-start` | `attempt_id`, `inputs`, `prepared_at`, `retry_of` |
| `attempt-result` | `attempt`, `outcome`, `finished_at`, `jobs`, `traces`, `outputs`, `summary` |
| `package-output` | `package`, `attempt`, `artifacts` |
| `generation` | `generation_id`, `assembly_result`, `packages`, `artifact`, `content_manifest`, `verification` |
| `generation-observation-snapshot` | `generation`, `generation_id`, `root_inventory_digest`, `observations`, `record_set_digest` |
| `source-repository` | `location`, `normalization` |
| `source-reference` | `repository`, `kind`, `value` |
| `source-archive` | `digest`, `size` |
| `source-archive-association` | `archive`, `reference`, `relationship`, `producer` |
| `source-provenance` | `producer`, `producer_observation`, `package`, `project`, `output`, `build_inputs`, `source_selection`, `archive`, `associations` |
| `relationship-observation` | `producer`, `producer_observation`, `subject`, `relation`, `target`, `evidence` |
| `verification-check` | `producer`, `check_id`, `definition_digest`, `granularity` |
| `observation-coverage` | `producer`, `subject`, `family`, `collector`, `scope`, `outcome`, `observation_count`, `details` |
| `verification-execution` | `producer`, `producer_observation`, `check_id`, `definition_digest`, `subject`, `attempt_id`, `sequence`, `outcome`, `execution`, `environment_digest`, `evidence`, `granularity`, `timing` |

### Source selection

`package` is the source-project/package identity, not an application or runtime.
`pin` has `month` (YYYY-MM-01), `repository`, exact full Git `revision`, repository
`path`, and SHA256 `digest` of the original monthly pin file's bytes. Corrections
within a month change revision/digest. Do not substitute a normalized Python
literal digest for the pin file byte digest.

`upstream` is a nonempty array of `{repository, revision}`. Git revisions are full
40- or 64-character lowercase hex values. An unknown upstream revision may be
null only with an explicit record gap. This supports existing source-release
archives without inventing commit identities. `archives` is a nonempty array of
artifact descriptors for the actual consumed archives/additional source bytes.
Capture sizes after obtaining bytes. The library neither executes pin files nor
fetches sources. Retrieval locations belong to archive-mirror, keyed by digest.
A producer may use one source-selection per consumed archive to bind each explicit
upstream declaration unambiguously. Archive hashes do not authenticate a Git
relationship. Unsupported revision types must remain null with a gap; preserve
original identifiers in retained recipe materials rather than guessing Git from
hexadecimal syntax. Never enrich historical records from current declarations.

### Build inputs

`step` identifies the recipe stage (for example `final` or `temporary-libstdcpp`).
`purpose` is `package` or `assembly`. Package inputs require at least one
`source-selection` reference; assembly inputs may have none. All referenced
source selections must agree with the package identity.

`recipe` is one descriptor for a retained resolved recipe manifest/bundle, including
all recipe files, generated commands and code affecting execution; hashing one
entry-point filename is insufficient. `patches` lists patch descriptors in declared
application order; reordering changes input identity. Descriptors identify retained
bytes, not proof that commands applied them. A partial classification requires a
gap even when some patches are captured. Recovery must retain these frozen inputs;
missing bytes do not authorize substitution from newer recipes or sources. `target`
is the declared target platform. `options` is a string mapping for build-affecting
settings. `materials` is a nonempty list of descriptors identifying toolchain,
build root or bootstrap environment, assembler implementation, additional inputs
and relevant license metadata. There is no universal toolchain discovery.

`dependencies` is a list of `{output, result}` bindings: a `package-output` ID and
its successful `attempt-result` ID. For legacy output only, result is null. The
same binding shape is used by a generation's `packages`. Inspection checks that
results succeeded and actually name their output, including transitive dependencies.
A generation currently permits one installed output per package identity; bootstrap
stages are dependencies, not duplicate installed package entries.

`environment` is a string mapping limited to CC, CXX, CFLAGS, CXXFLAGS, CPPFLAGS,
LDFLAGS, LANG, LC_ALL, TZ, SOURCE_DATE_EPOCH, PATH and MAKEFLAGS. This is an allowlist,
not a secret detector. Producers must avoid credentials in values, options, recipe
manifests and summaries. Uncaptured relevant environment needs an explicit gap.

### Prepared attempts, results and recovery

`attempt_id` is an immutable globally scoped owner identity, including host/project
scope where necessary. It is distinct from the content hash and from mutable titles.
`inputs` references frozen build inputs. Persist this record and its ID in owner
state before dispatch. `prepared_at` and `finished_at` are UTC timestamps in
YYYY-MM-DDTHH:MM:SS[.ffffff]Z form. Results cannot predate preparation.

`retry_of` is null or the **previous attempt-result ID**, preserving failed history
and evidence in exports. A retry uses a new owner identity and new prepared record;
it may select changed inputs, which remain visible. Recovery reuses the original
prepared record and must not silently select current pins/recipes/toolchains.

A result references its `attempt-start` via `attempt`. `outcome` is succeeded,
failed, cancelled or uncertain. Only succeeded results may have `outputs`, and
must have at least one output. A failure's diagnostic artifacts belong in trace
retention, not accepted package outputs. `summary` is an owner-supplied explanation.
`jobs` contains `{host_id, job_id}` locators; `traces` contains `{host_id, build_id}`
locators compatible with build-trace's scoped build IDs. Empty arrays are allowed
for owners without such facilities; missing expected capture must appear in gaps.
Locators do not authorize access or prove current availability. Retained trace
export bytes may be included as artifact descriptors in the producing output.

One result per attempt is accepted within the inspected graph; conflicting results
or different prepared bindings for one attempt identity are errors. The immutable
store alone does not enforce a global owner-ID uniqueness index. Owners must
serialize finalization and persist the selected record IDs. Export roots must
include all relevant records when auditing independent branches of attempt history.

An uncertain result records unresolved execution; it does not authorize redispatch.
Later resolution/correction records are deferred to a versioned extension. Do not
rewrite an uncertain result as success. First-pass recovery supports continuation
of a prepared binding and explicit uncertainty, not an uncertainty-reset workflow.

### Outputs and generation assembly

A package output binds its package identity, producing `attempt-start`, and nonempty
artifact list. The start reference avoids a result/output hash cycle. The result
then references the outputs, and consuming inputs/generations reference both.
Legacy output uses null `attempt` and must include a gap explaining missing history.
Never label a pre-existing output with today's recipe or monthly pin.

A generation's `assembly_result` must be successful and derive from inputs whose
purpose is assembly. Its dependency bindings must exactly match `packages`.
`artifact` and `content_manifest` must appear in the assembly's output artifacts.
Assembly covers installation order, configuration, generated files, deletions and
other final-tree changes, not merely package compilation. `verification` contains
retained report descriptors; checking report bytes does not interpret or endorse
its test results. `generation_id` remains the owner's immutable identity.

Keep the final artifact digest outside that artifact. An embedded manifest may
carry input references but cannot contain its own final archive hash. This version
identifies exact archive bytes plus a separately defined content inventory; it
provides no generic directory hashing algorithm.

### Source-development provenance

The original `source-selection` kind remains unchanged. It records the exact monthly
selection used by existing image-build adapters and continues to accept only a full
Git revision or an explicit unknown with a gap. New source-development records add
richer facts without reinterpreting those persisted records.

A `source-repository` stores the producer's exact repository literal under
`normalization: exact-literal-v1`. Build-record performs no URL rewriting, case
folding, suffix removal, redirect following or alias inference. Two different literals
are different repository identities until a future explicit alias/equivalence fact
says otherwise.

A `source-reference` points to a repository and classifies one upstream identity as
`git`, `tag`, `opaque` or `unknown`. Git requires a full lowercase revision;
tag and opaque values are preserved literally; unknown has a null value and a declared
gap. A tag is not coerced to a commit, and a hex-looking opaque value is not guessed to
be Git.

A `source-archive` identifies exact retained bytes by SHA256 and size only. Archive
filenames and download URLs do not define that byte identity. The selected filename,
monthly pin and consumed archive descriptor remain available through the referenced
`source-selection`. Frozen download declarations remain retained producer evidence;
a mirror move or URL change must not rewrite the archive/repository/reference records.

A `source-archive-association` connects one archive-byte record to one typed source
reference and states **how** that relationship is known. The initial image-build
adapter accepts only `declared-not-independently-reproduced`. This is a reviewed
metadata declaration, not proof that checking out the reference reproduces the archive.
Multiple declared upstream identities for the same archive are parallel facts, not a
conflict. The association records the producer contract but not one observation ID, so
an unrelated download-location change does not rewrite the semantic relationship. The
enclosing `source-provenance` record preserves the exact producer observation that
asserted it. Future source-attestation/reproducibility evidence should use stronger,
versioned facts rather than rewriting these declarations.

A `source-provenance` binds the producer observation to package/project identity,
the exact existing package output, build inputs and source selection, the archive-byte
record and all archive/reference associations. Inspection verifies that the output was
produced from those inputs, that the selection is one of those frozen inputs, and that
the archive digest/size occurs in that selection. Producer source gaps remain attached
to the binding. This yields a durable traversal from package/project through exact
repository/reference/archive facts into the existing build provenance graph.

### Typed relationship observations

A `relationship-observation` preserves one image-build v1 relationship row and its
producer observation identity. The initial vocabulary is closed to:

- `needs-library` and `provides-soname`;
- `elf-interpreter` and `script-interpreter`;
- `declares-build-dependency`, `declares-test-dependency` and
  `declares-runtime-dependency`;
- `used-build-output`.

The first four relations use an installed artifact subject containing absolute path,
byte digest and sorted package-owner names. SONAME relations target a literal SONAME.
Interpreter relations target an absolute path. ELF observations retain the exact
`readelf` executable digest used by image-build; shebang observations retain the
literal optional argument but do not resolve `/usr/bin/env` through any PATH.

Declared package dependencies use a package subject bound to its exact canonical
`package-output`, a package-name target, and the frozen dependency recipe artifact as
evidence. They are declarations only. Build-record does **not** add an edge from a
declared package name to a package output, infer which output satisfies a SONAME, claim
ABI compatibility, resolve interpreter paths, or convert package ownership into a
runtime dependency.

`used-build-output` is different because it is already a deterministic canonical
fact. Its subject is the consuming package output, its target is an exact
`package-output` record, and its evidence is an exact `build-inputs` record.
Inspection requires that evidence to be the consuming output's prepared inputs and
requires the target output to occur in those inputs' dependency bindings. Target
package identity must agree with the referenced output.

Published-envelope validation also requires package relationship subjects to be the
installed output for that package in the generation. Artifact owner names must be a
subset of installed generation packages. These checks bind producer observations to
the canonical generation without adding the generation ID to the relationship record;
the same immutable relationship fact may therefore be reused by multiple snapshots.

Relationship records do not imply observation completeness. A generation with no
`needs-library` rows cannot be interpreted as having no library requirements until
a separate coverage record says the relevant scope was successfully examined. Coverage
is the next versioned foundation.

### Verification checks and observation coverage

A `verification-check` is the immutable definition identity for one logical named
check version. It contains the stable logical `check_id`, a separate
`definition_digest`, granularity and producer contract. It has no generation or
execution identity. Therefore one logical check may have several definition records
over time, and one definition may be executed repeatedly across generations.

Image-build generation exports may carry explicit check rows and terminal executions
through independent capture paths. Build-record accepts both and canonicalizes the
union of distinct definitions. Candidate verification exports can likewise derive
check-definition records directly from their terminal execution observations.
`verification-execution` is intentionally left unchanged, preserving its existing
canonical identity; snapshots can include matching check-definition records without
rewriting old executions.

An `observation-coverage` record answers whether a particular observation family was
actually collected for an exact generation-candidate/root-inventory subject. It binds
producer contract, collector implementation digest, controlled observation family,
declared scope, explicit outcome, observation count and producer-derived details.

Coverage outcomes are `complete`, `partial`, `unavailable`, `not-performed`,
or `not-applicable`. `complete` is always relative to the declared scope. A
complete record with `observation_count: 0` means the declared scope was examined
and no matching observations were found; it is not equivalent to missing collection.

The initial image-build v1 adapter emits six families:
`verification-commands`, `elf-interfaces`, `script-interpreters`,
`declared-package-dependencies`, `used-build-output`, and
`source-provenance`. Named verification remains partial by design because upstream
subtests and anonymous legacy jobs are explicitly outside its scope; it becomes
unavailable only when the producer reports no canonical named verification report and
no named definition/execution is available.

ELF coverage is unavailable when ELF files exist but readelf is unavailable; per-file
readelf timeout/failure makes it partial. Script coverage is partial for
unsupported/non-UTF8/non-absolute shebangs. Declared package dependency coverage is
partial when a frozen dependency declaration is missing or a legacy output prevents
recipe inspection. Exact used-build-output and source-provenance coverage become
partial when legacy outputs prevent canonical input/source inspection.

Unknown upstream revisions are provenance-content gaps, not collection-coverage
failures when the source observation itself was successfully captured. Similarly,
unsupported areas such as `dlopen`, ABI compatibility, service dependencies and
env-PATH resolution remain explicit scope exclusions rather than silently becoming
negative observations.

Coverage status is separate from record/reference integrity, evidence-byte
availability, provenance completeness and verification outcome. Therefore
`inspect().complete` still means that the reachable metadata closure has no missing
records or declared record gaps; it does not mean every coverage family is complete.

Image-build candidate-verification v1 has no generation-wide root inventory when
there are no results, so build-record does not fabricate candidate coverage from its
free-form coverage string. Candidate check definitions and terminal executions remain
canonicalizable independently.

### Verification executions

A `verification-execution` is an immutable terminal observation supplied by a
versioned producer contract. The initial adapter accepts image-build's
`image-build-verification-observation-v1`: logical `check_id`, separate
`definition_digest`, exact generation-candidate subject, attempt/sequence,
PASS/FAIL/ERROR/SKIP outcome, execution identity, environment digest, evidence and
producer timing. Repeated executions are separate records; a changed definition does
not silently create a new logical check identity.

`producer_observation` preserves the producer's own content identity. The canonical
record deliberately does **not** contain a canonical generation-record reference.
Image-build can capture a check while the root is still a candidate, and later publish
that same candidate as a generation. Adding publication state to the execution would
change its canonical identity. Instead, the subject retains the immutable owner
generation identity and root-inventory digest. The published-generation adapter checks
those fields against the supplied canonical generation closure before canonicalizing
the execution. Candidate ingestion needs no fabricated generation record.

Timing fields may be null when owner evidence does not establish them. Non-null times
must be explicit UTC timestamps; build-record preserves their original representation.
Observation time is not execution time. Evidence objects remain producer-owned
references and facts; this record does not claim their current availability or parse
journal text. Coverage and absence semantics are intentionally separate work.

### Generation observation snapshots

A `generation-observation-snapshot` is the stable read-only boundary intended for
cross-generation consumers such as integrate-observe. It contains the canonical
generation record ID and owner generation identity, the exact root-inventory digest
observed by the producer, categorized canonical observation record IDs, and a
`record_set_digest`.

The observation categories are fixed in schema 1:

- `verification_checks`;
- `verification_executions`;
- `relationships`;
- `source_provenance`;
- `coverage`.

Each list is sorted, contains unique canonical IDs, and references only the matching
record kind. No record may appear in two categories. `record_set_digest` is SHA256
over canonical JSON containing the generation record ID and the sorted flat set of all
included observation IDs. It identifies the exact included canonical record set; the
snapshot record ID additionally binds the owner generation identity, root-inventory
digest and category assignment.

Snapshots are append-only observations, not generation mutations. If snapshot S1
contains generation G plus records A/B/C and later verification record D becomes
available, the correct representation is a new snapshot S2 containing A/B/C/D.
Generation G, S1 and A/B/C retain their identities. S1 remains a valid statement of
what was included at that point; S2 does not supersede it by mutation.

Graph inspection requires snapshot verification executions and coverage records to
carry the same owner generation and root-inventory subject as the snapshot. Every
included verification execution must have a matching included
`verification-check` definition. Included source provenance must point to an output
installed by the generation. Package relationship subjects must use the installed
output for that package, and artifact relationship owner names must belong to the
installed package set.

Relationship observations intentionally do not carry a generation identity. Snapshot
membership is the publication-time assertion that those already-canonical interface
facts belong to this observed root. Build-record cannot independently prove an
artifact path/digest occurred in a rootfs because schema 1 has no canonical per-file
root inventory record; the image-build adapter therefore validates the producer
envelope and root-inventory binding before constructing the snapshot.

Snapshots may contain empty observation categories. This supports accurate legacy or
incomplete generations without inventing observations. Absence of a coverage record
still means coverage is unknown; consumers must never turn an empty category into a
negative fact by inference.

The generic `generation_observation_snapshot()` constructor knows no image-build
storage layout. `ingest_image_build_snapshot()` is an adapter convenience: it
validates one image-build v1 generation envelope, canonicalizes all supported source,
relationship, check, execution and coverage facts, and returns dependency-first new
records with the snapshot last. The original generation closure is supplied
separately and remains unchanged.

Snapshot **persistence** and owner **publication** are separate operations. The intended
production sequence is: the canonical generation exists; image-build produces a
versioned observation envelope; the build-record adapter validates it against that
generation closure; canonical observation records are constructed; image-build calls
`Store.put()` for returned records in dependency-first order; the snapshot is
persisted last; then image-build durably records that snapshot record ID in owner state.
Only that final owner-state binding makes the snapshot discoverable as owner-selected
or current for that image-build lifecycle.

`Store.put(snapshot)` is idempotent immutable storage only. It does not select the
snapshot, publish it, order snapshots, update the generation, or make a multi-record
transaction. If interruption occurs after canonical records or the snapshot are stored
but before owner publication, image-build must recover idempotently and bind the same
prepared snapshot identity rather than scanning the store for a plausible newest
record. Later observations create another immutable snapshot and require a separate
owner publication decision. Build-record never chooses a preferred/current snapshot
and never infers chronology from snapshot hashes or store enumeration.

## Bundles, inspection and verification

Bundle shape: `{schema_version: 1, roots: [record_id, ...], records: {id: record}}`.
Every supplied record is validated and hash-checked; semantic relationships are
checked in the graph reachable from roots. Unreachable records are not evidence
for those roots. `Store.bundle` exports the reachable closure and fails if a record
is missing; imported bundles may be incomplete and `inspect` reports missing IDs.
The export is self-contained metadata only. It does not embed archives, logs or
recursively copy bytes referenced by external manifests.

Inspection includes root `subjects` with package names/input references and `evidence`
with captured job/trace locators and explicitly unchecked availability.

Inspection reports reference closure, declared gaps and observation coverage as
separate concepts:

- `reference_closure_complete` is true exactly when every canonical record reference
  reachable from the supplied roots is present. `missing_record_count` and
  `missing_records` expose missing IDs. Wrong-kind or inconsistent references remain
  validation errors rather than an incomplete-closure status.
- `declared_gap_free` is true exactly when no reachable canonical record contains
  declared `gaps`. `declared_gap_count` counts individual declared gap reasons and
  `declared_gap_record_count` counts records carrying one or more reasons.
  `declared_gap_summary` repeats those totals plus bounded counts by canonical record
  kind. The existing `gaps` array remains the detailed source, with exact record IDs
  and reason strings. Schema 1 has no structured gap-code field, so build-record does
  not invent categories by parsing prose.
- `coverage` is the independent projection of canonical `observation-coverage`
  records. A partial/unavailable/not-performed collector outcome is not a missing
  canonical reference and is not automatically a declared record gap.

The compatibility field `complete` keeps its original meaning and is exactly
`reference_closure_complete and declared_gap_free`. Callers that mean graph/reference
closure must use `reference_closure_complete`, not `complete`.

None of these fields means a build succeeded, records are truthful, bytes are
available, tests passed, signatures are valid or a rebuild would be bit-for-bit
identical. An attempt-start root alone says only that preparation was recorded.
Consumers must inspect the appropriate result/generation and coverage facts.

`verify_artifacts` accepts an explicit digest-to-local-path mapping. It never opens
paths or URLs named by a record. Reports distinguish verified, mismatch, unavailable
and not-provided. Files are streamed and checked against recorded hash and size;
observed metadata changes during the read are errors. The pin file has a byte hash
but no separately captured size. Trace job/log availability remains unchecked;
there is no automatic network/controller adapter. SHA256 supplies integrity against
an expected digest, not authentication of the producer.

`compare` requires complete references and one generation root on each side. It
reports added/removed/changed package outputs, changed top-level input fields, an
assembly-input change flag and declared gaps. It does not expand recipe manifests
or compute a rootfs file diff. Reused inputs with a new attempt remain distinguishable.

## Durability, retention and trust boundary

The store is a trusted owner-controlled POSIX directory. Each record is written to
a temporary file, fsynced, linked without overwriting its digest filename and the
directory fsynced. An existing record is revalidated on idempotent insertion.
I/O failure must block owner progress; reopening and retrying the same record is
safe. A crash may leave an unreferenced temporary file; no automatic cleanup or
multi-record transaction exists. The owner must durably provision the store's
parent directories before use. Reads reject record symlinks, but the store is not
a filesystem sandbox against concurrent hostile local writers.

Persist records in dependency order and write the owner's published generation
pointer last, after closure validation and artifact verification. Retained generations
must protect their record closure and required sources/materials. Owners implement
retention; this library deletes nothing. Logs may use a separate policy with loss
reported honestly. Signing, public attestations, policy certification, global query
indexes and producer integrations are outside this first pass.
