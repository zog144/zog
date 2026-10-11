# Required package and generation provenance with build-record

This is an **opt-in Python integration** for normal package builds. Install the
compatible build-record schema-1 library before enabling it. Existing unconfigured
pipelines retain their previous behavior; no existing host or compiler job is
migrated automatically. The optional build-trace capture remains separate.

The adapter produces source-selection, build-inputs, attempt-start, package-output
and attempt-result records. It binds their IDs in each package's `provenance.json`.
New configurations also require canonical assembly and generation records for the
normal image/seed-check/native-check pipeline. Build-trace 0.6 exposes package joins, generation navigation and canonical
generation comparisons.
Build-record's schema stays at 1 and its library stays at 0.1.0.

## Configure a new owner pipeline

Use an owner-controlled state directory, stable host/project identities, the original
monthly pin file, and its verified repository revision/path. The adapter hashes and
retains the supplied file bytes; it does not fetch Git or authenticate the revision.
The staged recipes must carry the matching materialized monthly snapshot generated
by `stage_recipes`. Missing or differing original/materialized pins block execution.

```python
from pathlib import Path
from zog.image_build import ImageBuild
from zog.zog.image_build.provenance import Provenance
from zog.zog.image_build.runner import BoxControlRunner

state = Path(project_root) / 'state'
pin = Provenance.capture_pin(
    state, original_monthly_pin_path,
    repository='https://github.com/zog144/image-build',
    revision=exact_pin_repository_commit,
    repository_path='project/pins/2026-10-01/commit-pin.py',
)
provenance = Provenance(state, host_id=host_id, project_id=project_id, pin=pin)
builder = ImageBuild(
    package_dir=staged_recipe_directory, state_dir=state,
    runner=BoxControlRunner(execute=configured_controller_adapter),
    provenance=provenance,
)
selection = builder.ensure(targets, toolchain=accepted_toolchain)
```

This configuration belongs in the authorized image-build worker. There is no new
CLI worker flag or automatic deployment in this pass. Do not enable it by restarting
an active build. Dynamic test fixtures and dependency replacement flows currently
fail closed when provenance is enabled; their exact additional materials need an
explicit adapter. Use the normal owner workflow for those existing operations.

## Durable ordering and recovery

The image-build pipeline policy binds provenance host/project, original pin identity
and explicit retry map. Its existing lock serializes preparation and finalization.
The store is `state/image-build/build-record/records`; retained artifact bytes are
`state/image-build/build-record/artifacts/<sha256-hex>`.

1. Verify original monthly pin binding and consumed source-cache hashes. Retain exact
   source bytes, package recipe files, materialized pin, builder Python source,
   resolved command/environment/policy description, prepared-root inventory and
   toolchain manifest as content-addressed artifacts.
2. Create canonical source/input records, then `provenance-preparing.json` with a
   fixed prepared timestamp/identity. Publish that immutable attempt-start and write
   required `provenance.json` before any package runner call. Optional trace identity
   receives references to that prepared record, inputs and owner binding.
3. On reopen, use the same pointer, validate graph and required artifact bytes, check
   retained recipe/implementation files against the execution checkout, and reuse
   the existing controller checkpoints. Changed required code/inputs block recovery.
   Current catalogue or pin files are never substituted for the pipeline snapshot.
4. Capture a terminal command failure or output-validation failure as a failed
   attempt-result with no accepted output. Unknown execution, lost responses and
   arbitrary storage failures retain the prepared record without inventing a final
   outcome. Existing controller reconciliation remains authoritative.
5. After owner output verification, publish package-output and stage an immutable
   `provenance-finalizing.json` containing the result timestamp/content. Put the result,
   verify its closure/material bytes, then update the owner pointer. A lost response
   or pointer write replays the same intent/result ID. Required errors propagate and
   block normal continuation/publication; they are not optional telemetry failures.

