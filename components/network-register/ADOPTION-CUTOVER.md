# Reviewed adoption and read-only recovery — network-register 0.10.0

`RecordAdoption(engine).adopt(...)` imports explicitly reviewed existing Zog/legacy
records into the shared ledger without modifying the provider. The station-access
companion supplies the review, freezes the old writer, and activates the shared
worker after validation. It does not infer ownership from matching DNS values.

Each item supplies `resource_id`, canonical `name`, exact `record_id`, `snapshot`,
`marker`, and `desired_revision`. A snapshot contains name, public IPv4 address,
effective TTL, type A and proxied=false. Adoption accepts Zog operation markers
and the existing `Zog network-register owner <sha256>` marker. It does not adopt
arbitrary unmarked/foreign-comment records in this pass. An explicitly reviewed
absent assignment uses null record ID, snapshot and marker; full authorized
inventory must confirm absence, and its name remains reserved to the resource.

The caller supplies owner, binding, request ID and expected connection/binding
revisions. Every target is checked against current authority, exact account/zone,
provider inventory, name/prefix, record ID, content/TTL/proxy/marker, and conflicting
A/CNAME/DNAME/NS records or ancestor aliases/delegations. The entire batch commits
records, reservations and the adoption receipt in one durable local transaction.
Authorization and scope are rechecked after network reads. Failed storage rolls
back the batch. Identical request/payload replay returns its receipt; changed
payload, resource/name collisions, existing reservations, or unresolved operations
fail explicitly. Retain adoption receipts and legacy evidence.

Adoption preserves the existing comment and effective TTL. A later ordinary update
uses the exact adopted ID and writes the normal operation marker. Thus a legacy
Cloudflare TTL of 60 is adopted as 60; first desired publication at policy TTL 300
is an ordinary journaled update, not part of migration. Unchanged desired and
observed snapshots cause no provider mutation.

`DnsEngine.recheck(actor, owner_id, request_id, expected_revision)` explicitly
opens another bounded read-only verification window for an uncertain operation.
It records authorization and the operator decision, preserves the saved payload,
record IDs, marker and step key, and never repeats the provider write. The worker
then advances verification normally. Prepared, completed or conflicting operations
cannot use this API to bypass conflict handling. Revoked/replaced credentials are
not substituted. A persistent conflict still requires operator investigation;
there is no force-repair or automatic state deletion.

The engine also now recognizes DNAME conflicts while inspecting managed names.
This change does not add DNAME writes or alter registrar capabilities.

Verification: 209 network-register fixture tests pass, including atomic adoption,
absent reservations, marker/ID/content drift, batch rollback, replay conflicts,
revocation during reads, post-adoption updates by ID, and read-only rechecks.
No live provider acceptance, DNS mutation, domain purchase, or deployment occurred.
The operator workflow and deployment prerequisites are in station-access's
`docs/DNS-CUTOVER.md`.
