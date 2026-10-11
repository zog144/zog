# Experimental managed session producer

Migration 0012 adds ManagedAdmission, one protected history row per host. It is
additive and preserves existing UUIDs, approvals, labels, DNS and audit history.
The endpoint is disabled by default (`HOST_MANAGED_ADMISSION_ENABLED = False`).
Set `HOST_MANAGED_ADMISSION_ENABLED=1` only for an explicitly configured managed
beacon station with a dedicated authority/key. This pass provides the environment
switch for isolated acceptance; it does not enable deployed installations.

Local integration fixtures explicitly override that setting and provide
HOST_MANAGED_AUTHORITY_ID and HOST_MANAGED_SIGNING_KEY_FILE. The latter is a dedicated
service-owned Ed25519 private key file, mode 0600, in a protected directory. It must
not be an archive issuer or root filesystem release signer. Keys are never generated
or exported by this endpoint. Establishing the authority UUID or rotating its key
requires coordinated provisioning; no automatic trust replacement is implemented.

`POST /api/hosts/<UUID>/managed-session/` requires the existing approved active host
key's RFC 9421 signature and replay nonce. Its closed request fields are version=1,
installation_id, state_volume_id, authority_id, registry_id, challenge UUID,
previous (null initially, then {epoch,checkpoint}), and boot_id. Reported installation
claims do not replace operator fingerprint approval or host-local admission checks.

Verification occurs before the shared security write lock; key approval/public-key
binding and archival state are checked again under it. Session creation, approval,
revocation and heartbeat acceptance share the same lock. The initial request binds
installation/volume/authority/registry permanently. Later mismatches refuse. Every
new request must present the current checkpoint; independent station history is not
reconstructed from host claims. Identical retried payloads return the same unexpired
claims, signed again; repeated HTTP signature nonces are rejected. A lost response
past expiry needs explicit future recovery, not an automatic checkpoint reset.

The response (Cache-Control: no-store) contains version=1, public_key and a signed
session token. Tokens last 300 seconds with no skew allowance. They bind the exact
request, host fingerprint, issuer origin, authority audience, epoch/checkpoint and
an inspect-only scope. A new session invalidates earlier session IDs. Session tokens
are not bearer authentication for heartbeat: the approved host signature is required.

After a ManagedAdmission row exists, ordinary/legacy heartbeat fallback is denied.
The signed heartbeat body must include managed_session with the current unexpired
session ID. It is removed before report persistence; the response echoes that ID.
Revocation stops session/heartbeat acceptance under the same security lock. Session
claims, control keys and tokens are not added to ordinary host-list/admin responses.
Rows and audit events remain when records are archived; no automatic history reset.

Command queueing, administrator command UI, remote delivery and production gateway
composition are not implemented. The joint test invokes the restricted read-only
inspection interface directly and validates its host-signed result. It is a local
Django/controller fixture, not a live remote-control acceptance test. The narrow `--managed-state` consumer remains diagnostic-only. The additional
0.4.1 `--managed-beacon` profile requires a separately provisioned root supervisor
and permits enrollment/session/heartbeats only. It rejects all remote commands.
Combined live supervisor/beacon acceptance remains pending; default enablement
remains off. See host-discover docs/BEACON-SUPERVISOR.md for composition and recovery.