Original record/artifact hashes and the original monthly Git revision are different
identities from image-build's normalized `monthly_identity`, `source_pins`, package
fingerprints and generation IDs. No substitution between these digests is allowed.

To reopen, restore the **recorded** provenance configuration from the pipeline:

```python
record = builder.inspect_pipeline(pipeline_id)
provenance = Provenance.from_configuration(state, record['policy']['provenance'])
# Construct ImageBuild with this provenance and the same execution policy, then:
# builder.resume(pipeline_id)
```

Changing or disabling provenance for a prepared pipeline is a policy mismatch.
Recovery after a genuinely failed final package result needs a new explicit retry;
never reuse its attempt ID or overwrite that final result. Follow the existing owner
release/retry workflow, with `retry_of={package_key: previous_failed_result_id}` in a
new Provenance configuration. Only failed/cancelled results for the same package
are accepted as retry targets. This API does not release or launch anything by itself.

## Truthful scope, gaps and retention

- Canonical package identity is the materialized package key (for example gcc-final).
  Build-trace package arguments use this directory key, not a display alias.
- Globally scoped attempt identity is the JSON encoding of
  `[host_id, project_id, image_build_attempt_id, package_key]`. Do not parse it as a
  colon-separated string or mistake it for a content hash.
- Source bytes are checked against their declared hashes. Original pin revision is
  caller-declared, not cryptographically authenticated. Explicit source-bound Git
  revisions are captured as described below; archives alone do not imply commits.
- Resolved recipe and constituent files are retained artifacts. Reviewed patch sources are
  classified in declared order; unclassified transformations retain a gap.
- Prepared root/toolchain inventories describe bytes verified by image-build. The
  adapter does not archive all toolchain/root files. Accepted package output artifacts
  are **output inventories**, not package/rootfs archives; build-record verification
  verifies inventory bytes and does not recursively verify their listed files.
- Controller/runtime implementation, custom execute callbacks and host kernel are not
  fully captured. Environment outside build-record's allowlist is recorded as a gap;
  resolved recipe material retains the owner environment. Recognized sensitive values
  in resolved commands/environment/policy are rejected before recipe capture rather
  than replaced with different build-affecting values. This is not universal secret
  detection; the store is private owner-controlled state, not a public export.
- Reused outputs without a producer binding become explicit legacy package-output
  records with no attempt/result, never today's recipe/pins attached retroactively.
- No garbage collection is added. Retain the records/artifacts and owner pointers
  together. Do not apply runtime's 25-entry history limit to provenance. Interrupted
  writes can leave unreferenced immutable objects; no automatic deletion occurs.
- This integration does not interpret licensing, attest signatures, assert bitwise
  reproducibility or change package acceptance criteria.

## Controlled acceptance

With current build-record and build-trace on PYTHONPATH, run:

```sh
python3 -m pytest -q tests/test_provenance.py
```

These fixtures use the real image-build engine and runner with synthetic execution.
They cover failure/retry/accepted output, explicit dependencies, unchanged input IDs,
original pin recovery after current files change, preparation/finalization pointer
interruptions, missing/tampered artifacts, source/recipe changes, disable-policy
rejection, legacy gaps and joined build-trace queries. No milestone compiler job,
real controller dispatch or host reboot is involved.


## Generation policy and compatibility

A newly constructed `Provenance(...)` uses owner configuration **schema 2** with
`generation_contract='rootfs-v1'`. This is an image-build configuration version,
not a new build-record schema. `from_configuration` restores saved schema-1 policies
as package-only (`generation_contract=None`), preserving their exact configuration.
Passing `generation_contract=None` explicitly creates that package-only policy.
Never change policies on an existing pipeline: resume rejects either enabling or
disabling generation capture. Required recovery checks still reject changed bound
recipe/implementation bytes; upgrading code does not authorize input substitution.

