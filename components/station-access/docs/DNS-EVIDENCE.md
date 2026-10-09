# Trusted DNS evidence readiness — station-access 0.4.13

This pass connects network-register 0.9.0's DNS collector and evidence policy to
station-access's authenticated host and AWS inventory records. It introduces a
read-only administrator command. It does not switch the running DNS reconciler,
adopt provider records, activate the new write engine, or change provider assets.
The existing Registries UI and legacy Cloudflare controller remain compatible.

## Upgrade and provenance

Install the exact external network-register commit in `version-share-handoff.json`
with its `dns` extra (dnspython >=2.8,<3). Apply additive host_registry migration
0011. Existing host/assignment fields are preserved. The new signed DNS fields
start empty: migration deliberately does not promote old reports into trusted
signed evidence. Wait for a new signed heartbeat and complete inventory scan.
No beaconer protocol/version change is required.

Only the verified Ed25519 heartbeat path saves `signed_dns_report` (cloud identity
and public address only), the approved key fingerprint, and an observation time.
The time is conservatively derived from the authenticated signature expiry minus
the profile's maximum lifetime and skew, never made newer than receipt. Legacy
heartbeats cannot overwrite this snapshot. The key must still be approved for
the same host; reports predating its approval do not qualify. Revocation or a
replacement key requires fresh evidence.

Inventory snapshots now include the account/region/instance identity and the
regional scan start time. A slow scan cannot make old data fresh merely by
committing it later. Account-scoped region-discovery success is recorded alongside
the existing legacy scan status. The collector requires recent successful global,
account-discovery, and regional scans, an actual observation, and no missing-host
marker. Existing older inventory JSON fails the new check until refreshed.

`RegistryEvidenceSource` reads these records under a database snapshot and feeds
`EvidenceGate`. The gate enforces equal enrolled/signed/inventory identity, public
address, exact desired snapshot/revision, and five-minute freshness. A stopped or
missing host freezes publication. Only an explicitly disabled assignment supplies
unpublish intent; old legacy auto-removal semantics are not imported into the new
policy. The legacy controller itself is unchanged in this release.

## Read-only check

Create a service-owned mode-0600 JSON selection file outside the source tree.
It contains references and explicit scope, never API secrets. Example values are
placeholders and must be replaced with the intended administrator, credential,
zone, nameservers, binding identity and existing host UUIDs:

```json
{
  "schema": 1,
  "owner_user_id": 1,
  "credential_id": "11111111-1111-4111-8111-111111111111",
  "credential_revision": 1,
  "binding_id": "reviewed-example-binding",
  "binding_revision": 1,
  "zone_id": "PROVIDER_ZONE_ID_OR_PORKBUN_DOMAIN",
  "zone_name": "example.uk",
  "prefix": "hosts.example.uk",
  "nameservers": ["ns1.provider.example", "ns2.provider.example"],
  "host_ids": ["22222222-2222-4222-8222-222222222222"]
}
```

Use an active superuser's numeric ID and the credential ID/revision displayed by
the current provider metadata. Choose the nameservers assigned to this exact
provider zone/domain, not values discovered from unrelated DNS. A binding selection
is an operator input; it grants no management rights or persisted record ownership.
The existing assignment must name one direct child of the selected prefix.
The host allowlist is explicit and limited to 256 entries.

With the station environment and database selected, run Django's command:

```sh
python -m django check_dns_evidence --settings=station_access_project.settings \
  --configuration /secure/dns-evidence-selection.json
```

The station backend must be installed/importable, and
`STATION_ACCESS_STATE_DIRECTORY` must select the intended existing station state.
The command performs DNS queries and provider GET/read operations. It neither runs
an inventory scan nor invokes `DnsEngine.apply`. Provider credentials are decrypted
only through the existing dedicated vault; their reference binds the saved revision.
Changed/removed credentials, disabled administrators, missing keys or wrong account
bindings stop the check. There is no fallback to token files or older credentials.
Porkbun's local account reference is the selected credential's stable ID; it is
not a provider-issued account identity or a way to infer a replacement account.

Output separates DNS authority, provider read access, per-host evidence, and unknown
write permission. `writes_enabled` is always false. A ready result still says
`adoption: requires-explicit-review`; it is not an approval token. No ledger,
connection, binding, or managed record is provisioned. Results expire with their
underlying evidence; subsequent engine actions must collect/check again.

## DNS collector boundary

The collector uses trusted recursive DNS to discover parent servers and addresses,
then direct nonrecursive TCP queries for parent referrals and every pinned server's
SOA/prefix evidence. It rejects aliases, subdelegations, nonpublic destinations,
wrong/lame/missing answers and disagreement. It is bounded to 45 seconds/128 queries
by default. It is not DNSSEC validation, legal ownership proof, or confirmation that
a provider-applied record has propagated. Ambiguous shared parent/child hosting is
rejected. See network-register's `DNS-COLLECTOR.md` for the full contract.

## Verification and next implementation boundary

Observed local results: 191 network-register tests, 173 registry tests, and 87 portal
tests pass. The populated migration rehearsal preserves host and legacy assignment
records and leaves signed evidence empty. Provider and DNS calls in these tests
use fixtures; no live provider mutation or deployment was performed. UI code is
unchanged; no frontend build was needed for this pass.

The next controller migration needs an explicit durable owner/connection/binding
selection, review/adoption of exact legacy record IDs and snapshots, and an atomic
cutover that disables the old writer before enabling the new one. It also needs
operation-status/recovery UI and versioned credential retention for lifecycle
operations. Those actions are not accomplished by this diagnostic or by updating
the package pin. Preserve old state and do not run two writers over the same names.

This pass was merged onto unstable `5dc6e2f08ee0abcfd86e2d3915944f37de283af3`.
The concurrent Users administration, production defaults/assets, and component
licensing changes are preserved. Production frontend source/output hashes were
rechecked; no frontend source or assets were changed by this pass.
