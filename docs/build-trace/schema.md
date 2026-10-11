# Inspection schema 1

Every successful object includes `schema_version: 1` and `kind`. CLI output and
Python return values are the same JSON-compatible dictionaries. New optional fields
may be added; incompatible meaning changes require a new schema version.

## Facts and identities

A fact has `value`, `origin` and `source`. Missing facts have a `reason`.

| Origin | Meaning |
|---|---|
| captured | Read from the named owner record; not reconstructed from current inputs |
| derived | Deterministic projection, such as request-ID-to-job-ID or an inventory digest |
| imported | Existing artifact-reuse receipt; does not claim fresh execution |
| missing | Unavailable/not captured; outcome may use the explicit string `unknown` |
| redacted | Value deliberately withheld; never substitute it for an absent value |

`source` is relative to `state/image-build`, or `box-control:job:<id>`.
A missing field's source names the expected record; it does not prove the file exists.
Inventory `record_digest` hashes canonical sorted-key compact ASCII JSON of the
retained inventory. It is a build-trace summary digest, not an owner artifact ID and
not a verification that current output bytes still match that inventory.

Host scope is caller supplied. Build display locators reuse attempt/pipeline names.
Command display locators use their retained relative stems. Job ID derivation uses
the existing controller schema-1 request hash. Request/job and command bindings are
checked; inconsistent owner records are errors. These locators never authorize
recovery or resubmission.

## Objects

| Kind | Contents |
|---|---|
| build-list | `items`, `next_cursor`, `has_more`; IDs, package/phase title, preview, owner status |
| build | status/error/generation facts, pipeline inventory summary, package input/output/reuse facts, paged `commands` |
| command | argv, optional inline shell body/interpreter, cwd, allowlisted environment, execution settings, job and execution identity, outcome, gaps |
| logs | job/build/host scope, entries, controller cursor, availability, owner status |
| comparison | structured input/settings/command differences keyed by package or command locator; unavailable fields |
| export | one bounded build inspection, schema and provenance; no journal entries |
| error | `error.code` and safe `error.message` |

Execution outcome stays separate from completeness. Currently all build summaries
are `partial`: start timestamps, version/source projections and individually captured
child commands are incomplete. A retained completion can establish success/nonzero
exit after controller pruning. A missing completion or a prepared request alone
cannot establish execution. Controller observations are read without refresh.

Package order is directory order; within a directory it is prepare, configure,
build, test, install and numeric index. Unknown legacy phases are grouped last.
Fixture directories remain distinct. This is semantic grouping, not wall-clock order.

## Journal availability

| Value | Meaning |
|---|---|
| available | Owner returned a valid page (possibly no new entries after a cursor) |
| pending-or-empty | Empty history with a recorded prepared/starting/running state |
| empty-or-expired | Empty initial history; retention loss versus no output is unknown |
| cursor-expired-or-unavailable | Owner cannot find the continuation anchor |
| identity-unavailable | No established job/journal identity |
| not-configured | No controller reader configured |
| retrieval-failure | Owner unavailable or read failed; no execution conclusion |

Owner cursors are passed unchanged and remain bound to project/job/boot/invocation.
The first page is a tail read. A failed page never advances the incoming cursor.
No claim of whole-journal completeness is made.

## Pagination and limits

List/command pages use deterministic keyset cursors bound to host, project,
authorized build set and query filters. Cursor encoding is not an authorization
credential. Cross-scope cursors are rejected. Concurrent insertion before a consumed
key is not included; status changes between pages are not a snapshot. Restart from
the first page to observe the latest full set. No persistent index exists; every
request rebuilds its projection from owner records, with no ingestion side effects.

Defaults: 1–100 entries per page; 4096-character cursor; 1 MiB JSON response;
16 MiB per source record; 256 MiB cumulative image-build source bytes for deep
inspection; 16 MiB cumulative source bytes and 100 candidate builds for list pages;
10000 visited records and entries per directory. Source bytes count the image-build
JSON bytes read in this request, not the response size or controller/journal traffic.
`InspectionLimits` configures the file/source/list/record/scan budgets with positive
integers. Service code must choose budgets, not trust arbitrary remote request values.