The generation contract covers `_ensure` composition: ordinary images and the
controlled seed/native verification variants. Dedicated bootstrap/native publishers
require their own adapters and fail closed in generation mode. Bootstrap imports
remain explicitly external seed inputs. Unconfigured pipelines behave as before.
No existing running pipeline, CLI worker or deployment is automatically migrated.

## Generation production and publication

The image-build lock serializes package preparation, assembly and publication.
`attempts/<attempt>/assembly/` holds:

| File | Durable meaning |
|---|---|
| `preparing.json` | Fixed canonical assembly attempt-start, including timestamp |
| `prepared.json` | Frozen owner/inputs/prepared reference before composition |
| `finalizing.json` | Fixed successful assembly result, including timestamp |
| `generation.json` | Verified canonical generation root and assembly binding |

Assembly inputs name the exact output/result pair for each installed package, in
composition order. Build-only dependencies remain reachable through package input
records. The recipe captures image-build implementation files, the owner inputs,
composition order/policy and Info index generation. Assembly attempt identity is
JSON `[host_id, project_id, owner_attempt_id, "@rootfs-assembly"]`; this reserved
assembly name is not a materialized package directory. Reopening must match the
frozen intent; a composed tree with no recorded assembly intent cannot be retrofitted.
Local composition can be replayed from its bound outputs; this never redispatches a
package command or resolves uncertain controller execution.

After composition the producer creates an actual deterministic uncompressed USTAR
archive and a versioned content inventory, using the existing strict host-export
payload serializer without changing host-install's export contract. Artifact format
`image-build-rootfs-ustar-all-root-v1` normalizes uid/gid/mtime to zero and retains
paths, regular-file bytes, modes and symlink targets. Extended attributes, hard links,
unsupported file types and unsupported USTAR names fail explicitly. The artifact
represents that normalized export; it does not preserve arbitrary host uid/mtime.
No foreign boot bundle, host readiness assertion or log data is inserted. Archives
are owner runtime artifacts under the content-addressed store, never Git assets.

The normalized archive and `rootfs-content.json` are assembly output artifacts.
A successful assembly result refers to that output, and the generation refers to
that result and the exact installed package bindings. Canonical `generation_id` is
JSON `[host_id, project_id, owner_generation_id]`. The owner generation ID remains
image-build's input fingerprint; the canonical record ID separately binds all
producing records and archive bytes. The final artifact hash is outside the archive.

The producer verifies the reachable records and retained artifact bytes before
writing `assembly/generation.json`. Publication copies the composed tree to staging,
checks it against the canonical inventory and package references, writes the
image-build manifest containing `build_record`, then fsyncs and renames the immutable
generation. Discovery indexes finish before activation/terminal pipeline status.
Any required write/verification failure blocks normal completion. Recovery replays
fixed records/timestamps and namespace fsync barriers, including a lost rename or
activation response. No automatic retry with newer inputs is introduced.

Existing-generation return, direct publication reuse, activation and completed
pipeline resume all validate the retained canonical pointer when generation mode
is enabled. An existing generation keeps its original producing graph even if a
new caller requested equivalent owner inputs. A different graph cannot overwrite
it. A generation with no canonical pointer is explicitly legacy and is rejected
in generation-required mode; unconfigured/package-only inspection remains available.

## Package reuse and generation discovery

Released-package cache imports preserve the original canonical output/result in
`record.json.result.provenance`. Restoration retains it in `result.json.provenance`,
checks scope, result success, frozen owner inputs and the actual output inventory,
and does not create a new producing attempt. It does **not** write a fake
`provenance.json` under the reusing attempt. Existing build-trace package joins
continue to use their original producer pointers; readers must explicitly add
support for the reused-result reference before claiming that join is available.

Missing historical bindings remain explicit legacy records. A missing known pointer,
a provenance-enabled cache with missing bindings, changed inventories or conflicting
output/result bindings blocks reuse rather than downgrading known history to legacy.
Older cache entries that omitted known bindings need an explicit migration/reimport
strategy; no in-place rewriting is attempted. Cache policy matching remains exact.

