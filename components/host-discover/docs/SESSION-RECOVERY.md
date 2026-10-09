# Explicit expired-session recovery v1

Host-discover 0.4.5, host-identify 0.3.4 and station-access 0.4.20 add a bounded
operator procedure for an accepted managed-session response lost until expiry.
Keep host-install 0.4.3's persistent listeners, KillMode=mixed and 90-second stop
budget. No producer change, boot reset, remote command or automatic repair is added.

## Contract and ownership

The station's `/api/hosts/<host UUID>/managed-recovery/` accepts signed POSTs from
the currently approved host key, using the existing HTTPS origin and HTTP nonce
replay checks. It rechecks approval/archive state under the identity lock. Body:
`version:1`, `operation_id` (canonical UUID), `journal_sha256` (hex SHA256),
`pending` (the complete unchanged v1 session request).

Only an exact retained request match with expired session claims and consistent
identity/epoch/checkpoint yields evidence. Unknown, unexpired, revoked, conflicting
or superseded history refuses. No session, epoch, checkpoint or approval changes;
HTTP nonces are consumed as usual. Repeated queries need fresh signatures and may
refresh the evidence lifetime, never the session lifetime. There is no new DB schema.

Response: `version:1`, `public_key`, `evidence`. Evidence is an Ed25519 JWT with
`typ:zog-managed-expiry-evidence-v1` and a fingerprint kid. Claims are exactly:
`iss aud sub iat exp jti operation_id journal_sha256 request_sha256 fingerprint
installation_id state_volume_id registry_id epoch checkpoint session_expired_at`.
Issuer is the configured HTTPS origin; audience is the configured authority UUID;
subject is the host UUID; jti equals operation_id. Lifetime is at most 300 seconds,
and the accepted session expired no later than evidence issuance. Request SHA256
uses canonical sorted compact ASCII JSON, with no NaN values. Evidence is not a
session token and cannot authorize a heartbeat or controller command.

Host-identify owns envelope verification. Host-discover verifies the exact journal
and request digests, all identity/configuration bindings and a single-epoch advance.
An established station key must match its pin. For a lost *first* session response,
no key has yet been checkpointed: root must independently confirm and supply the
station key fingerprint. Copying the fingerprint from the untrusted evidence file
is not independent verification. Existing pins cannot be overridden with this flag.

## Operator procedure

1. Stop the beacon, inspect the original failure and confirm healthy STATE/identity
   and no installer hold. Keep the producer admission listener available. Record
   `host-discover-supervisor inspect` revision and run ID. Do not reset first.
2. Choose a new recovery operation UUID. As UID/GID970 with the configured service
   groups, run `host-discover-recovery evidence --operation-id <UUID>` and retain
   stdout as a bounded JSON evidence file. For example, root may redirect stdout
   from `sudo -u host-discover -- host-discover-recovery evidence ...` into a
   root-owned 0600 file under /run. This uses the existing private key only as the
   service account; the root recovery command never loads it. No journal is changed.
3. As root, run:

   ```sh
   host-discover-recovery apply --operation-id <UUID> --revision <inspected revision> --run-id <inspected run UUID> --evidence-file <absolute JSON file> --reason '<operator reason>'
   ```

   Only first-session recovery additionally requires
   `--station-key-fingerprint <independently confirmed SHA256 fingerprint>`.
   The evidence must still be valid when first authorized. Root checks the stopped
   consumer lock, fresh producer admission, protected digest, identity and exact
   revision/run before durably authorizing this one transition.
4. On interruption, use `host-discover-recovery inspect`, then explicitly
   `host-discover-recovery resume --operation-id <same UUID>`. Resume requires root,
   stopped consumer and healthy matching STATE. A stage-only interruption happened
   before durable authorization: rerun apply with fresh evidence and unchanged
   revision/run. Never delete state to unblock recovery.
5. Successful recovery returns session-reconciled and the new supervisor revision.
   It preserves the original run/fault. Inspect again and use the existing
   root-only compare-and-set `host-discover-supervisor reset` with that revision,
   original run ID and a reason; then start the beacon. The next normal session
   request advances from the recovered checkpoint using a new request identity.

Do not automate this command in systemd. The command only reconciles one expired
request; root reset remains a separate explicit decision about the original fault.
Restoring permissions or removing a hold alone never authorizes either action.

## Durability and retained evidence

Root directory `host-discover-supervisor` remains 0700. Its recovery.json (0600)
binds operation, reason, acceptance time, signed evidence, original and target
journal and ledger snapshots. Capacity is 65536 bytes; oversized recovery refuses
before any target write. Normal supervisor operations/reset reject an in-progress
record or temporary file. The record is durable before journal changes, then the
journal is fsynced before the protected digest advances. Fault, run, identity,
replay entries, other registry state and reset history are preserved.

Explicit resume accepts only the recorded old or new states, and only old→new
ordering. It recreates partial recovery-owned temporary files from the protected
record. It revalidates the signature at the *recorded authorization time*, allowing
completion after evidence expiry. Unknown state and interrupted ordinary writes
remain blocked; this is not general torn-write repair. All original filesystem
ownership, no-symlink, bounded-read, mount and exclusive-lock checks remain active.

Completion renames recovery.json to last-recovery.json (one bounded protected
receipt, replaced only on later successful recovery). It retains the resolved
pending request and prior checkpoint as evidence. Repeating resume of the last
completed operation succeeds only while its resulting state is still unchanged.
Stale authorization cannot apply after the journal or supervisor advances.

The signed station evidence is a snapshot, not a lease: concurrent station history
changes can make the next normal session fail its checkpoint check. They never
permit silently skipping epochs. Key rotation, missing station history, whole-STATE
rollback, hostile root/service-account compromise and general disk repair are out
of scope. Local tests simulate mount/account evidence and expiry; a new isolated
live recovery acceptance run remains required. The earlier outage acceptance is
not repeated or claimed as acceptance of this new recovery operation.