Listing scans candidate IDs in order and returns a cursor after the last completely
examined candidate. It may return an empty page with `has_more: true`, when a sparse
filter reaches its scan budget. A source budget reached after progress returns a
continuation; the unfinished candidate is retried on the next page, never skipped.
A candidate too large to inspect on its own returns an actionable error. Integrity,
malformed-record and concurrent-change errors are never treated as pagination.
`has_more` means candidates remain, not that another match is guaranteed. A final
empty page is therefore possible. Root directory enumeration remains bounded by
the record limit; raising it may be necessary for more than 10000 attempt names.

List cursors from version 0.1.0 are rejected; restart listing after upgrading. Version
0.2.0 cursors bind the same scope and filters. Changing limits between pages is allowed.
`command_count` remains the whole attempt's recognized command count, deduplicated by
record stem. `matched_command_count` describes the filtered commands on a list row.
Previews are at most eight argv entries, each at most 512 characters, with an explicit
`command_preview_truncated` flag; exact argv remains in command inspection.

`inspection` reports source bytes, visited records and effective budgets. List pages
also report scanned builds and why scanning stopped. `TraceError.details` and CLI
`error.details` identify the exhausted budget, relative source record and needed bytes
when known. These are diagnostic facts, not additional filesystem read authorization.
Source records must be regular files. Directory traversal and symlink following
beneath the configured evidence root are refused. Files replaced during a request
produce `concurrent-change`; retry that read, never a build. Cross-owner consistency
cannot be atomic; source checks do not prove a live job state has not since changed.

Comparisons/exports fail if they exceed response limits. Exports also fail rather
than silently truncate beyond the command limit. Use command pages for larger builds.

## Redaction, retention and failure handling

Environment values are allowlisted in `model.ENVIRONMENT`. Other values have explicit
redacted markers. Known credential formats, secret-bearing assignments/flags and URL
passwords are filtered from text. This is a presentation safeguard, not a universal
secret detector. Arbitrary stdout or shell text may contain unrecognized secrets.
No raw environment is persisted by build-trace. Existing owner records may predate
redaction and are never rewritten by inspection. Review exports before sharing.

There is no trace retention task. image-build retains command/preparation/completion
records across normal workspace cleanup; box-control may prune released history,
and journald has independent retention. Build-trace neither pins nor deletes them.
Retained generation provenance policy remains owner-side work; no 25-entry runtime
default is applied here. Version 0.3 optional owner records add pre-persistence filtering.

Library errors raise `TraceError(code, message)`. CLI operational errors are JSON on
stdout: exit 2 invalid query/cursor, 4 absent or unauthorized build/command, 3 all
other operational errors. Argparse syntax/help retain conventional stderr/stdout.
Codes include `invalid-record`, `integrity-error`, `unsupported-schema`,
`source-unavailable`, `concurrent-change`, `source-too-large`, `response-too-large`,
`export-too-large` and `dependency-unavailable`. Raw exception text is not exposed.


## Selective reads and layout support (0.2.0)

Lists never read package `prepared.json`, `result.json` or artifact inventories.
Package/phase filters are applied to command views before reading command checkpoints,
completion records or controller state. Package aliases in views remain supported.
Unfiltered/status-only listing also considers pipelines without attempts; those
pipeline JSON records remain individually bounded and may carry recipe inventories.
Package/phase queries skip pipeline candidates, which have no command-level match.

Direct command and log reads validate the requested attempt and allowlisted command
path shape, then read only that command's view/checkpoint/completion. They do not scan
pipelines, sibling commands or package inventories. Full build details resolve a
pipeline from retained attempt status or command views. If neither records the link,
`pipeline_id` remains unknown; there is no global scan to guess it. Cross-record
pipeline conflicts still fail full inspection.

`layout.status` is `supported` or `unsupported-layout`. An unrecognized attempt
without normal engine evidence has `command_count: null`, rather than a claim that
nothing ran. Known `*-launch.json`/`*-job.json` filenames are reported (at most 20),
without reading their contents or inferring jobs/results. Direct command lookup on
an unsupported attempt raises `unsupported-layout`. Mixed layouts expose diagnostic
receipt filenames but currently project only recognized engine commands.
`retry_relationships` is explicitly missing until image-build supplies an owner-defined
record. No relationship is inferred from a filename, timestamp or successful job.

`shell_parsing` distinguishes `captured`, `not-shell`, `no-inline-script`,
`unsupported-options`, and `missing-command-string`. Recognized shell options are
parsed only until the script/file operand; later positional arguments cannot be
mistaken for `-c`. Shell argv is always preserved. `script.reason` records an unavailable
parse state; a recognized interpreter can be present even if parsing is unsupported.
No shell body or recipe is executed by this parser.