`manifest['build_record']` supplies the canonical generation root, prepared/input,
result/output, host/project, owner generation and trace-build references. Export
independently with build-record:

```python
from build_record import Store, inspect

pointer = selection.manifest['build_record']
store = Store(state / 'image-build/build-record/records')
bundle = store.bundle([pointer['record']])
report = inspect(bundle)
```

Or run `python -m build_record export STORE GENERATION_RECORD_ID`. The resulting
metadata bundle needs neither image-build nor build-trace to inspect. Use an explicit
digest-to-path map with build-record verification to verify external artifact bytes.

Replayable owner indexes live at
`build-record/generation-members/{outputs,attempts}/<record-hex>/<generation-record-hex>.json`.
They index canonical output or attempt-start IDs, not mutable display names or job
IDs. `provenance.generation_roots(output=output_record_id)` or
`provenance.generation_roots(attempt=prepared_record_id)` verifies every returned
entry against the published generation closure. Exactly one selector is required.
The default limit is 100 (maximum 1000); overflow fails explicitly. This trusted
local owner API is not a remote authorization or pagination API. Build-trace must
add its own full-closure attempt permissions and bounded presentation when consuming.

Index relations are `installed`, `assembly`, or `dependency-or-history`; the latter
includes build-only inputs and failed retry history and must not be presented as
installed packages. Indexes do not assert independent provenance. They are repaired
from a validated generation on resume/reuse; no whole-store scan infers membership.
An interruption can leave a partially written index until owner recovery finishes;
lookup of an absent entry is not a global proof of non-membership. Conflicting/stale
entries fail explicitly, including when a generation was reclaimed externally.

## Completeness, retention and acceptance limits

Closed graph validity, declared completeness, byte verification, execution success,
authenticity and reproducibility remain separate. Current package gaps propagate,
so a published generation can have a valid closed graph with `complete: false`.
Missing required records/artifacts or conflicting bindings still block publication.
Verification of package inventories does not recursively validate archived historical
package files; image-build checks actual outputs before composition and the finished
generation tree against its archive inventory.

Keep record/artifact closures, assembly intents and owner pointers while generations
or pending operations depend on them. No cleanup added here deletes these artifacts;
existing workspace cleanup retains package outputs and assembly records. No runtime
history limit is applied. Interrupted writes can leave unreferenced staging trees,
records or artifacts. Garbage collection and index reclamation remain future work.

Controlled tests cover multi-package/build-only closure, independent build-record
inspection, failed retry history, original bindings shared by two generations,
legacy rejection, policy compatibility, missing/tampered materials, swapped results,
publication-copy tampering and interruptions before/after durable record/pointer,
rename, index and activation writes. Tests use synthetic execution and a synthetic
accepted-toolchain descriptor for ordinary-image activation. They do not claim real
compiler acceptance, a bootable rootfs, live deployment or host reboot testing.


## Frozen upstream and patch declarations

An optional literal `source-provenance.py` in the recipe directory declares:

```python
{'schema': 1, 'sources': [
    {'source': EXACT_SOURCES_PY_ENTRY,
     'upstream': [{'repository': 'https://example.org/project.git',
                   'revision': FULL_LOWERCASE_GIT_REVISION,
                   'revision_type': 'git'}]}
]}
```

Each source must match an entire `sources.py` entry, including its archive hash.
This is a declaration, not authentication of an archive-to-commit relationship.
The producer makes one source-selection per consumed source, each with its exact
archive descriptor and explicit upstream identities. Undeclared sources remain
unknown with a gap. Without this file, the prior combined unknown source shape
is retained. Duplicate or mismatched declarations block preparation.

