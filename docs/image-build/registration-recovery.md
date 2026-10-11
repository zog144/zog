# Registration timeout recovery

Root registration imports and synchronizes a filesystem before replying. A reply
 timeout does not prove that import failed. image-build preserves the resource ID
and complete registration intent before calling box-control.

With a compatible box-control providing `RootControlReplyTimeout` and
`inspect_build_root`, the adapter handles only a typed `build_register` reply
timeout in the exception cause chain. It polls durable registration status with
backoff, recording `registration-progress.json` beside the prepared root. It
replays the identical mutation API only after an observation says `ready`.
Box-control independently verifies intent and clears its own recovery marker.
No job identity is issued until registration has completed.

Recovery is limited to eight observations and a 120-second polling budget;
an already-started inspection can take up to its separate 10-second limit.
Missing registrations may still be queued, so they are observed, not resubmitted.
An import remaining unfinished, an inspection fault, a changed intent or an
unsupported older controller stops safely with retained state. Explicit resume
uses the same resource. Storage failures and job-start timeouts are never retried
by this handler. This mechanism does not waive compilation or test failures.

Deployment requires matching controller and daemon support. Older controllers
retain the previous safe stop behavior. The implementation does not make import
an asynchronous background daemon job: import stays serialized; progress reads
use the independent inspection lane while import proceeds after a caller timeout.
