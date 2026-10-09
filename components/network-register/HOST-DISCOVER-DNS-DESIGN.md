# Proposed host-discover integration (not implemented)

Host-discover owns host identity, enrollment, observations, display labels and desired DNS assignments. A central background reconciler calls network-register for provider operations. Beacon handling saves observations and marks desired DNS dirty; it never waits for a DNS API request. Reconcile after changes and periodically to repair missed work.

## Names and ownership

Use an immutable enrolled host identity, with AWS account, region and instance ID as verified attributes. Allocate a stable DNS label when opting a host into publication, initially suggested from the human label. Keep editable display labels separate. Validate a single lowercase DNS label, reject reserved names and enforce uniqueness within the domain. Do not silently rename DNS when a display label changes. Example: compiler-01.hosts.example.org. The hosts prefix is a naming convention, not a separately created zone.

Persist host identity, zone ID, FQDN, provider record ID, desired address, applied address, desired revision and reconciliation status. Reserve names transactionally. A stale worker must not overwrite a newer revision. Treat provider record IDs and local ownership mappings as authoritative; a comment is only supporting evidence. Preserve unrelated records and report collisions. Current network-register's name-only ownership marker needs strengthening before multi-host automation.

## Trusted addresses and credentials

Only authenticated enrolled hosts can update their own observations. Do not trust arbitrary labels or addresses supplied by a beacon. For EC2, cross-check the enrolled identity against successful AWS inventory and use its public address. Distinguish scan failure from confirmed stop/termination. Keep DNS credentials at the central service, scoped to the managed zone; hosts receive no provider token. Separate purchase credentials from routine DNS credentials.

## Records and lifecycle

Start with DNS-only A records targeting verified public IPv4 addresses, TTL 60 seconds; add AAAA when IPv6 is supported. AWS public DNS names can be CNAME targets, but the association still needs refresh after host lifecycle changes, so this does not remove reconciliation. Address changes trigger updates. Unchanged beacons produce no provider writes. Back off transient API failures and expose pending, synchronized, conflict and error states.

Confirmed stop or termination removes the owned address record; retain its name reservation so it is not immediately assigned to someone else. Missed beacons alone mark a host stale, not terminated. Define a separate expiration policy if publishing solely from beacon leases. DNS TTL is cache lifetime, not a lease or record expiration mechanism. Public DNS must not retain a released EC2 IP indefinitely.

## Initial integration scope

One configured domain; explicit publication opt-in per enrolled host; stable unique DNS label; A records; one reconciler; verified inventory addresses; owned-record removal for confirmed stop/termination; visible status and retry. Public service access and TLS are separate capabilities. This document is a proposal, not a review of the current host-discover source.
