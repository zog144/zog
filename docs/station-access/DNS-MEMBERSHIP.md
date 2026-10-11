# Shared DNS membership — station-access 0.4.17

Requires network-register 0.11.0 at the exact handoff commit. This is a source
release; no running host, credential, domain registration or DNS record was changed.
The earlier immutable cutover review and legacy recovery files must be retained.
No additional Django schema migration is required for this feature. Apply the
release's ordinary migrations when installing alongside other unstable changes.

## Enroll a new host

Approve the exact host key and wait for fresh signed evidence and account-scoped
AWS inventory. On the host page choose a DNS label, review the reservation, then
confirm. The service checks enrolled cloud identity, running state, matching public
IPv4, observation freshness, current credentials, DNS authority, provider inventory
and name availability. The review itself saves only an owner-only review file.
Commit reserves the name, creates pending publication intent and adds the host to
the shared worker's durable membership. The worker rechecks evidence before writing.
Display-label changes do not rename a reservation. There is no automatic enrollment
into the shared writer based only on receiving an arbitrary beacon.

## Unpublish and release

Unpublish records explicit intent; it deliberately keeps ownership of the name.
After reconciliation has confirmed absence, choose Review name release and confirm.
Release checks the exact local tombstone/reservation and current provider absence,
then removes the assignment and membership. It preserves operation receipts,
allocation generations and a full SecurityAudit snapshot. A stopped/revoked host
does not need to send another beacon to release an already-unpublished name.
Other archival blockers, including key revocation and token expiry, still apply.
Release does not terminate EC2, revoke keys or archive a host.

Both reservation and release make zero provider writes. The normal shared worker
performs subsequent A-record writes. Reusing the same host starts above its old
operation revisions; old unprepared plans cannot reclaim a released allocation.
Cloudflare publication TTL is 300 seconds, Porkbun policy is 600 seconds. The
current station cutover setup remains Cloudflare-only; this pass does not introduce
a Porkbun station writer migration or claim live Porkbun acceptance.

## Operator equivalents and recovery

Run these through the installed release's Python/management command environment:

```
python manage.py manage_host_dns review --host-id UUID --change reserve --label compiler
python manage.py manage_host_dns review --host-id UUID --change release
python manage.py manage_host_dns commit --approve-review REVIEW_SHA256
python manage.py manage_host_dns status
```

The web API is administrator-only and additionally requires the selected owner.
POST `/api/hosts/UUID/dns-membership/` with `action` and optional initial `label`
returns the review; POST the same route with only `review_id` commits it. A review
cannot be committed through another host's route. The root operator CLI uses the
configured owner; it is not a remotely exposed authority bypass.

A membership change first writes a durable pending fence. Reconciliation and other
intent changes stop while it is pending. The ledger allocation and Django projection
are separate transactions: an idempotent name receipt plus the transactional audit
let the same commit resume after either transaction. Repeat the exact review ID;
do not delete state or generate replacement reviews to clear a pending change.
The UI retains the reference and exposes Resume after an interrupted request;
after a browser reload recover the pending review ID using `status` and the CLI.
If enrollment evidence became stale, refresh the normal signed/inventory evidence
and retry. Current owner/credential authorization remains mandatory during recovery.

If a prepared change failed *before* any name receipt or Django audit exists, an
operator may use `manage_host_dns cancel --approve-review REVIEW_SHA256`. Cancellation
is refused after either side changed. Completed and cancelled reviews cannot be
reapplied as new changes. Preserve the ledger, reviews and registry DB together in
backups. Loss of activated membership metadata fails closed. An empty membership
is valid and the worker performs no writes until another reviewed enrollment.

Before a future live upgrade, test the installed service interpreter/dependency
versions, authenticated host inventory and lifecycle routes, and pending status.
Then use a disposable enrolled host for review/confirm, one publication, unpublish,
release and reuse. Check that provider IDs change only as intended and unrelated
records remain unchanged. No funded registrar account or domain purchase is needed
for these existing-zone checks. This acceptance remains outstanding.