## Integration additions (0.3.0)

The response remains schema 1 with additive fields. Optional image-build schema-1
`.trace.json`, `.summary.json`, `.observation.json` records are recognized alongside
legacy records. Their maintained owner contract is `image-build/docs/build-trace-contract.md`.
Command names use captured titles when available and clearly marked derived labels
otherwise. `category` distinguishes build/diagnostic/retry/unknown. `provenance`
exposes the owner's captured recipe/input/source identities, without deep inventory
reads. The new owner capture includes the pipeline pin-set identity when present, or null
for older records without one; versions are not guessed.

`relationships` contains explicit `retry-of`/`diagnostic-of` links to exact command
or job identities. Build-level `retry_relationships` gathers at most 32 links with a truncation flag;
command pages retain individual links without changing original statuses. Missing relationships differ from a captured empty list.
Imports retain imported provenance. Old arbitrary receipt filenames remain
unsupported until the owner explicitly imports verified facts. Referenced targets
are not fetched; no cross-attempt authorization or automatic traversal occurs.

`request_id`, `observation_source`, `observed_at`, `completion_available`, `evidence`,
`recovery` and `failure_summary` are additive command fields. Evidence items have
kind/reference/availability: available/missing for files read by this request,
not-checked for external job/journal/receipt references. These are scoped locators,
not download URLs. Package evidence includes preparation, result and reuse records.
The journal API separately determines current log availability. A durable journal
reference does not guarantee retention or allow logs to bypass the controller.

Live read-only controller observations take precedence. Without a live record,
retained execution completion establishes the result independently of cleanup;
retained controller observations supply additional identity and failure information.
An earlier retained running observation cannot hide a later runner completion.
`observed_at` refers to the retained observation, not the current live read.
Conflicting request/job bindings or terminal completion identities are errors.

Failure summaries separate submission (established/prepared-only/not-established),
execution (established invocation/not-established), outcome and cleanup. Established
submission alone is not evidence that a process ran. Unknown does not mean failure,
never-ran or success. Owner errors in command summaries are redacted then limited to
2048 characters with `owner_error_truncated`; full owner error facts remain bounded
by the response budget. Build summaries include at most 20 failed/unknown command
summaries and an explicit truncation flag; command pages provide individual details.

Recovery statuses describe the observation: complete means process cleanup was
confirmed; pending means it was not complete; blocked means the owner reported an
unknown outcome/state requiring reconciliation; unknown means insufficient owner
cleanup evidence. `resources_released` remains a separate fact. Complete never
means success, acceptance, promotion, or permission to resume. Historical records
may be stale after a crash/reboot. Inspection performs no refresh/reconciliation,
replay, submission, cancellation or cleanup. Only the owner can resolve ambiguity.

New owner records are capped at 256 KiB each. Existing configurable 256 MiB deep,
16 MiB list, 16 MiB file and 1 MiB response bounds remain. Filtered lists read trace
identity before matching, then summaries/observations only for matches. Trace
capture is optional: absent records use legacy facts with explicit gaps. Persistence
redaction applies to new optional owner records, not existing private bindings.

## Canonical provenance join (0.4.0)

Two additive APIs: `provenance(build_id, package, cursor=None, limit=20)` and
`compare_provenance(before, after, package)`. CLI names are `provenance` and
`compare-provenance`. Both require explicit `record_store` and `record_project_id`
constructor options; ordinary inspection requires neither and has no build-record
dependency. Full build package rows expose the retained `build_record` owner pointer;
new command trace provenance also contains the prepared/input reference and pointer
location. These references alone are not graph/byte verification.

The adapter reads `attempts/<id>/packages/<key>/provenance.json`, checks its host,
project, build, package and scoped attempt identity, and loads the result root (or
prepared root when unfinished) only from the configured content-addressed store.
All traversed records use strict build-record JSON/schema/hash/graph validation.
Existing no-follow/concurrent-change checks apply. A wrong digest/binding is an
error; absent records are reported with `complete: false`. No current recipe lookup,
network retrieval, artifact verification or controller mutation occurs.

