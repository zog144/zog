# Workspace lifecycle and recovery

New workspaces are dormant. Creation allocates a workspace number only. First use
allocates display/port values, persists running intent, and creates a launch request.
Workspace identity and allocation survive server replacement.

One per-workspace host-local `flock`, plus an in-process lock, serializes requests and
reconciliation across Django workers. The allocation lock serializes numbering and
display reservations; database uniqueness also protects numbers and endpoints.
No database transaction spans a call into box-control. This pass supports one host
and one shared state directory; it is not a distributed-lock design.

Launch sequence:

1. Persist endpoint and typed parameter values.
2. Obtain a controller request ID and commit it with `launch_pending=True`.
3. Call box-control with the recorded parameters and identity.
4. Persist exact runtime identity and clear pending state.
5. On connection demand, check current runtime facts and a bounded RFB banner.

A lost launch reply is recovered from a matching retained runtime (including its
parameter values), or retried with the original request ID. If the identity expired
and no evidence remains, the workspace faults rather than issuing a new request.
Missing previously-bound runtime evidence also blocks replacement. A proven terminal
runtime can be replaced with a fresh request ID and the existing endpoint assignment.

Stop commits stopped intent first and invalidates grants. A pending launch is resolved
through `cancel_application_launch`: this cancels an unstarted request or returns the
accepted runtime for exact termination. Recovery may first finish an already accepted
controller operation under the existing durability rules. Cancellation does not issue
a new launch. Ambiguous controller recovery remains blocked.

Endpoint changes and runtime replacement invalidate readiness, increment endpoint
revision, and revoke outstanding grants. Grant resolution rechecks current runtime,
active user, ownership, runtime identity and endpoint revision. Closing a viewer has
no effect on desired-running state.

`require_workspace_number` is the shared authorized first-use function for graphical
application integration. An RFB banner is a preliminary server gate; X11 authentication
and cross-program socket/mount plumbing still require the image-build integration pass.

Migration preserves existing identities/endpoints. Legacy pending launches without
recorded parameters require explicit recovery using the original controller; this pass
does not guess bindings for them. Admin cannot directly edit lifecycle fields or delete
workspace rows, avoiding orphaned runtimes. Workspace deletion is not implemented.
