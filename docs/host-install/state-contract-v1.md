# STATE contract v1 — recovered handoff

Recovered 2026-10-01 from the user-preserved handoff after container rollback.
The historical delivery/outage statements below describe the original response.
The /state direction was accepted by the user; numeric assignments remain reserved
pending collision checks. Implementation details and current API are recorded in
state-interface.md as the next pass lands.

I propose **`/state` as the canonical persistent mount**, with a fixed account profile, explicitly authorized identity initialization, and recovery that requires reconciliation with the station.

This is a **proposed interface**, not implemented startup behavior. The draft and 19 synthetic scenarios were written, and six fixture-consistency checks passed. The workspace then disconnected; **I could not complete file delivery or commit this proposal**. No deployment or disk changes occurred.

**1. Paths, accounts, and permissions**

Reserve the following assignments for a proposed `zog-host-accounts-v1` profile:

| Account/group       | UID | GID | Purpose                                  |
| ------------------- | --- | --- | ---------------------------------------- |
| `host-discover`     | 970 | 970 | Beaconer, host-key ownership and signing |
| `box-control`       | 971 | 971 | Local controller orchestration           |
| `archive-consumers` | —   | 972 | Read explicitly shared archive grants    |
| `host-control`      | —   | 973 | Access the restricted controller gateway |

These are fixed assignments across compatible host generations. Installation must reject collisions rather than allocate different numbers silently. Both users have locked passwords, a non-login shell, no sudo and no capabilities.

| Path                                                             | Owner:group                     | Mode                   |
| ---------------------------------------------------------------- | ------------------------------- | ---------------------- |
| Mounted `/state`                                                 | root:root                       | `0755`                 |
| `/state/.zog-state.json`                                         | root:root                       | `0444`                 |
| `/state/host-install/installations/`                             | root:root                       | `0755`; records `0444` |
| `/state/host-install/operations/`                                | root:root                       | `0700`; records `0600` |
| `/state/host-discover/`                                          | host-discover:host-discover     | `0700`                 |
| Its `identity/`, `trust/`, `control/`, `registries/` directories | host-discover:host-discover     | `0700`; files `0600`   |
| `/state/box-control/`                                            | box-control:box-control         | `0700`                 |
| `/run/host-discover/private/`                                    | host-discover:host-discover     | `0700`                 |
| `/run/host-discover/archive/`                                    | host-discover:archive-consumers | `0750`; grants `0640`  |
| `/run/box-control/host-discover.sock`                            | box-control:host-control        | `0660`                 |

The unmounted `/state` directory in HOST-A/HOST-B should be empty, root-owned, mode `0000`, on the read-only host root.

**Host-discover signs directly using host-identify’s library.** Its account owns `identity/identity.pem`; no separate signing daemon is proposed for v1. This preserves the current model, while acknowledging that compromising the beaconer account compromises its signing authority.

Archive consumers receive no access to identity directories or controller sockets.

Image-build supplies fixed account definitions. Host-install validates them and provisions writable ownership **after verifying STATE**. Locked shadow-account composition needs coordination with image-build because its current exporter deliberately rejects shadow databases.

**2. Mount verification and startup**

The installer binds STATE using all of:

- Partition **PARTUUID**.
- Filesystem **UUID** and type.
- A random `state_volume_id`.
- The logical `installation_id`.
- A root-owned volume marker whose digest appears in bootstrap configuration.

Labels and `/dev/nvme…` names are not identity.

Before loading any private state, privileged startup preparation and host-discover—in its own mount namespace—must establish:

1. `/state` is an actual mount boundary, backed by the uniquely resolved expected partition.
2. Its filesystem UUID, type, mount root, device association and volume marker match.
3. It is writable at both mount and filesystem levels.
4. Component paths have correct owners/modes, no symlink ancestors, and no unexpected nested mounts.
5. The account mapping, initialization receipts and state schemas are compatible.
6. A bounded write/fsync/rename/directory-fsync probe succeeds as the service account.

Retain directory descriptors and use anchored file operations. A successful startup check does not excuse ignoring later write or fsync failures.

Startup should require the STATE mount and a successful host-install preparation service. Use mount ordering plus `BindsTo`/`After` relationships to stop dependent services when the mount disappears; these dependencies supplement the filesystem checks rather than replace them. [GitHub](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml?utm_source=chatgpt.com)

Do not unconditionally create persistent identity directories through `StateDirectory=` or tmpfiles rules.

On missing/wrong STATE, read-only transition, failed fsync, exhausted space or corrupt state:

