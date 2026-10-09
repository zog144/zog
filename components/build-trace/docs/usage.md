# Usage for the image-build implementation chat

Run on an authorized build host or a local copy of its retained evidence. The
project must contain `state/image-build`. The shell function below passes paths
and a host identity explicitly; it does not discover hosts or change credentials.

```sh
trace() {
  python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" "$@"
}
trace list --package gcc --status nonzero-exit --limit 20
trace list --status failed --limit 20
trace list --attempt "$ATTEMPT_ID"
```

A package command can fail while the pipeline stays `pending`, so use
`nonzero-exit` to find captured command failures and `failed` for attempt status.
Statuses are exact filters; there is no undocumented equivalence between them.
Use returned `items[].id` and `commands.items[].id` for subsequent requests.
Always follow `has_more`/`next_cursor`, even when a list page contains no matches:
scan budgets can stop a sparse search before the next match. Old 0.1.0 list cursors
must be discarded on upgrade. Example continuation:

```sh
trace list --package gcc --status nonzero-exit --limit 20 --cursor "$NEXT_CURSOR"
```

Detail requests:

```sh
trace inspect "$BUILD_ID" --limit 20
trace command "$BUILD_ID" "$COMMAND_ID"
trace inspect "$BUILD_ID" --limit 20 --cursor "$NEXT_CURSOR"
trace compare "$OLD_BUILD_ID" "$NEW_BUILD_ID"
trace export "$BUILD_ID" --command-limit 100
```

Build IDs are `attempt:<retained-directory-name>` or `pipeline:<pipeline-id>`.
A pipeline with no attempts is included in lists, so failures before preparation
remain visible. Command IDs are a stable relative record stem such as
`packages/gcc/build-0`; lookup is restricted to the selected build. These display
locators never replace image-build/controller recovery identities.

`command.value` is recorded argv. `script.value` is available for recognized shell
`-c` forms. `working_directory`, `environment` and `settings` come from retained
resolved requests when available. `outcome` is separate from evidence completeness.
For legacy records, inspect the `origin` and `reason` fields instead of assuming
missing means default, success or never executed.

## Journals

Install the supported box-control source and dependencies and use an authorized
root-control socket. Build-trace uses no elevated shell or arbitrary journal query.

```sh
python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --controller --socket-path /run/zog/root-control.sock \
  logs "$BUILD_ID" "$COMMAND_ID" --limit 50

python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --controller --socket-path /run/zog/root-control.sock \
  logs "$BUILD_ID" "$COMMAND_ID" --limit 50 --cursor "$NEXT_CURSOR"
```

The same `--controller` options enrich list/inspect results with controller
observations. Without them, metadata inspection still uses durable completion
records. There is no automatic fallback to a different host or journal stream.

The initial journal page is the controller's tail, not the beginning of all output.
Always reuse its returned cursor. `cursor-expired-or-unavailable` means the anchor
cannot be found; it does not establish why it disappeared. `empty-or-expired`
means the owner cannot distinguish absence from retention loss. Read failure never
changes execution outcome or advances a cursor.

## Python interface and future station-access integration

```python
from pathlib import Path
from zog.build_trace import BuildTrace, BoxControlReader
from zog.box_control import BoxControl, Project

# Select these from trusted server-side configuration after authorization.
control = BoxControl(Project(Path(project_root)))
trace = BuildTrace(project_root, host_id=host_id,
                   controller=BoxControlReader(control),
                   allowed_build_ids=authorized_build_ids)
page = trace.list_builds(package="gcc", status="nonzero-exit", limit=20)
command = trace.inspect_command(build_id, command_id)
logs = trace.logs(build_id, command_id, cursor=cursor, limit=50)
```

An omitted `allowed_build_ids` means all builds in the explicitly configured local
project. An empty iterable means none. This is a narrowing mechanism, not remote
authentication. station-access must select project/host/build scope on the server,
apply its administrator policy and escape every command/log string when rendering.
Never accept a project path, socket path or host scope directly from an untrusted
request. No new HTTP routes are implemented by this pass.


## Configure read budgets

Defaults suit lightweight discovery and larger explicit detail reads. Settings are
local administrator options, independent of page size and the fixed 1 MiB response cap.

```sh
python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --list-source-limit-mib 32 --scan-build-limit 200 list --package gcc-final --limit 10
python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --source-limit-mib 256 --file-limit-mib 32 inspect "$BUILD_ID"
```

Use `--record-limit` for the maximum visited records/entries per directory. Raising
budgets can increase memory use; a byte budget refers to serialized input, not Python
object memory. Check `inspection` counters and `error.details` before choosing higher
limits. A known command or log query should not need an increased inventory budget.

