# Archive-mirror startup and consumer handoff (v1)

This release implements role intent, delivery, local reconciliation, lifecycle calls, and acknowledgements. It does **not** implement the archive-mirror application, archive transfer/scheduling code, a production serving endpoint, certificate setup for new mirrors, or a host-root execution mode. Existing bundled box-control expects immutable image-build generations. Using `/` as its rootfs is not an available shortcut.

## Signed heartbeat extensions

The RFC 9421 signature covers the actual request body, including these optional fields:

- `station_login`: `{ "username": "station-admin", "password": "..." }`, or explicit `null` to erase the central record. Omission preserves the last value. Accepted only for the exact active approved host key. Enrollment/legacy reports cannot carry it.
- `mirror_status`: `{ "revision": 1, "state": "blocked", "reason": "application-missing", "runtime_id": "" }`. Acknowledgements for an older/newer role revision cannot replace current status. `running`/`ready` requires a runtime ID. State/reason use bounded enums; exceptions and application output never enter this field.

Successful bound heartbeat responses keep `version: 2` and the existing `archive` grant/null, and add:

```json
{
  "mirror_roles": {
    "desired": {
      "version": 1,
      "revision": 1,
      "selected": true,
      "endpoint": "https://mirror-01.example.org",
      "retain_archives": true,
      "lease_expires_at": 1800000900
    },
    "candidates": [
      {
        "host_id": "d270fc26-2e8d-42d4-8188-d94bead264bd",
        "endpoint": "https://mirror-01.example.org",
        "revision": 1,
        "ready": false,
        "state": "assigned"
      }
    ]
  }
}
```

The sample timestamp is illustrative. Real leases last 900 seconds from response issuance. Candidate data is limited to selected providers with approved identities (maximum 32). Every approved beacon gets the list, including providers that do not yet pass readiness. Selection does not imply consumer access. No host login passwords, shared mirror password, or private issuer keys appear in the response. Tokens appear only inside the existing per-host `archive` envelope, governed by independent administrator policy. HTTP responses use `Cache-Control: no-store`.

Daemon behavior on older responses without `mirror_roles`: retain the last valid intent only until its lease expires; do not renew it implicitly. It never accepts decreasing revisions or different intent at the same revision. Revoked/denied signed heartbeats request a stop and clear archive grants. Existing bearer tokens remain potentially usable at a mirror until their 15-minute expiry plus the verifier's configured 5-second tolerance.

## Local protected files and consumers

Daemon-owned identity directory: 0700; key, binding, role lock/state, and optional station-login export: 0600. Never mount the identity directory into the mirror application.

Credential directory: 0750, owned by the beacon account, group `archive-consumers` (or a deliberately equivalent narrow group). Atomic files are 0640 with the same group:

- `archive.json`: existing short-lived per-host archive grant. Explicit policy withdrawal/denial clears this file. Expired grants are purged; consumers still validate expiry themselves.
- `mirror-candidates.json`: version, bound host UUID, discovery expiry, and provider list. Contains no token. Kept as metadata when no grant exists; it conveys no permission by itself.
- `mirror-intent.json`: version, bound host UUID, and desired role/lease. Contains no station login, identity key, or issuer secret. The mirror app can read this through an explicit read-only mount or local configuration.

An authorized image-build/archive consumer should use:

```python
from host_identify.mirror_access import read_access
access = read_access(
    "/var/lib/host-discover/credentials",
    public_keys=locally_provisioned_ed25519_public_keys,
    issuer="https://host-registry.hosts.example.org",
    audience="zog-archive-mirror",
    operation="download", collection="sources",
    expected_mirror="https://operator-configured-cluster-entry.example.org",
)
```

The returned object has ready `endpoints`, the host's `token`, `expires_at`, and credential `format`. Read it again before each operation: it verifies JWT algorithm, keyring, issuer, audience, subject binding, operation/collection grant and expiry, plus discovery expiry. No ready candidates means failure, not fallback to an old provider. A list cached during a temporary outage can be used only until its discovery/grant expiry; readiness is last reported state, not a guarantee a cached endpoint is currently reachable. Try another listed ready endpoint after connection failure. Set `Authorization: Bearer <token>` on the HTTPS request; do not follow redirects or place credentials in URLs, logs, shell arguments, or error diagnostics.

`expected_mirror` remains the fixed operator-configured entry point in the existing grant for backwards compatibility; candidate origins are delivered separately by the trusted controller. All current mirrors must share the explicitly configured cluster audience. Update legacy consumers from direct `read_credentials` use to `read_access` before relying on provider withdrawal: old consumers know only the old fixed entry point. Future independent mirror trust domains would require separate audience-scoped grants, not blindly forwarding this token across domains.

