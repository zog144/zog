# Reviewed DNS destinations and diagnostics

Administration → Registries can install an additional DNS destination using a saved
Cloudflare or Porkbun account. The shared central DNS controller must already be
configured and active. This flow does not bootstrap the station/controller, purchase
a domain, change delegation, initialize a missing SOA, import existing records or
rotate credentials on an existing binding.

1. Select a saved account and load its domain pages.
2. Choose a domain and one host-name prefix label, such as `hosts`.
3. Review. The station checks current credentials, provider account/zone access,
   parent delegation, authoritative SOA and prefix shadowing, and complete provider
   record inventory. Existing records within the prefix or overlapping destinations
   block setup and require separate reviewed ownership import or another prefix.
4. Confirm the exact review within ten minutes. The station repeats the checks,
   verifies unchanged credentials and nameservers, initializes a private ledger and
   saves the empty destination. Assign individual hosts on the Hosts page.

No provider writes occur in this flow. Successful reads do not prove write access.
Cloudflare DNS-edit or Porkbun domain DNS permissions are exercised only by an actual
requested record operation. The controller continues to verify each enrolled host's
signed address against AWS inventory before publication.

Reviews are bound to their administrator, credential revision, domain, namespace and
nameservers. Changed inputs require another review. Retrying the same confirmed
review returns its installed destination. A crash after ledger initialization but
before DB publication can resume the same unexpired review. Missing or mismatched
active ledgers are never recreated. An expired uncommitted review is rejected;
operator inspection may be needed for an orphan ledger after an interrupted setup.

The diagnostic buttons inspect the primary and additional destinations without
writing DNS, recovering operations or changing host intent. Reports distinguish
credential revision/authentication, provider domain access and outages, authority,
record inventory/ownership, stale host evidence, and retained pending operations.
An uncertain/conflicting operation requires explicit recovery; pressing Check does
not resend a write. A successful check is an observation, not a persistent grant or
an assurance about a subsequent provider request.

## Administrator API

`POST /api/hosts/dns-setup/`, authenticated administrator session and CSRF required:

| action | Fields |
|---|---|
| `zones` | `credential_id`, `revision`, optional provider `cursor` |
| `review` | `credential_id`, `revision`, `zone_id`, `label` |
| `commit` | `review_id` |
| `inspect` | `binding_id` (`primary` or a saved additional destination ID) |

Domain listing returns `zones` and an optional next `cursor`. Review returns its
ID, expiry, provider, domain, prefix and nameservers. Commit returns `binding_id`,
`provider_writes: 0` and `replayed`. Inspection returns readiness, authority/provider
read observations, per-host codes and pending-operation summaries. Blocked setup
returns a safe stage/code/message without provider response bodies or credentials.
User-supplied ledger paths, nameserver URLs, connection objects or host evidence are
not accepted. Backup and restore work is explicitly deferred until post-release.