Provenance store defaults: 32 MiB source bytes, 1 MiB per record and 10000 visited
records. Python `provenance_limits=InspectionLimits(...)` can lower/adjust read budgets;
build-record's own schema/bundle limits still apply. CLI uses these fixed provenance
budgets; ordinary source-budget flags apply to the owner evidence read. Responses
retain the 1 MiB cap, with 1–100 records per page. Missing IDs are summarized up to
100 with a count/truncation flag. Gap/artifact counts describe the whole reachable
graph; record pages contain the actual declarations. A too-large single projection
fails explicitly rather than being silently truncated.

`records.items` is a redacted inspection projection, not a canonical bundle whose
returned bytes can be rehashed to its record IDs. Integrity validation occurs before
presentation filtering. Exact record export remains build-record's responsibility.
Cursors bind authorization scope, store, project, build/package and root identity.
Every referenced prepared attempt must use this owner adapter's scoped identity
encoding and be allowed; all result trace locators must also match host/authorization.
This prevents a permitted retry from exposing a disallowed original attempt.

Comparisons require complete references but may carry declared gaps. They expose
input-field differences and original pin/source descriptors, separate same-inputs
and different-attempt indicators, result/output bindings, gap counts and read metrics.
They are package-attempt comparisons; no new rootfs generation comparison contract
is introduced. `artifact_verification` remains not-checked and authenticity remains
not-verified. Current journal availability belongs to the existing logs API.

## Ownership and authority of inspection fields

Build-trace is the read-only execution-inspection layer. Build-record owns the
canonical immutable provenance schema, record identities, validation, relationships
and canonical export. Image-build produces and durably binds those records and
owns orchestration/recovery; box-control remains authoritative for job/runtime
identity and journald evidence. Build-trace does not construct, finalize or persist
canonical provenance, and has no separate provenance datastore or persistent cache.

`origin: captured` means a value was read from its named source. It does **not**
make that value a canonical build-record record. The following classification is
part of the schema-1 inspection contract; existing JSON keys remain compatible.

| Inspection field | Classification and interpretation |
|---|---|
| Command `provenance.value` | Presentation snapshot from image-build's optional trace capture. Recipe, source, pin-set, toolchain and input summaries are legacy owner metadata, not canonical records. Nested `build_record` identities are references only until resolved through the canonical join. |
| Package `inputs` | Retained image-build preparation/result metadata for execution inspection. Its owner fingerprints are not build-record IDs and must not be promoted to canonical build-inputs records by the reader. |
| Package `build_record` | Image-build owner pointer containing canonical record IDs. Ordinary inspection has not validated its graph or artifacts. Use `provenance` for scoped graph validation. |
| Package `output_identity` | Image-build's retained output identity, not the canonical `package-output` record ID. Canonical output references are obtained through the validated owner binding/result. |
| Package `output_manifest`, build `recipe_snapshot` | Derived presentation summaries. `record_digest` is a build-trace inventory-summary digest only; it is not a build-record ID, artifact hash verification or reproducibility claim. |
| Package `reuse` | Imported image-build reuse receipt for execution inspection. It does not establish a canonical dependency/output relationship. |
| Package `source_archives`, `version` | Legacy presentation placeholders; missing means unprojected here, even when a separate canonical join supplies that information. |
| Build `generation` | Retained owner generation locator/status value. It does not establish a canonical attempt/output-to-generation relationship. |
| Command `relationships`, build `retry_relationships` | Captured execution-navigation links and their derived summary. They do not replace canonical `attempt-start.retry_of` or authorize recovery/retry. |
| `provenance` response `binding`, `roots`, record `id` | Owner binding and canonical identity references; the join checks available graph records and reports missing records explicitly. |
| `provenance` response `records.items` | Ephemeral, redacted presentation projections of validated build-record records. Never insert or rehash these projections as canonical records. |
| `compare` differences | Comparison of retained execution settings and legacy owner metadata; not canonical provenance equivalence. |
| `compare-provenance` | Read-only comparison of the captured canonical package graphs; no new records or relationships are created. |
| `export` | Bounded redacted inspection export. Canonical provenance export belongs to build-record's export API/CLI. |

Prefer canonical records for provenance presentation when available. Keep legacy
inspection metadata labeled separately; do not silently merge conflicting values
or use current recipes/pins to fill historical gaps. Existing binding/hash/scope
conflicts remain errors. Missing canonical records remain missing, rather than
being reconstructed from trace snapshots. Consumers may cache presentation under
their own policy, but must retain source/identity and availability distinctions.

### Generation integration boundary