Each provider independently uses `host_identify.archive.verify` with locally provisioned **public** keys and fixed issuer/audience. See ARCHIVE-AUTHORIZATION.md for the reusable verifier and test fixture. Never fetch a verification key from token headers. Role election must not weaken filesystem collection allowlists or path traversal protection in the future mirror application.

## Optional box-control bridge

The default beacon remains outbound-only with no box-control project access. A locally configured optional adapter uses these supported library calls:

- `issue_application_request_id()`; persist ID before work.
- `launch_application(name, request_id=...)`; retries reuse the same ID.
- `cancel_application_launch(name, request_id=...)` to cancel an unstarted request or find an accepted runtime after a crash.
- `terminate_application_runtime(runtime_id)` for the exact runtime this controller owns; then confirm the stop via observation.
- `observe_application_runtime(runtime_id)` for all required programs, with runtime/boot identity checks supplied by box-control.

An optional local configuration (administrator-owned configuration file, never sent by the command center):

```json
{
  "mirror_box_control": {
    "project": "/srv/zog",
    "application": "archive-mirror",
    "required_programs": ["server", "refresh-scheduler"]
  }
}
```

Provision the installed matching box-control/image-build/root-control runtime, authorized project control account, supported rootfs generation, declared application, and service access before setting this. `ca_file` is an optional adapter-only custom CA for the mirror serving probe. Standard HTTPS certificate verification and redirect rejection always apply. Do not remove service isolation indiscriminately to enable it. The current restrictive systemd unit intentionally does not provide project state access automatically.

Command-center messages contain role intent, not arbitrary commands, project paths, or executable content. Only the locally installed named application can run. The app must read the public intent file to learn host UUID/revision/endpoint; the controller does not grant access to its private state directory or inject arbitrary shell parameters.

Use the application's normal scheduler member to run periodic archive refreshes (a cron process or equivalent scheduler inside the declared application). The adapter requires both `server` and `refresh-scheduler` to be observed active. Unknown/partial observations report blocked rather than treating absence of evidence as a stopped process. Confirmed failed members cause exact-runtime termination followed by persistent retry backoff (60 seconds, doubling up to 900 seconds). An uncertain launch always retries its original durable request ID. Unrecoverable/expired request evidence stays failed for administrator investigation; it does not manufacture a fresh ID to hide uncertainty. Endpoint/revision changes stop the owned old runtime before replacing it.

Provider removal/lease expiry stops the owned runtime/scheduler and never deletes archive paths or project data. A failed stop remains failed and retries; it is not acknowledged as stopped. A missing bridge or application reports blocked. The role loop runs in the beacon process; run it as a supervised service. Its persisted lock prevents concurrent daemon invocations from starting duplicate work. Filesystem and box-control operation recovery are used across restarts; no distributed host-side election is attempted.

## Application obligations and readiness endpoint

The future archive-mirror application must:

1. Read `mirror-intent.json`, require its own UUID and current selected role/revision, and refuse startup or continued scheduling after lease expiry. Re-read it on a bounded interval (recommend at most 60 seconds). Stop server/scheduler when unselected or expired even if the beacon service has died. Use the host clock with time synchronization.
2. Keep archives on an explicitly configured persistent path independent of the runtime generation; shutdown must retain them. Scheduling must not delete retained data on role removal.
3. Start an HTTPS file server and a supervised periodic refresh scheduler under the declared application; do not daemonize them outside the application's lifecycle.
4. Enforce per-request JWT authorization and operation/collection policy with fixed trusted public keys. Role selection alone is not an archive-download grant.
5. Implement a non-secret readiness endpoint:

```
GET /.well-known/zog/archive-mirror/ready
200 application/json
```

```json
{
  "version": 1,
  "host_id": "d270fc26-2e8d-42d4-8188-d94bead264bd",
  "role_revision": 1,
  "serving": true,
  "scheduler_running": true
}
```

Return true only after the collection roots/catalogue are readable, the real serving path is usable, the scheduler is functioning, and the current lease is valid. Do not include any credentials or archive bytes. The adapter requires an exact matching document, validates TLS, rejects redirects, caps the response at 4096 bytes, and separately observes required processes. A running process with a bad probe reports running/probe-failed, never ready. The next signed heartbeat reports the result. This is a host-observed serving check, not a central Internet reachability attestation or a verified download of actual archive content.

## What is tested here vs. deferred

Local fixtures exercise assignment, delivery, durable start IDs, restart/retry, stop intent, preserved archive files, blocked prerequisites, required-program observation, scoped client token selection, and verifier allow/deny behavior. No real archive-mirror application was launched, no real root filesystem was built, and no live HTTPS mirror download was performed. The archive-mirror implementation chat should implement the obligations above and then run the staged real-runtime/HTTPS acceptance tests before enabling provider roles in production.
