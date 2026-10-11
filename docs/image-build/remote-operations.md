# Remote image-build operation contract

Contract: `image-build-remote-operation-v1`.

This interface is the transport-neutral boundary between image-build and callers such
as host-deploy, station-access, or a future GitHub/SQS dispatcher. Image-build does
not know which transport requested an operation.

Every request binds:

- a client operation ID;
- an operation type;
- the exact authorized source repository identity;
- the exact immutable deployed commit revision;
- operation arguments;
- an optional predecessor operation ID.

The adapter is invoked from that exact deployed checkout. A request whose repository
or revision differs from the deployment is rejected before execution. Reusing an
operation ID with different input is rejected.

## Operations

Initial operations are:

- `recipe.validate`: parse reviewed recipes and verify the monthly `commit-pin.py`.
- `package.inspect`: report source identities, dependencies, outputs, licensing and
  source provenance for one package.
- `dependencies.resolve`: return deterministic dependency order for arbitrary
  reviewed targets.
- `pipeline.submit`: prepare and continue an `image`, `bootstrap`, `seed-check`
  or `native-check` pipeline.
- `pipeline.inspect`: bounded read-only summary of an existing pipeline.
- `pipeline.resume`: continue an adapter-owned pending pipeline only with its
  originally bound repository/revision.
- `pipeline.cancel`: durably bind an explicit cancellation request, cancel any
  retained controller jobs by their existing identities, wait for process cleanup,
  then release pipeline resources without deleting retained evidence.
- `pipeline.retry`: create a new pipeline after a predecessor has authoritative
  terminal failure evidence and no unresolved outcome. The predecessor is explicitly
  released; its recipes, attempts and failure evidence remain retained.
- `generation.inspect`: verify and report a published generation inventory and
  provenance locators.
- `diagnostic.submit` / `diagnostic.inspect`: execute or inspect a reviewed,
  repository-pinned diagnostic definition.

Pipeline preparation and execution are separate internally. The pipeline ID and its
owner/source binding are durable before the first command submission. If a caller
loses the reply, repeating the same operation discovers that exact pipeline rather
than creating another one. Calls carrying the same remote operation ID are serialized
by a per-operation file lock before request or binding creation, so concurrent
duplicate dispatchers cannot allocate competing durable state.

## Request

Example:

```json
{
  "schema": "image-build-remote-operation-v1",
  "operation_id": "oct1-gcc-pass1",
  "operation": "pipeline.submit",
  "source": {
    "repository": "zog144/image-build",
    "revision": "0123456789abcdef0123456789abcdef01234567"
  },
  "arguments": {
    "mode": "image",
    "selection": "<64-hex toolchain generation>",
    "targets": ["gcc"]
  }
}
```

The CLI is:

```sh
python3 -m zog.image_build.remote_operations \
  --repository-root /absolute/deployed/source \
  --source-repository zog144/image-build \
  --source-revision COMMIT \
  --package-dir /absolute/deployed/source/project/package \
  --state-dir /absolute/lane/project/state \
  --controller-config /absolute/lane/project/controller.json \
  --provenance-host-id HOST-ID \
  --provenance-project-id zog-compiler-view \
  --expected-pin-digest sha256:EXACT-COMMIT-PIN-DIGEST \
  request.json
```

Host-deploy is responsible for obtaining and authorizing the source checkout,
transporting the request, AWS/SQS/IAM concerns and selecting the lane. For a
production lane, image-build captures the exact deployed `commit-pin.py` bytes into
build-record provenance and refuses execution when their SHA-256 differs from the
lane binding. Image-build
owns request meaning, recipe/pipeline identity and recovery.

## Result

Every response uses `image-build-remote-result-v1` and is bounded. Core fields include:

- operation ID/type and exact source repository/revision;
- recipe, pipeline and attempt identities;
- selected generation;
- package/stage/phase where known;
- status and terminal outcome;
- bounded failure reason;
- controller job IDs and observed exit/outcome fields;
- journal/evidence locators and bounded sanitized log excerpts when the configured controller is available;
- generation/artifact and provenance locators; generation inspection includes a bounded inventory prefix, total count, truncation flag, full inventory digest, and the durable manifest locator;
- uncertainty and explicitly missing evidence;
- allowed next operations;
- predecessor operation.

The response is an observation of image-build/controller state, not recovery
authority. Full logs remain in journald/controller storage and full artifacts remain
in durable image-build stores.

Status meanings:

- `completed`: authoritative operation completion was verified.
- `failed`: terminal failure evidence exists.
- `pending`: the same identity requires inspection/continuation.
- `released`: the pipeline was explicitly abandoned/released.

A controller failure whose process cleanup is explicitly unresolved also remains pending and is never offered for retry. An unknown controller outcome remains pending with `uncertainty=true`; retry is not
offered. Pending pipelines may be explicitly cancelled. Cancellation never creates a
replacement command identity: it reconciles/cancels the retained controller jobs,
requires process cleanup, and only then marks the pipeline released.

## Explicit retry

A failed recipe is never modified in place. A corrected commit uses a new remote
operation ID and `pipeline.retry` with `predecessor` referencing the failed remote
operation. The old pipeline must still classify as a resolved terminal failure.

A new source revision is allowed for the retry. That creates a new snapshotted
pipeline while retaining the old source revision, recipes, command evidence and
failure.

## Diagnostics

Diagnostics are repository source, not issue-body shell.

A diagnostic is stored at:

```text
project/diagnostic/<name>/
    diagnostic.json
    <script>.py
```

The declaration fixes the Python script, guest interpreter, timeout, memory maximum,
thread maximum, CPU weight, output-byte limit and result paths. Requests may only add
a bounded argv vector and select a retained target generation.

Diagnostics:

- use an immutable selected generation as a read-only build root;
- copy only the reviewed pinned Python diagnostic source into the source workspace;
- run through the existing box-control/root-control finite-build mechanism;
- have no host privileges;
- have network disabled by the current build protocol;
- receive their own controller request/job identity;
- retain output hashes and controller/journal locators;
- remain linked to the exact remote operation/source revision.

Networked diagnostics require a future separately reviewed protocol change; this
contract does not weaken root-control's current `PrivateNetwork` policy.

## Concurrency / build lanes

Image-build remains intentionally serialized **within one state directory**. Concurrent
independent builds use different box-control Project roots/state directories on the
same host. This preserves each lane's:

- `image-build.lock`;
- pipelines, attempts and generations;
- box-control mutation guard/build records;
- root-control build resources.

Root-control already scopes privileged resources by the full project root. Build
requests additionally support optional systemd `CPUWeight` alongside the existing
per-job MemoryMax/TasksMax. Host-deploy owns host-wide lane admission.

Do not share mutable attempts/generations between lanes. A lane deliberately rejects
a second unfinished pipeline while another lane, backed by a different state
directory, may prepare and execute independently. Archive-mirror is the intended
cross-lane source-byte cache.

## Remaining interactive/administrative work

The remote contract deliberately does not provide:

- host-level package installation or privileged shell access;
- root-control/systemd service administration outside finite build jobs;
- EC2 provisioning, stopping, rebooting or filesystem repair;
- replacement of uncertain controller submissions;
- automatic retries;
- network-enabled diagnostics.

Those remain host-deploy administrative operations and, until their gateway contracts
are implemented and accepted, may still require Work/live-host execution.
