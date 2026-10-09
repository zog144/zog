# Archive authorization and integration contract

This release supplies a tested verifier and a WSGI fixture. It does NOT implement an archive store, upload/download engine, or a live archive-mirror deployment. A passing fixture is not live mirror acceptance.

## Issuer

Configure HOST_ARCHIVE_CONFIGURATION with the absolute path of a root/admin-managed JSON file like deployment/signed-identity/archive-issuer.example.json. It selects an HTTPS mirror origin, fixed issuer, fixed audience, active key ID, and local Ed25519 private key path. No policy defaults are granted. Approval alone returns archive:null. Set operations and collections separately under Host identities → Archive permissions. Supported operations are download and list; collections are explicit identifiers, no wildcards, paths, or implicit parent grants.

Generate a dedicated archive-access signing key as the station-access account using:

    python tools/archive-key.py --directory /var/lib/station-access/archive-access-signing --key-id archive-access-2026-01

Precreate this directory as station-access, mode 0700. The command preserves an existing key and prints only a public JSON keyring. Its private `identity.pem` must be 0600 and owned by the issuing account. Never use this key to sign root filesystem releases. Future release integrity verification needs separate keys and a separate trust decision.

The issuer uses JWT with algorithm EdDSA constrained to Ed25519. Header is exactly alg, kid, typ=`at+jwt`. Claims:

- iss: configured exact issuer
- sub: immutable Host UUID
- aud: configured single mirror audience
- iat and exp: integer seconds; lifetime 900 seconds
- jti: unique token UUID
- version: 1
- operations and collections: explicitly configured lists

Each successful authorized heartbeat mints a fresh token. Hosts ordinarily report every 60 seconds, so renewal occurs well before expiry. Each host/token is distinct. No fleet master secret or signing private key is sent to hosts.

Heartbeat archive object:

    {"version":1,"format":"zog-archive-jwt-v1","mirror":"https://mirror.example.test",
     "token":"<access JWT>","expires_at":1234567890,"issuer":"https://registry.example.test","audience":"zog-archive-mirror"}

HTTP responses use Cache-Control: no-store. Credentials are never placed in URLs, ordinary host-list responses, or audit events. Do not enable body/header capture in a reverse proxy or tracing system for machine endpoints.

## Mirror verifier

Distribute ONLY the public JSON keyring through trusted administrative configuration, not through a token-selected URL. Load it locally, validate version 1, and convert each base64 value with host_identify.signatures.public_key. Pass the resulting fixed mapping to:

    from host_identify.archive import verify
    claims = verify(token, public_keys, expected_issuer, expected_audience,
                    required_operation, required_collection)

Raises PermissionError on denial. Verification enforces EdDSA/Ed25519, exact issuer and audience, expiry, issuance time, maximum lifetime, UUID subject/token ID, and operation/collection permissions. Clock tolerance is 5 seconds. Unknown kids, other algorithms, embedded jwk, jku, x5u, crit, and extra headers are rejected. There is no remote key retrieval.

The mirror must determine required_operation and required_collection from its own route and storage mapping; never trust query parameters to reduce the required permission. Authenticate before opening the archive, honor collection boundaries, prevent path traversal, and send the credential only in Authorization: Bearer on a direct HTTPS request to the configured mirror. Do not forward it across redirects. Public verifier keys are not secrets, but their integrity is security-critical.

`host_identify.mirror_fixture.application` demonstrates three routes, two collections, and authorization for each route. Its response bytes are an explicit fixture marker, not a real archive. `tools/demonstrate.py` runs the complete pending → approval → signed heartbeat → policy → token → allowed/denied route scenario in an isolated database.

## Local delivery and consumers

Daemon private state: /var/lib/host-discover/identity, 0700 host-discover:host-discover.
Credential directory: /var/lib/host-discover/credentials, 0750 host-discover:archive-consumers.
Credential file: archive.json, 0640 host-discover:archive-consumers, atomic replacement with fsync.

Only explicitly authorized local service accounts (e.g. image-build) belong to archive-consumers. They may read the file; group users cannot replace it. Do not add general login users to that group. If all programs share one Unix account, this mechanism cannot isolate them from each other; use separate service accounts to enforce that boundary. The signing private key remains inaccessible to the consumer group.

Consumers can call host_identify.storage.read_credentials with the credential path, locally trusted public keyring, expected issuer/audience, required operation/collection, and expected mirror. It checks file modes/ownership consistency, rejects symlinks, rejects expired envelope credentials immediately (no local grace), then verifies the JWT using the same public verifier. Read it again for each download/request; do not cache a token indefinitely. Group membership and path/keyring configuration are provisioned by the administrator. The HTTP download transport is the consumer's responsibility.

The daemon authenticates delivery with TLS and checks response schema, host ID, configured mirror/issuer/audience, expiry, JWT structure and envelope consistency. It does not confuse decoding a JWT with signature verification: consumers and the mirror verify signatures independently. A malformed response or outage preserves an existing unexpired token; stale tokens are purged on subsequent daemon attempts and always rejected by consumers. archive:null and HTTP 401/403 clear local credentials. Pending/new-key enrollment clears prior credentials. Redirects are rejected without credential forwarding. The daemon logs only exception class names and acceptance status, never tokens or response bodies.

## Withdrawal, revocation, and rotation

Removing archive policy stops issuance and returns archive:null on the next successful signed heartbeat. Revoking the host key stops issuance and future signed heartbeat acceptance; a 401 clears its local credential when reachable. Previously issued bearer tokens, including copied tokens, may remain usable at the mirror for up to 15 minutes plus 5 seconds of tolerance. This release has no online revocation feed. Do not claim immediate mirror-side revocation. Replacing a host key retains that Host's separately administered policy; approving the replacement re-enables issuance under that policy.

For signing-key rotation:
1. Generate a new private key in a different owner-only directory, with a different kid.
2. Add its public key to every mirror/consumer trusted keyring while retaining the old public key.
3. Atomically change issuer configuration to the new kid/path.
4. Keep the old public key for at least 905 seconds after the last old-key issuance (and complete propagation); then remove it.
5. Remove/archive the old private key according to administrative retention policy.

Emergency removal of a public key rejects all tokens signed by it, not just one host. Keyring integrity/distribution and clock synchronization are deployment responsibilities. No arbitrary remote keys can be selected by a token.