`revision_type='unknown'` requires `revision=None`. `revision_type='opaque'`
retains a nonempty original revision in the frozen recipe file, but emits canonical
null plus a gap: schema 1 only represents Git revisions. A hexadecimal string is
never inferred to be Git. The catalogue binds OpenSSL's existing Git declaration
and SQLite's primary opaque revision; it does not equate SQLite's mirror with its
primary repository. Stage materialization validates a stage declaration or its
version-bound project fallback and copies it into new frozen recipes. Existing
materializations are never silently upgraded.

Patch capture reuses `integration.py['patches']`, the licensing contract: ordered
unique IDs, positive increasing `order`, exact non-archive source entries, matching
`applies_to` version/stage, and nonempty affected-file before/after hashes. Sources
must have distinct destinations. Their exact bytes are retained and checked both
in the source cache and staged source directory before execution and on recovery.
Missing or changed required patch bytes block continuation; there is no refetch or
replacement with current catalogue material. Recipes must keep these staged patch
inputs unchanged while the attempt remains pending.

Canonical `build-inputs.patches` preserves declared application order. Descriptors
do not independently prove that a shell command applied a patch. By default a gap
states that additional recipe transformations may exist. Only an explicitly
reviewed `patches_complete=True`, together with an explicit `patches` list (possibly
empty), removes that classification gap. It does not remove other provenance gaps,
attest successful execution, or certify licensing.

The declaration bytes, patch bytes, recipe implementation and original monthly pin
are frozen before runner dispatch. Recovery uses the original prepared identity and
recorded descriptors; changing today's recipes, pins or declarations cannot repair
missing original materials. Earlier stored records and exports are not rewritten.
Absent optional metadata keeps the existing package fingerprint. No canonical
schema change or execution-log duplication is introduced.

Run `tests/test_source_provenance.py` alongside the full suite for ordered patches,
Git/opaque/unknown handling, frozen recovery, legacy export immutability and
build-trace 0.6 generation-comparison coverage. These are local synthetic tests.

## Installed trust verification reports

New `host_trust` and `host_trust_assembly` operations freeze
`verification_report_contract=image-build-installed-verification-v1` in owner
inputs before preparing assembly or executing the installed check. They retain
`installed-verification.json` as a content-addressed artifact and supply its
descriptor to `generation_provenance.finish(..., verification=[descriptor])`.
The existing schema-1 generation `verification` field contains that descriptor;
no new build-record type or schema version is introduced.

The report binds the scoped candidate generation, canonical assembly attempt,
tested root inventory digest, command/request/policy digests, successful outcome,
completed cleanup, and host/runtime/invocation/trace identities. It contains no
command text or journal entries. The check is named `installed-trust`; its exact
semantics are the frozen command, not a new universal test-success definition.
The report attests the installed offline check, not a public HTTPS handshake,
signature authenticity, complete legacy provenance, or boot readiness.

Capture compares the retained verification preparation with the candidate root,
frozen owner inputs and command. It checks output inventory, controller completion,
policy, request paths, timeout, read-only root and disabled network. This also
works after the verifier has cleaned its temporary root/source directories.
Finalization freezes the report descriptor before creating the immutable generation.
Required missing, changed or replaced report evidence blocks acceptance. An uncertain
pointer/result write replays the same report, attempt, result and generation IDs;
it does not dispatch another installed check. Producer verification also rejects
an owner execution receipt that disagrees with the canonical report.

Recovery under this new contract keeps the same inputs and implementation.
An old work directory without this contract is not silently upgraded: use its
original frozen implementation to recover it, or prepare a separately authorized
new assembly. Existing published generations retain their original empty report
lists. Do not rebuild accepted packages or rewrite old records merely to add a
report. The standard package-only generation path continues to use an empty list
when no installed verification contract was requested.

Build-record exports contain report descriptors; consumers need the retained report
bytes to read the outcome. `verify_artifacts` verifies those bytes but does not
interpret or endorse their assertions. Build-trace can resolve the execution
references for human-readable commands and invocation-scoped logs. Keep the report
artifact for as long as its generation is retained.