```python
from zog.build_trace import BuildTrace, InspectionLimits
trace = BuildTrace(project_root, host_id=host_id,
                   limits=InspectionLimits(source_bytes=256 * 1024 * 1024,
                                           list_source_bytes=16 * 1024 * 1024,
                                           scan_builds=100))
cursor = None
while True:
    page = trace.list_builds(package="gcc-final", limit=10, cursor=cursor)
    for build in page["items"]:
        print(build["id"], build["title"])
    if not page["has_more"]:
        break
    cursor = page["next_cursor"]
```

Diagnostic attempts with only custom launch/job receipts now show
`layout.status="unsupported-layout"` and an unknown command count. Preserve those
receipts for the owner-adapter follow-up; do not manufacture engine checkpoint files.
The original attempt failure remains unchanged when independent retries exist.

## Failure and interruption workflow

1. `trace list --package gcc-final --limit 10`, following every continuation.
2. `trace inspect "$BUILD_ID" --limit 10` for explicit relationships and a bounded
   failure summary. Command summaries include failures and unresolved outcomes.
3. `trace command "$BUILD_ID" "$COMMAND_ID"` for the captured title, recipe/source
   provenance, exact scoped identities, request settings and evidence references.
4. `trace logs "$BUILD_ID" "$COMMAND_ID" --limit 50` with controller options for
   current journal availability; preserve its cursor on retrieval failure.
5. Read `recovery.status`, process cleanup and resource-release facts separately
   from outcome. Hand exact IDs to image-build/box-control for owner reconciliation.
   Reopening build-trace itself performs no recovery action.

```python
command = trace.inspect_command(build_id, command_id)
print(command['title'])
print(command['failure_summary'])
print(command['recovery'])
for ref in command['evidence']:
    print(ref['kind'], ref['reference'], ref['availability'])
```

Without the updated image-build capture, legacy evidence remains usable. Diagnostic
receipts can be explicitly adopted with the owner `import_diagnostic` API documented
in image-build's `docs/build-trace-contract.md`; the inspector does not import them.
A historical import is read-only with respect to execution but writes optional
owner metadata, so it belongs in the owner's authorized workflow and operation lock.

## Canonical package provenance (0.4)

Enable the image-build owner producer as documented in its
`docs/build-record-integration.md`. Install compatible build-record alongside this
reader. The store and stable project identity are trusted caller configuration:

```sh
python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --record-store "$PROJECT_ROOT/state/image-build/build-record/records" \
  --record-project-id "$PROJECT_ID" \
  provenance "$BUILD_ID" gcc-final --limit 10

python3 -m zog.build_trace --project-root "$PROJECT_ROOT" --host-id "$HOST_ID" \
  --record-store "$PROJECT_ROOT/state/image-build/build-record/records" \
  --record-project-id "$PROJECT_ID" \
  compare-provenance "$FAILED_BUILD_ID" "$RETRY_BUILD_ID" gcc-final
```

The package argument is the materialized directory key. `provenance` returns a
paged, redacted record projection, prepared/result IDs, graph gaps and missing-record
counts. Follow `records.next_cursor` when `records.has_more`, keeping the same query.
A changed root after owner finalization invalidates the old cursor; restart inspection.
Use canonical build-record export separately when byte-exact records are required.

`compare-provenance` reports changed canonical input fields, selected pin/source
facts, and whether attempts differ even when their input IDs match. It does not
reinterpret a retry's success as success of the original attempt. Missing graph
records produce an explicit incomplete comparison, not empty/equal differences.

```python
trace = BuildTrace(project_root, host_id=host_id,
    record_store=trusted_record_store, record_project_id=stable_project_id,
    allowed_build_ids=authorized_build_ids)
page = trace.provenance(build_id, 'gcc-final', limit=10)
comparison = trace.compare_provenance(failed_build_id, retry_build_id, 'gcc-final')
```

A restricted caller must be authorized for every referenced attempt in the closure,
including retry history and dependencies. Otherwise the query returns not-found.
The reader never opens artifact paths/URLs from records and never writes to the
store. Metadata completeness, build outcome, byte verification, producer authenticity
and current journal availability remain separate. `not-captured` means legacy or
unconfigured owner capture; it does not mean the build never ran.

## Generation and reused-output inspection (0.5.0)

Configure `--record-store` and `--record-project-id` as for package provenance.
The store is the trusted canonical records directory; generation manifests and
membership indexes are read beneath the configured image-build state root.

```sh
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID generation-provenance OWNER_GENERATION --limit 20
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID generations --output sha256:OUTPUT_RECORD_HEX
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID generations --attempt sha256:ATTEMPT_START_HEX
```

