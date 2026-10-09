# Optional build inspection contract, version 1

`zog.zog.image_build.trace_records` owns optional inspection records alongside durable
execution records. Build-trace 0.3 consumes these records read-only. Execution,
resumption, cancellation and acceptance never consult them. Existing controller
checkpoints and runner completions remain the execution authority.

| Suffix | Contents | Update rule |
|---|---|---|
| `.trace.json` | schema/origin, attempt/command/package/stage/phase/index/pipeline, title, category, provenance, relationships, receipt references | First successful capture is immutable |
| `.summary.json` | schema/origin, redacted argv/environment/cwd/settings and policy; optional imported request ID | First successful capture is immutable |
| `.observation.json` | schema/origin, request/job IDs, observation time, selected controller execution/cleanup/error/journal fields | Replaced after a validated owner observation |

All have `schema: 1`. Origin is `captured` or `imported`. A title includes the
package, phase and zero-based command index, stage and immutable attempt ID. An
attempt ID is not a chronological attempt number. Engine captures include the
package fingerprint, prepared input identities, source declarations and the
pipeline source-pin identity when available. No current
recipe reconstruction occurs. A missing pipeline source-pin identity is null and an uncaptured package version
stays absent; source declarations may contain versions in URLs but are not parsed to guess.

The engine writes identity before its runner call; the runner captures the request
before execution. The controller adapter also captures requests for direct callers,
then observations after validated submission/inspection and each refresh it already
performs, plus the result of an already requested job release. This adds no controller calls. A crash after submission but before an
observation leaves the existing checkpoint as prepared evidence, not proof of
execution. Existing owner retry/resume logic reconciles that identity. A stored
observation is historical, including its boot ID; inspection cannot detect a later
reboot from that record alone. Normal workspace cleanup retains these small files.

Capture writes use atomic replacement and fsync under the caller's existing lock.
Each serialized record is at most 256 KiB; at most 32 relationships and 32 receipt
references are allowed. Optional write/serialization failure logs a generic warning
and returns false. Automatic engine identity capture also contains validation errors.
It does not fail execution or replace its original exception. An immutable record
with different contents returns false and is not replaced. Readers validate identity
conflicts and report an error rather than silently choosing a different identity.

Before persistence, environment values are allowlisted and known credentials,
secret assignments/flags and URL passwords are redacted. This is conservative
filtering, not universal secret detection. Exact private execution bindings are
unchanged and remain subject to existing owner access controls. Inspection records
and exports should remain administrator-only. Records are never recovery inputs.

## Diagnostics and retries

New diagnostic/retry orchestration calls `capture_identity` under its operation lock
before the ordinary runner or adapter, using `category='diagnostic'` or `'retry'`.
The GCC diagnostic worker uses this contract and links the exact failed job.
Supported command locators are a root-level stem or the existing package/fixture
stem layouts. Explicit relationships have exactly this shape:

```python
relationships = [{
    'relation': 'retry-of',  # or diagnostic-of
    'target': {'attempt_id': original_attempt, 'command_id': original_command},
}]
# Alternatively, target={'job_id': exact_original_job_id}.
```

Relationships do not replace the original failure, waive tests, establish promotion
or claim a latest attempt. Nothing is inferred from timestamps or filenames. A
missing trace record means relationships were not captured; an empty list means
this record declares none. This pass does not automatically annotate other retry
workers or historical hosts.

Historical receipts need explicit adoption by their owner. Supply a verified full
controller record and exact references relative to `state/image-build`; no receipt
search, arbitrary path reading or job discovery occurs:

```python
from zog.zog.image_build.trace_records import import_diagnostic

ok = import_diagnostic(
    attempt_dir / 'focused.log', attempt_id=attempt_dir.name,
    command_id='focused', package='gcc-final', stage_id='compiler-diagnostics',
    phase='test', command_index=0, controller_record=verified_job_record,
    receipts=['attempts/gcc-fixture-pass2/focused-20261002-job.json'],
    relationships=[{'relation': 'diagnostic-of',
                    'target': {'job_id': exact_failed_job_id}}],
)
if not ok:
    raise RuntimeError('Inspection import incomplete; inspect before continuing')
```

This imports only inspection records marked `imported`; it does not manufacture
engine views, controller checkpoints, execution completions or acceptance results.
The request ID hash is checked against the job ID and retained in the immutable
summary, so reusing a locator for another job fails. Individual writes are atomic;
the three-file import is not transactional. False can leave partial inspection
metadata, with missing evidence explicit; retry the same verified import under the
owner lock. Do not reinterpret false as successful capture. Receipt references are
locators, not a claim that referenced files still exist or that journal rows remain.