Image-build now publishes explicit generation roots and replayable member indexes
under its rootfs-v1 producer contract. Build-trace 0.5 consumes these read-only as
described below. A package result closure follows references to inputs and outputs;
it cannot discover later generations through those forward edges alone. The owner
indexes provide discovery, while canonical graph membership supplies validation.
Build-trace must not infer relationships from names, status labels or inventory
digests, or construct/finalize the relationships. Build-record references trace/job
identities; logs and execution history remain in their existing owner stores.

## Generation consumer (0.5.0)

The producer prerequisite described above is now available in image-build's
`rootfs-v1` contract. The read-only consumer accepts schema-2 generation manifests
with schema-1 `build_record` pointers. Canonical record schema remains 1. These
additive APIs do not change existing inspection fields or promote legacy metadata.

`generation-provenance` returns `binding`, `roots`, paged redacted `records`, gaps,
missing-record counts and read metrics. Owner generation, assembly start/input,
result/output and canonical generation root bindings are cross-checked. Missing or
legacy manifests return `not-captured-or-unavailable`; malformed/conflicting known
bindings are errors. A retained root with missing graph records reports those gaps
for unrestricted trusted local readers; no artifact-byte verification is implied.

`provenance` supports explicit reused-output/result references as a fallback when
`provenance.json` is absent. Its response identifies the retained-output binding
and preserves the original producer. Missing references are not reconstructed;
swapped/failed result bindings are errors. Explicit legacy outputs retain their
canonical gaps and do not acquire an invented producer.

`generation-list` pages the chosen member's retained reverse-index entries. Each
available row validates its canonical membership; stale/conflicting known values
are errors, unavailable generation manifests and incomplete closures are explicit
unverified rows. Discovery completeness stays unknown, including an empty index.
It does not traverse an unrestricted record directory or repair index files.
Only installed membership should be presented as installation in the rootfs.

All available attempt-start identities and trace locators in every loaded closure
must satisfy host/project and `allowed_build_ids`, including reused producers,
assembly, dependencies and failed retries. A disallowed closure fails the request;
rows are not silently filtered. With a narrowed build allowlist, missing records
prevent proving authorization and fail closed. Legacy generations have no canonical
attempt authorization and cannot be inspected under a narrowed allowlist. A legacy
output with no producing attempt cannot be used for reverse discovery.

Record pages bind cursors to host/project/allowlist, store, selected subject and
canonical root. Navigation cursors additionally bind the member and current index
filenames; additions/removals invalidate continuation. Restart after invalidation.
Scope changes also invalidate cursors. Responses cap at 1 MiB; page limits are
1–100. The record-store budget is shared across all page graphs (default 32 MiB,
1 MiB per record, 10000 records); owner reads use the configured inspection limits.
Index enumeration is bounded by the owner directory-entry limit. Budget overflow
fails explicitly; reduce the page size where applicable. Filesystem snapshots use
no-follow reads and concurrent-change detection; there is no cross-owner transaction.

`complete` retains build-record's declared completeness, distinct from closure
availability, success, artifact verification, authenticity and reproducibility.
Record projections remain ephemeral and redacted. Exact canonical export belongs
to build-record; neither a new datastore nor a canonical writer is introduced.

## Summaries and comparisons (0.6.0)

`generation-summary` is a compact projection of a validated generation graph:
`assembly`, `artifact`, `content_manifest`, `package_count`, paged `packages`,
`coverage`, and a generation-provenance detail query. Package rows contain exact
canonical reference IDs and original `producer_build_id`. `relationship_to_assembly`
is same-attempt/different-attempt/unknown; different-attempt does not infer chronology
or claim fresh execution by the assembly owner. Only root-installed packages appear.
Canonical source selections and recipe descriptors supply drill-down references;
no current catalogue/recipe reconstruction or journal retrieval occurs.

`coverage` separates `complete`, gap count and first 20 gap declarations with explicit
truncation, from missing-record count and first 100 missing IDs. Gaps are redacted
presentation data. The detailed record API supplies the full declarations by paging.
An incomplete graph returns `availability: incomplete` without a misleading partial
installed-package list. Legacy/missing owner manifests retain their existing explicit
availability; permission-limited readers still fail closed on missing graph records.