Python methods are `generation_provenance(generation, cursor=None, limit=20)` and
`generations(output=None, attempt=None, cursor=None, limit=20)` (options are keyword
arguments). The former takes image-build's 64-hex owner generation identity; the
latter takes exactly one canonical output or attempt-start ID. `provenance(build_id,
package)` now falls back to explicit `result.json.provenance` bindings when no
original package pointer exists. It reports `binding_kind: retained-output`; this
is not evidence that the selected reusing attempt executed the original producer.
Canonical producing identity remains in the returned record graph. Since 0.6, `compare-provenance` also resolves these retained-output references.
It does not synthesize owner pointers; use `compare-generations` for generations.

Generation navigation reads only the selected member's owner index directory and
the graphs for that result page, with shared per-request budgets. It validates
membership against canonical records. `installed`, `assembly` and
`dependency-or-history` are distinct relations. An empty list is not proof that no
generation uses the member: index recovery belongs to image-build. Discovery
completeness is always explicitly unknown. See the schema for authorization and
availability semantics. These APIs neither read rootfs/archive bytes nor run owner
verification, index repair, generation finalization or activation.

## Compact summaries and comparisons (0.6.0)

```sh
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID generation-summary OWNER_GENERATION --limit 20
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID compare-generations BEFORE_GENERATION AFTER_GENERATION
```

Python: `generation_summary(generation, cursor=None, limit=20)` and
`compare_generations(before, after, cursor=None, limit=20)` (paging arguments are
keyword-only). Both use owner generation identities, not canonical record IDs.
Summaries page installed packages, showing original producer/output/result/input
IDs, recipe descriptors, source-selection references, assembly identity and up to
20 declared gaps. `detail` links to the existing generation-provenance query.
Build-only dependencies remain in that detailed closure, not the installed list.

Generation comparisons use build-record's canonical comparison logic. Every package
in the union appears, including `same-output` rows: an identical output ID means the
same canonical output, not independently reproduced bytes. Other statuses are
`added`, `removed`, `same-inputs-different-output`, `changed-inputs`, or
`different-output-inputs-unknown`. `different_producer` separately compares captured
attempt-start IDs. Assembly input change is reported separately. Follow `packages`
paging; limits/cursors apply to the package rows.

`compare-provenance` now accepts original and retained-output bindings on either
side. `different_attempt` compares original producing attempts, not the two selected
inspection locators. `before_binding_kind` / `after_binding_kind` identify
`prepared-pointer` versus `retained-output`; `same_output` is null when one side has
no output. Legacy missing inputs return `legacy-inputs-unavailable`, never equality
of two unknowns. Existing generation navigation and detailed record views remain
available. No comparison claims byte equivalence, causation or reproducibility.

## Source and ordered patch details (0.7.0)

With the same trusted project/host/record-store options:

```sh
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID materials attempt:ATTEMPT PACKAGE --limit 20
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID materials generation:OWNER_GENERATION PACKAGE
build-trace --project-root PROJECT --host-id HOST --record-store RECORDS \
  --record-project-id PROJECT_ID compare-materials generation:BEFORE generation:AFTER PACKAGE
```

Python APIs: `materials(subject, package, cursor=None, limit=20)` and
`compare_materials(before, after, package, cursor=None, limit=20)`; paging is
keyword-only. Subjects are `attempt:ID` or `generation:OWNER_GENERATION`, and can be
mixed for comparison. Generation selection requires an installed package; attempt
selection also supports retained reused-output references. The original producing
inputs remain authoritative. Generation rows and comparison views supply these
detail-query references.

Source rows show canonical source-selection ID, consumed archive descriptors,
monthly pin descriptor, declared upstream repositories/revisions and source gaps.
Multiple archives in one historical record stay grouped; no per-archive upstream
mapping is invented. A null revision remains unknown, including opaque revisions
not representable in the canonical Git field. The reader never opens recipe
materials to recover extra identifiers. Declared archive/upstream associations are
not authenticated proof.

Patch rows show descriptor name/digest/size and one-based declared application
position. `patch_count: 0` does not establish complete patch classification. Read
`input_gaps` and `coverage`; descriptors do not attest successful application.
The canonical schema exposes textual gaps, not a structured patches_complete flag;
this reader does not infer such a flag from the absence of a particular sentence.

Comparison aligns unique single-archive names or unique patch names, solely for
presentation. It reports before/after pin, archives, upstream and gaps, plus changed
patch descriptor fields and order positions. Added/removed means declarations in
the two records, not filesystem actions. Renamed, combined or ambiguous groups stay
unpaired added/removed declarations. No array-position guess links archives to
repositories. Existing same-output/same-input distinctions remain unchanged.

`items` (details) and `changes` (comparison) contain paged items/has_more/next_cursor.
Limits are 1–100. Record/source/response limits and full-closure authorization apply;
a single oversized declaration fails explicitly. Patches precede sources in detail
pages, with patch order preserved. Missing records and legacy inputs stay explicit;
no current catalogue lookup, downloads, patch execution or archive reads occur.
