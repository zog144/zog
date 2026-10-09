# host-install identity preparation — pass 1

This source-only pass implements transaction primitives for the proposed
state-contract-v1. It does not implement live mount verification, root-owned
installer authorization/consumption, station recovery admission, or remote control.
The proposal is not yet present in host-install unstable
bb7f84a5dfb221c4dd266d5254e9e80be2a98228. No live host was changed.

## Coordinator contract

host-install must verify the intended mounted STATE, fixed account mapping,
permissions and schemas, and inspect its root-owned operation record before
calling these APIs. Run key operations as host-discover (proposed UID/GID 970).
Provision `/state/host-discover/identity` as 0700; do not put keys in images.
A `mode: fresh` bootstrap value is never sufficient authorization.

The proposed library authorization object has exactly these fields:

```python
authorization = {
    "schema": 1,
    "kind": "zog-identity-initialization",
    "authorization_id": "<canonical UUID from active installer transaction>",
    "installation_id": "<canonical installation UUID>",
    "state_volume_id": "<canonical STATE volume UUID>",
    "identity_directory": "/state/host-discover/identity",
    "account_profile": "zog-host-accounts-v1",
    "expected_fingerprint": None,
}
```

`zog.host_identify.initialization.prepare(directory, authorization)` prepares and
publishes one Ed25519 key and returns a public receipt. The dictionary is NOT
self-authenticating: the privileged coordinator must obtain it from a verified
active operation, never from a network request or arbitrary JSON file. This API
is not an enrollment or provisioning-preapproval endpoint.

The receipt has schema 1, kind `zog-identity-receipt`, authorization SHA256,
authorization_id, installation_id, state_volume_id, and fingerprint. The digest
is SHA256 of the module's canonical UTF-8 JSON encoding (sorted keys, compact
separators, final newline). No private bytes appear in the receipt.

The coordinator must durably commit that exact receipt as consumption of the
root-owned transaction. Only then may an admitted daemon call
`initialization.load_existing(directory, consumed_receipt)`. The caller must
verify receipt ownership, coherent committed configuration, volume binding and
absence of recovery holds. Passing the service-owned receipt back to the loader
without verifying independent installer consumption is NOT admission.

Consumption is idempotent for the same transaction and receipt. Conflicting
consumption is an error. If the coordinator crashed after key publication, it
resumes the same unfinished transaction, verifies the receipt, then consumes it.
A consumed operation with missing material goes to recovery, never prepare.

## Persistence and interruption semantics

All file operations are anchored to an opened directory walked without symlink
ancestors. Files are service-owned 0600 and the directory 0700. `key.lock` is
shared with the legacy implementation; it is never unlinked. Files are bounded,
regular, and not multiply linked, except for the recognized transient atomic
publication link that prepare can reconcile.

The transaction record, prepared-key.pem and public receipt.json are persisted
before publication of identity.pem. Publication is atomic and does not overwrite
an existing identity. Repeated/concurrent preparation returns the same receipt.
The private staged key is retained in the protected identity directory for this
v1 recovery protocol and must receive the same protection as identity.pem.

A crash after durable preparation resumes that same key. A crash before the key
is durably prepared, a partial/corrupt file, a missing prepared key, conflicting
candidate, changed authorization, or foreign key causes refusal. In particular,
an initialization.json without prepared-key.pem does NOT cause fresh generation
on retry. The installer must expose this as recovery-required, not delete files
to make a retry succeed. Fsync errors propagate and prevent successful return.

These are local persistence protections, not protection against a compromised
service account, privileged filesystem substitution, or restoration of all state.
The caller still needs verified mounts, runtime mount-loss handling and independent
station recovery/session history. Keep unresolved controller operations intact.

## Legacy compatibility

`storage.load_existing_key(directory)` loads an existing non-managed legacy key
without creating a directory, lock or key. The existing legacy key.lock must be
present; marker checks run under that shared lock to exclude concurrent managed
initialization. Missing locks require explicit reconciliation. `storage.load_key` retains its historical
implicit creation behavior only for legacy, non-/state, non-transaction directories.
Both reject managed identity directories: managed loading requires the consumed
receipt API. No existing enrollment, UUID, key, signature or token format changes.

Migration/adoption of existing identities is deliberately not implemented by the
fresh initializer. A separate audited installer operation must define that path.

## Verification

Tests exercise repeated and concurrent initialization, independent-process reuse,
interruption at durable boundaries, link/unlink crash recovery, permissions,
symlinks, fsync failure, corrupt/missing files, foreign keys, conflicting candidates,
receipt mismatches, unknown schemas and absence of implicit replacement. Tests use
temporary directories and synthetic installer authority; no real STATE mount or
privileged coordinator acceptance is claimed.

## Pass 2: descriptor-bound consumption reads (0.3.2)

`initialization.load_existing_fd(fd, identity_directory, completion)` reads the
consumed identity relative to a retained directory fd supplied by the verified
STATE caller. It never reopens the canonical path, creates a lock/file, or closes
the caller's fd. The name is compared with the recorded authorization. Unexpected
publication candidates, missing independent completion, noncanonical authorization
bytes, unsafe files, and receipt/key disagreement fail closed. The path-based
`load_existing` now delegates to this implementation after opening its directory.

The caller still authenticates the privileged consumption record and rechecks the
mount before/after reads; passing the service-owned receipt itself is insufficient.
Tests replace the original path while holding the old descriptor and confirm that
only the originally opened identity is loaded. This does not authorize network
transport or solve privileged initialization/consumption publication.

Authorization SHA-256 uses `encode()` including its final newline. host-install's
canonical record digest omits the newline and belongs to a different domain.