`generation-comparison` validates both roots in one bounded Reader, invokes
build-record.compare, then presents the package union as paged rows. Canonical
changed_input_fields and assembly_inputs_changed are retained. Equal output IDs are
same-output; equal known input IDs with different outputs are
same-inputs-different-output. Different producer IDs are reported separately.
Unknown legacy inputs never compare equal merely because both are null. Added and
removed refer to installed membership, not deletion/creation of records or dependency
reachability. `changed_package_count` follows the canonical package comparison;
`package_count` includes unchanged packages. Neither asserts binary differences.

Both APIs enforce existing full-closure host/project/attempt scope, no-follow reads,
shared request budgets, 1–100 row limits and 1 MiB response cap. Cursors bind the
operation, scope, store and exact root identities (both ordered roots for comparison).
Missing/unavailable graph responses have no fabricated comparison. Oversized single
rows fail explicitly. Source/gap projections remain noncanonical, ephemeral and read-only.

Package compare-provenance now resolves either original prepared pointers or explicit
retained-output references. The original producer's prepared/input IDs are derived
only from its validated canonical graph. The two selected builds and original
producers all require authorization. Each side retains its existing source budgets;
comparison reports metrics separately. No producer pointer is persisted for reuse.

## Frozen source and patch projection (0.7.0)

`materials` resolves an authorized attempt's original or retained-output input
binding, or an installed package within an authorized generation closure. It returns
canonical `inputs`, paged source/patch `items`, counts, exact declared `input_gaps`,
coverage and read metrics. Known source declarations retain their canonical pin,
archive and upstream fields; unknown revisions remain null. A combined source record
is explicitly marked as having no per-archive mapping. Patch `position` is one-based
canonical list order. Classification/application completeness is not inferred from
the presence, absence or names of descriptors. Canonical record identity/completeness
remains build-record-owned; source and patch bytes are not read or verified here.

`material-comparison` resolves both sides and pages explanatory changes. Exact source
record identities can match; otherwise only unique single-archive names align source
declarations. Unique patch names align patch descriptors and positions. Ambiguity or
renaming remains unpaired added/removed declarations, not inferred lineage. Matching
is presentation only and does not alter record identity or assert upstream truth.
Empty unchanged ordered patch lists produce no descriptor change; their declared
input gaps are still returned on each side. No equality of unknown historical
inputs is claimed. `availability: unavailable` carries each side's explicit reason
when a meaningful comparison cannot be established.

Cursors bind host/project/allowlist/store, operation, selected subjects/package,
input IDs and graph roots. Existing per-side bounded graph reads, redaction and
1 MiB response limits apply; all closure attempts remain permission checked.
Descriptions/gaps may contain sensitive text and are presentation-filtered.
Oversized individual records or rows fail; source and patch detail pagination does
not authorize broader filesystem access. These are additive schema-1 projections.


## Integration observation projections (0.8.0)

Two additive APIs support the first integrate-observe consumer foundation:
`generation_observations(generation, collection=None, cursor=None, limit=20)` and
`candidate_verifications(candidate, cursor=None, limit=20)`. CLI names are
`generation-observations` and `candidate-verifications`. Both require an explicit
`record_project_id`; published generation inspection also requires the configured
canonical record store. Producer data arrives only through an injected read-only
observation provider. The trusted local CLI can wrap one explicit producer export with
`--observation-file`; this is not a retained build-trace storage convention.

Published generation envelopes are validated by build-record against the same
canonical generation closure already used by `generation-provenance`. Candidate
envelopes are validated independently and do not imply publication. Unsupported
producer schema versions, malformed producer identities, cross-generation bindings,
or unauthorized attempt/evidence locators fail closed.

`generation-observations` without `collection` is a compact manifest. It reports
the producer/context identity, derivation and collection counts/authority, but not all
rows. Collections are independently paged and cursor-bound to host/project/allowlist,
record store, owner generation, producer envelope ID and collection name:

- `checks`: producer logical check ID, definition digest and granularity;
- `verification`: deterministic build-record `verification-execution` projections;
- `relationships`: image-build relationship observations;
- `sources`: image-build source observations;
- `gaps`: explicit image-build producer gaps.

Verification rows keep `record` (the deterministic build-record identity),
`producer_observation`, `check_id`, `definition_digest`, candidate subject,
attempt/build identity, sequence, outcome, execution, environment digest, evidence,
granularity and timing separate. `authority: build-record` means build-record defines
that canonical record shape and identity. `persistence: not-checked` means this query
does not claim the record has already been inserted into a Store.

