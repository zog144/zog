# Managed-session expiry evidence (0.4.20)

POST `/api/hosts/<host UUID>/managed-recovery/` returns a separate signed evidence
envelope only for the currently approved host's exact accepted expired request.
The same admission enable flag, dedicated signing key, authority, TLS origin,
HTTP signature and nonce replay protection as managed-session apply. Approval
and archival state are rechecked under the identity lock. No session/history/epoch
is changed. Unknown, changed, unexpired and superseded requests return 409.

Body: version 1, operation_id UUID, journal_sha256 hex digest, and complete pending
managed-session request. Response: version 1, public_key, evidence. The JWT profile
is defined by host-identify 0.3.4 `recovery.py`. It includes exact host/installation/
STATE/registry/authority, request and journal digests, recovery operation identity,
accepted epoch/checkpoint and session expiry; its own lifetime is at most 300s.
It cannot be used as a session, heartbeat credential or command.

Host-discover 0.4.5 implements the operator workflow and root-owned durable local
transaction in docs/SESSION-RECOVERY.md. The station cannot authorize clearing local
faults. Fresh station evidence remains a snapshot; concurrent history changes cause
normal checkpoint checks to refuse a stale consumer. No automatic missing-history,
key-change or station rollback recovery is introduced. No database migration or
live deployment is part of this pass.
