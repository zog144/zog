# Pending build-root registration

A successful send followed by `RootControlReplyTimeout` for `build_register`
leaves an uncertain registration, not a failed build. The adapter persists
`registration-pending.json` containing the exact resource ID and registration
intent before its existing bounded inspection window. No command is dispatched
until the controller confirms readiness.

If that window expires, `BuildRegistrationPending` identifies the resource and
last observed phase. Supervisors using `glibc_final.wait_for` record registration
progress separately from command progress, wait 15 seconds, and revisit the same
operation. Native tools, including Rust, use this shared supervisor loop.
One-shot callers receive the pending exception and must explicitly resume their
saved pipeline. They must not create a replacement attempt.

On continuation, the adapter checks the saved binding and uses the read-only
inspection API. `importing` and `absent` remain pending; neither authorizes a new
registration mutation. Only `ready` allows exact registration reconciliation,
which lets box-control clear its own recovery guard. The pending marker is then
removed durably. Controller identity checks and prepared command checkpoints
continue to apply. Changed intent, released resources, unrelated recovery faults,
and inspection failures stop continuation instead of being silently retried.

A stopped root-control worker can leave an importing/absent registration pending
indefinitely. This mechanism does not infer worker liveness or restart the daemon;
operators must diagnose that condition. Storage integrity and fsync requirements
are unchanged. Existing deployed/frozen operations retain their original code;
use this implementation at the next operation boundary.