Relationship/source/gap rows remain `authority: image-build-producer`,
`canonical_record: null` and `canonicalization: not-yet-defined`. Build-trace does
not mint canonical records or edges for them. Coverage is returned beside the
collection and remains producer data until build-record defines a canonical coverage
contract.

Candidate verification rows use the same deterministic verification identity as a
later published envelope containing the same producer observation. Repeated executions
of one logical check remain separate records; definition changes remain separate from
the logical `check_id`. PASS/FAIL/ERROR/SKIP are preserved exactly. Absence remains
absence and is never converted into SKIP, success, deletion or an unchanged result.

These APIs do not yet provide cross-generation verification histories, reverse
relationship indexes, evidence expansion, baseline selection, release chronology,
regression classification, severity, blast-radius judgments or durable findings.


## Canonical relationship and source observation projection (0.9.0)

Build-record 0.5.0 defines canonical `relationship-observation` and source-development
records. The existing generation observation API now projects those identities
directly instead of labeling relationship/source rows as not-yet-canonical.

Relationship rows expose the deterministic `relationship-observation` record ID,
producer observation ID, literal subject/relation/target/evidence, declared gaps and
`persistence: not-checked`. This preserves interface facts rather than resolving
them: a `needs-library` SONAME is not mapped to a provider package, declared package
dependencies are not converted to output dependencies, and interpreter paths are not
resolved. Only a producer `used-build-output` observation carries its already
canonical exact output/input binding.

Source rows are keyed by the canonical `source-provenance` record and include the
canonical repository/reference/archive/association chain needed to explain that
binding. Repository identity remains exact-literal. Git commits, tags, opaque
references and unknown references remain distinct. The
`declared-not-independently-reproduced` archive/reference relationship is preserved
verbatim and is not promoted to proof that a revision reproduces archive bytes.

`generation_observations(..., collection="relationships", relation=..., package=...)`
supports bounded filtering by the closed relation vocabulary and by subject package
(or artifact package ownership). `collection="sources"` supports `package=...`.
Filters are part of the cursor scope, so a continuation cannot be reused under a
different relation/package query. These filters are projections over the supplied
generation envelope, not persistent indexes or reverse-resolution claims.

The compact manifest now marks verification, relationships and sources as
`authority: build-record`. Check declarations, observation coverage and general
producer gaps remain `authority: image-build-producer` until later canonical coverage
contracts exist. No query in this pass selects a release baseline, classifies a
regression, assigns severity, infers chronology, or stores findings.


## Canonical generation observation snapshots (0.10.0)

Build-record 0.7 `generation-observation-snapshot` records are the preferred
integrate-observe boundary. Build-trace accepts an explicit canonical snapshot record
ID; it does not invent a "latest" pointer or mutate generation state.

`observation_snapshot(snapshot, collection=None, ...)` returns a compact manifest
with the canonical generation record, owner generation identity, root inventory
digest, record-set digest, exact declared/available counts for each snapshot group,
and a coverage summary. The independently paged collections are:

- `verification-checks` → `verification-check`;
- `verification-executions` → `verification-execution`;
- `relationships` → `relationship-observation`;
- `source-provenance` → `source-provenance` with its canonical
  repository/reference/archive/association chain expanded read-only;
- `coverage` → `observation-coverage`.

Records read through a snapshot report `persistence: stored`, unlike deterministic
IDs computed from a raw producer envelope where persistence is not checked.

Coverage outcome is separate from metadata integrity. A snapshot can have a valid,
complete canonical record closure while a family is `partial`, `unavailable`,
`not-performed` or `not-applicable`. A complete coverage record with
`observation_count: 0` means the declared scope was examined and produced no
observations; it must not be collapsed into missing/unavailable coverage.

Coverage can be filtered by canonical family and outcome. Relationship/source
collections retain the bounded relation/package filters. All filters are part of the
cursor scope.

`compare_observation_snapshots(before, after, collection=None, ...)` compares exact
canonical membership sets. The manifest reports added/removed/unchanged counts for
every group, whether generation record/owner identity/root inventory are the same,
uniquely pairable logical-check definition changes, and uniquely pairable coverage
family changes. A selected collection pages the exact added/removed canonical records.

The comparison is intentionally factual. It does not label a FAIL as a regression,
choose a preferred execution, infer chronology from two caller-supplied snapshots,
resolve dependency providers, assign severity, calculate blast radius or persist a
finding. Those decisions remain integrate-observe responsibilities.