- Stop accepting and dispatching commands.
- Stop normal signing and credential renewal.
- Close the control session and fail the service.
- Retain uncertain operations for controller reconciliation.
- Never generate a replacement identity or fall back to HOST-A/HOST-B.

**3. Persistent versus transient state**

| State                                                   | Location                                                   | Lifecycle                                                                 |
| ------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------- |
| Private key and identity receipt                        | `/state/host-discover/identity/`                           | Preserve; never regenerate following a failed read                        |
| Approved UUID and registry binding                      | Existing `identity/binding.json` and `primary-origin.json` | Preserve with the matching key                                            |
| Pinned station-control keys and authorizations          | `/state/host-discover/trust/`                              | Persistent; changes require approved transitions                          |
| Command acceptance, replay, dispatch and result journal | `/state/host-discover/control/`                            | Persistent across restart/reboot; no silent reset                         |
| Secondary registry identities                           | `/state/host-discover/registries/`                         | Separate keys; observation-only unless explicitly redesigned              |
| Controller operations and cleanup state                 | `/state/box-control/project/state/`                        | Preserve pending operations and protected generation references           |
| Short-lived archive grants                              | `/run/host-discover/archive/`                              | Exclude from backup; renew after authorization; check expiry on every use |
| Temporary files and new process locks                   | `/run/host-discover/private/`                              | Recreate after verification; no durable progress encoded here             |
| Sockets and mount observations                          | `/run/…`                                                   | Recreate each boot                                                        |

Preserve existing `key.lock` and role-lock behavior during transition: **never unlink a live lock inode**. Those files are coordination mechanisms, not recovery journals.

Backups must capture identity, bindings, trust, replay records, installer receipts and relevant controller state consistently. Quiesce writers or use supported transactional backup procedures. Exclude `/run` and temporary credentials. Treat the backup as private-key material.

**4. Initialization, upgrade, rollback, and recovery**

**Fresh installation:** only an explicit host-install transaction authorizes initialization. It binds an initialization ID to the installation, volume, identity path and account profile. A `mode: "fresh"` configuration field alone is insufficient.

Host-identify generates and durably stages the key, atomically publishes it without replacing an existing identity, and records an initialization receipt. The privileged coordinator then durably records authorization consumption. Network enrollment starts only after these records agree.

An interrupted attempt resumes **the same prepared key and transaction**. A published key with an unfinished receipt is reconciled, not replaced. Corruption, competing candidates or mismatched receipts block initialization.

This requires separating today’s implicitly creating `load_key()` into explicit **initialize-once** and **load-existing-only** paths.

**Restart, upgrade and ordinary reinstall:** require the existing identity and completion receipt. Preserve installation UUID and STATE. Missing identity is an error even if an old bootstrap still says `fresh`.

**Rollback:** each generation declares compatible identity, trust, control-journal and controller-state schemas. Older software must refuse unsupported newer state before writing anything. Never restore old STATE merely to make an old slot start.

**Migration or backup restoration:** require an explicit transaction naming the expected host UUID/fingerprint, backup checkpoint and target volume. Establish a root-owned recovery hold before transport startup. Reconcile trust, replay history and uncertain controller operations before clearing it. Update retained slots’ STATE bindings or make incompatible slots ineligible.

**Important limitation:** a byte-for-byte restored STATE can retain valid UUIDs, markers and receipts. Local checks cannot reliably detect that rollback.

Therefore, every daemon start must obtain a fresh station-authorized control session, bound to the host identity, authority, new session ID and a station-maintained control epoch. No cached session survives restart. Stale checkpoints or trust revisions trigger reconciliation; uncertain old operations must not be automatically redispatched.

Station-access must retain that history independently. Box-control’s 48-hour idempotency window is useful execution protection, but is not an indefinite remote replay ledger. If both host and station histories are restored, or a private key is cloned, external recovery/reapproval is necessary; this proposal does not claim TPM-backed protection.

**5. Example bootstrap and installation records**

The canonical bootstrap is root-owned `0444` at:

`/etc/zog/host-install/bootstrap.json`

A representative excerpt follows. `EXAMPLE_*` values are placeholders, not usable authorization:

```
{
  "schema": 1,
  "kind": "zog-host-bootstrap",
  "profile": "state-contract-v1",
  "installation_id": "11111111-1111-4111-8111-111111111111",
  "configuration_revision": 1,
  "mode": "fresh",
  "state": {
    "mount_point": "/state",
    "filesystem_type": "ext4",
    "partition_partuuid": "33333333-3333-4333-8333-333333333333",
    "filesystem_uuid": "44444444-4444-4444-8444-444444444444",
    "state_volume_id": "22222222-2222-4222-8222-222222222222",
    "marker_sha256": "EXAMPLE_MARKER_DIGEST",
    "identity_directory": "/state/host-discover/identity",
    "trust_directory": "/state/host-discover/trust",
    "control_directory": "/state/host-discover/control"
  },
  "initialization": {
    "authorization_id": "66666666-6666-4666-8666-666666666666",
    "policy": "explicit-install-transaction",
    "expected_host_uuid": null,
    "expected_fingerprint": null
  },
  "registries": [
    {
      "registry_id": "primary",
      "origin": "https://registry.example.invalid",
      "role": "control",
      "ca": null
    }
  ],
  "control_authority": {
    "authority_id": "88888888-8888-4888-8888-888888888888",
    "registry_id": "primary",
    "replacement": "explicit-approved-transition-only",
    "new_session_every_process_start": true,
    "offline_commands": false
  },
  "installation_record": {
    "path": "/etc/zog/host-install/installation.json",
    "sha256": "EXAMPLE_INSTALLATION_RECORD_DIGEST"
  }
}
```

The corresponding installation record contains:

```
{
  "schema": 1,
  "kind": "zog-host-installation",
  "record_id": "55555555-5555-4555-8555-555555555555",
  "installation_id": "11111111-1111-4111-8111-111111111111",
  "operation": "fresh",
  "installer_recorded": {
    "expected_artifact_id": "EXAMPLE_ARTIFACT_ID",
    "expected_host_generation": "EXAMPLE_GENERATION",
    "expected_slot": "HOST-A",
    "account_profile": "zog-host-accounts-v1",
    "foreign_boot_bundle": {
      "kind": "foreign",
      "provider": "amazon-linux-2023",
      "record_reference": "EXAMPLE_PROVENANCE_RECORD",
      "record_sha256": "EXAMPLE_PROVENANCE_DIGEST"
    }
  },
  "security": {
    "secure_boot": "not-assessed",
    "measured_boot": "not-assessed",
    "remote_attestation": "not-implemented"
  }
}
```

Publish configuration as a durable, coherent set before making its slot selectable. Use temporary files, fsync, atomic rename and parent-directory fsync; multi-record transactions need a final commit marker.

Unknown schemas or required features block startup. Upgrades may change generation, artifact, slot and provenance; they must not implicitly change installation identity, STATE binding, numeric accounts or control authority.

A custom CA is a root-owned certificate file with a recorded digest. TLS verification stays enabled. Runtime observations—actual mount, boot ID, running root and health—remain separate from installer expectations.

**6. Responsibility split and integration fixture**

| Component                    | Responsibility                                                                                                                         |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **host-install**             | Volume binding, account provisioning checks, initialization/recovery authorization, installation records and compatible slot selection |
| **host-identify**            | Key generation/storage/signing, fingerprints, initialized-only loading and resumable initialization primitives                         |
| **host-discover**            | Mount preconditions, enrollment, trust, transport, replay/result journal and transient grants                                          |
| **box-control/root-control** | Restricted local gateway, operation policy and existing lifecycle/durability semantics                                                 |
| **station-access**           | Independent control epochs/checkpoints, explicit approval and recovery admission                                                       |
| **image-build**              | Reusable userspace, account-composition inputs and compatibility declarations                                                          |

The proposed gateway is `/run/box-control/host-discover.sock`. It checks peer UID 970 and a narrow operation allowlist, then enters normal box-control semantics. **Host-discover does not receive the general root-control socket, arbitrary shell execution or direct systemd privileges.** This gateway still needs implementation.

The written synthetic fixture includes bootstrap, installation, volume and account records plus 19 observation scenarios. The essential expected outcomes are:

| Scenario                                                              | Expected outcome                  |
| --------------------------------------------------------------------- | --------------------------------- |
| Correct STATE and completed identity                                  | Load existing identity            |
| Ordinary directory, wrong/ambiguous volume, read-only or failed fsync | Block                             |
| Missing key despite old `fresh` configuration                         | Block; do not regenerate          |
| Authorized interrupted initialization                                 | Resume the same prepared identity |
| Unsupported newer state schema                                        | Block without migration           |
| Declared backup restore                                               | Recovery hold                     |
| Stale station trust or replay checkpoint                              | Reconciliation required           |
| Previous-process session or unavailable station                       | No remote control                 |
| Observation registry attempts control                                 | Reject                            |

Remaining coordination is primarily implementation-facing: host-identify’s explicit APIs, the station session/recovery protocol, box-control’s restricted gateway, and image-build’s account/initramfs composition. The fixture checks establish record consistency only; real mount-loss, storage-failure and restored-state acceptance tests remain necessary.