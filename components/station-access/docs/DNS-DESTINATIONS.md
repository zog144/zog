# Additional host DNS destinations

Requires network-register 0.12.0 and migration 0013. The existing primary DNS
assignment and endpoints remain compatible. Additional destinations have separate
bindings, ledgers, assignments, revisions and status. A host may publish the same
label under several domains. Changing a display label never renames DNS.

New empty destinations can be installed through the reviewed Registries flow;
see [DNS-SETUP.md](DNS-SETUP.md). Existing owned ledgers use an explicit
administrator CLI import. After initializing a zone and resolving any outstanding
operation with network-register, import its
owned ledger with `manage_dns_destination import --selection FILE --ledger PATH`.
PATH is relative to the configured DNS state directory. The selection uses the
existing reviewed selection schema. Import performs provider reads and verifies
all selected records against fresh host evidence; it does not adopt foreign names
or send provider writes. Destination prefixes must not overlap existing bindings.
State and credentials belong outside the source repository.

The Hosts page lists each additional assignment with provider, name, address and
status. Administrators can reserve a label in an installed destination, enable or
unpublish it, and explicitly release an unpublished name for reuse. The additional
API is `/api/hosts/<host>/dns-destinations/<binding>/`: actions `reserve` (label),
`enable`, `unpublish`, `release`, or `cancel` (current revision). `cancel` only
removes an uncommitted reservation; it cannot discard ledger ownership/history.
Requests are session-authenticated, CSRF-protected and owner-scoped.

The existing DNS timer evaluates all enabled destinations under the same central
controller lock. Each uses the shared evidence gate and operation engine. Provider
warnings, drift and uncertain writes stop that destination. Stale beacons never
cause deletion. Explicit unpublish retains the name reservation until release.
Every additional assignment, including an incomplete reservation, blocks archival.

Reservation/release use durable ledger receipts plus a database phase. A crash
between the two stores leaves the destination fenced; repeat the same action to
resume. An uncommitted reservation can be discarded only if the ledger contains
no corresponding receipt, active allocation, owned record or pending operation.
Missing state is never automatically recreated. Credential changes require explicit
binding revalidation/migration; they are not silently substituted.

The original primary API still controls only its primary assignment. Unpublish
and release each destination before archival. Installing/configuring destinations
remains an administrator CLI task; the GUI manages hosts within those destinations.

## Reviewed setup and diagnostics

Station-access 0.4.22 adds the Registries setup flow for new empty destinations
and explicit read-only inspection of existing destinations. See [DNS-SETUP.md](DNS-SETUP.md).
Existing owned ledgers still use the operator-reviewed import described above.