## Caller-ordered histories and relationship traversal (0.11.0)

`verification_history(snapshots, check_id, definition_digest=None, cursor=None,
limit=20)` accepts 1–100 unique canonical snapshot IDs. Pagination is over snapshot
points, using the caller's exact list order. Every point retains all matching
`verification-check` definitions and all matching `verification-execution` records,
plus canonical `verification-commands` coverage. No representative execution is
selected. An optional definition digest is an exact filter, not a request to reinterpret
logical check identity.

The response states `order: caller-supplied` and `chronology: not-inferred`.
Changing sequence order invalidates an existing cursor. Snapshot generation,
root-inventory and coverage facts are returned at each point so consumers do not need
to infer absence from an empty execution list.

`relationship_traversal(snapshots, direction, selector_kind, selector_value,
relation=None, cursor=None, limit=20)` performs literal field matching over canonical
`relationship-observation` rows at every caller-selected snapshot point.

Forward selectors match subject fields: package, package-output, artifact path or
artifact digest. Reverse selectors match target fields: package, package-output,
SONAME or path. Reverse package matching may match the package label explicitly
carried by a `package-output` target; it does not discover or resolve a provider.
Reverse SONAME/path queries similarly do not link requirements to providers.

Each relationship point carries the canonical coverage families relevant to the
requested relation. Without a relation filter, all relationship-related coverage
families are included. A zero-match point is therefore distinct from a claim that the
phenomenon was completely examined unless its coverage records establish that.

Both APIs reconstruct results from immutable canonical roots and create no persistent
history/reverse index. Cursors bind the exact ordered sequence and all selectors.
Response size remains capped at 1 MiB; reduce page size or narrow the selector when a
single history point contains many matching records.

No caller sequence is treated as a release baseline or chronological truth. These APIs
make no regression, reachability, provider-resolution, causation, severity or blast
radius judgment.


## Snapshot completeness dimensions (0.12.0)

The old snapshot field `metadata_closure_complete` is removed because build-record
0.7's aggregate `complete` means both "no missing canonical references" and "no
declared record gaps". That aggregate is too broad for integration analysis.

Snapshot manifests and collection responses now expose independent fields:

- `reference_closure_complete`: true iff the canonical traversal reports no missing
  record reference;
- `missing_record_count`: number of missing canonical references;
- `declared_gap_free`: true iff no visited canonical record carries a declared gap;
- `declared_gap_count`: number of canonical records carrying one or more gaps;
- `declared_gap_reason_count`: total declared reason entries;
- `declared_gap_summary`: bounded category counts;
- `coverage`: canonical observation-coverage records, unchanged.

A World may therefore validly have complete reference closure, nonzero declared gaps,
complete ELF coverage and unavailable verification coverage at the same time.

The bounded gap summary categorizes exact canonical reason strings as:

- `upstream-identity`: unknown/undeclared upstream revision/reference identity;
- `external-environment-runtime`: runtime/controller/kernel or non-allowlisted
  environment evidence not captured canonically;
- `inventory-only-output`: package output represented by a verified inventory
  artifact while output bytes remain retained by image-build rather than the canonical
  artifact store;
- `other`: any declared reason not matched by the preceding presentation categories.

These are build-trace presentation categories, not new canonical record kinds. Exact
canonical reasons remain verbatim in the paged `declared-gaps` collection. Each row
contains the gap-bearing canonical record ID, its actual canonical kind, categories,
exact reason entries and reason count. `gap_category` is an optional exact category
filter and is cursor-scoped.

Snapshot comparison carries the same dimensions independently for both sides using
`before_*` and `after_*` fields, including raw coverage summaries. A reduction in
declared gaps is only a factual count/set difference; build-trace does not call it an
improvement or release judgment.

Canonical-only operations do not require image-build owner state. BuildTrace
construction is lazy with respect to `PROJECT/state/image-build`; these operations
work with only record-store and scope information:

- `observation_snapshot`;
- `compare_observation_snapshots`;
- `verification_history`;
- `relationship_traversal`.

Owner-local operations retain the old requirement and fail `source-unavailable`
when image-build state is absent. `generation_provenance` also requires the owner
generation manifest because that query follows the owner's published generation
pointer.

No snapshot discovery is introduced. Callers still provide explicit snapshot IDs;
build-trace does not scan the canonical store for latest/preferred snapshots or infer
chronology/baselines.
