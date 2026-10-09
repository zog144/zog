# Name reservation lifecycle — 0.11.0

`NameReservations(engine).check(actor, owner_id, binding_id, resource_id, name,
action, connection_revision=..., binding_revision=...)` previews `reserve` or
`release`. `change` additionally requires an idempotent `request_id` and commits
the allocation, reservation and audit receipt atomically. Both perform provider
reads only. Ordinary DNS publication still uses the existing plan/prepare/apply
workflow and its fresh publication evidence gate.

Reserve accepts only an unallocated resource and an absent, unreserved direct
child name. Release requires an absent managed-record tombstone, exact ownership,
fresh provider absence and no unresolved operation on the binding. Unpublish
alone deliberately retains the reservation. History and receipts survive release.
A reserve creates an absence tombstone, so a never-published reservation can also
be explicitly released after another absence check.

Use the returned `revision_floor` as the minimum desired revision for the new
allocation. Released allocations reject new prepares; reuse advances that floor
above historical operations and allocations. Replaying a completed receipt is
read-only, including after reuse. Never erase allocation tombstones or receipts.
Authorization and pinned connection/binding revisions are rechecked after reads.
External StateStore implementations must now implement transactional `delete`.

These primitives do not authorize adding a host to an application's selection.
The integration must validate enrollment and fresh signed/AWS evidence, durably
coordinate membership with its assignment database, and serialize its worker.
No provider-side lock exists against concurrent manual DNS edits: the normal
engine preflight remains required before any subsequent DNS write.
