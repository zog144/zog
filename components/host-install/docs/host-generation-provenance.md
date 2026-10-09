# Host generation provenance

Host-install 0.4.4 extends the existing STATE installation record with optional
A/B slot provenance and exposes a read-only verified host-generation report for
host-discover.

## Backward compatibility

Existing state-contract-v1 records remain valid. A legacy record without
`installer_recorded.host_slots` is normalized conservatively:

- the record's `expected_slot` is known with its recorded generation and root PARTUUID;
- the other HOST slot is unknown.

No inactive-slot generation is reconstructed from filenames, retained history, or
the current root filesystem.

New installation records may add:

```json
"host_slots": {
  "HOST-A": {"generation": "...", "root_partuuid": "..."},
  "HOST-B": {"generation": "...", "root_partuuid": "..."}
}
```

Either slot may be null when genuinely unknown. The selected slot must exactly
match `expected_host_generation` and `root_partuuid`, and the two slots may not
reuse one PARTUUID.

## Upgrade preservation

During an upgrade or reinstall, the non-selected slot's recorded provenance must
remain byte-for-byte equivalent. Switching from HOST-A to HOST-B or vice versa
requires the new record to carry `host_slots`, preserving the previous slot while
recording the newly selected slot. Once a record has a complete slot map, later
transitions may not drop that map.

This makes the current installation record a sufficient source for both slot
identities without guessing ordering from retained historical records.

## Verified runtime report

`zog.host_install.state_inspect.host_generation_report(context)` accepts an already
verified live STATE context and returns schema 1:

- installation UUID;
- installation record UUID and schema;
- installation operation;
- selected HOST slot;
- actually booted HOST slot, or null;
- HOST-A and HOST-B generation/root-PARTUUID records;
- transitional foreign boot-bundle identity, when recorded.

The booted slot is not copied from `expected_slot`. It is proved by comparing the
live `/` mount's block-device PARTUUID to the recorded slot PARTUUIDs. If the
system is still booted through a foreign/transitional root, or the root device
cannot be matched to a recorded HOST slot, `booted_slot` is null.

The report rechecks the retained STATE context before and after collecting live
root-device evidence. It is observational and performs no slot selection, boot
change, or STATE mutation.

## Validation boundary

Tests cover legacy normalization, complete A/B records, selected-slot binding,
duplicate PARTUUID rejection, transition preservation, A/B switching, live root
matching, and transitional-root non-mislabeling.

This source pass does not claim execution-capable test results or boot acceptance.
