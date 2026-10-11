# Managed session and inspection envelope profiles v1

`zog.host_identify.managed` uses maintained PyJWT with Ed25519 (`EdDSA`) only. Headers
must be exactly alg, typ and kid; kid is the pinned key fingerprint. Remote key URLs,
other algorithms, unexpected fields, invalid UUIDs and lifetimes over 300 seconds
are rejected. No expiry clock tolerance is granted by this profile.

Session typ is `zog-managed-session-v1`. Required claims bind issuer HTTPS origin,
audience authority UUID, immutable host subject, host fingerprint, installation and
STATE volume UUIDs, registry ID, process challenge, boot ID, previous checkpoint,
new epoch/checkpoint, jti, integer iat/exp and the sole operation `inspect`.
`session()` compares all caller-supplied expected bindings. The caller authenticates
initial station key establishment through the configured verified HTTPS origin and
pins it durably. Later substitution requires an explicit transition; automatic key
rotation is not supported here. The verifier never chooses keys from remote headers.

Command typ is `zog-managed-command-v1`. Commands bind issuer, audience, host subject,
jti request UUID, current session_id, runtime UUID, operation and expiry no later
than the session. Only `inspect` is accepted. The caller must durably record request
admission before local execution; signature verification alone is not replay storage.

Result typ is `zog-managed-result-v1`; host signing binds the result to the request
jti, host subject and session_id. Consumers must compare those expected values after
`verify()`. The generic verifier checks signature/profile/issuer/audience/lifetime;
it is not an authorization decision or automatic correlation check.

Dedicated station control keys must not be reused for archive tokens or rootfs
release signing. These profiles are integration scaffolding: production managed
transport remains disabled until full admission and joint acceptance are complete.
