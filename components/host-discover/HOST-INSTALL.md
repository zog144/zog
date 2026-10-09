> Historical pass-2 handoff. Current maintained interface: [Managed STATE](docs/MANAGED-STATE.md).

# host-install integration — pass 2

host-discover 0.3.6 consumes host-install 0.2.0 at unstable commit
`79567cf93a0c012c64936834f6bd90c67a5f68e6` and host-identify 0.3.2.
Use the exact repository revisions in version-share-handoff.json when building.
Dependency direction is host-discover → host-install and host-identify; neither
producer depends on host-discover. No producer implementation is vendored here.

## Implemented boundary

`host-discover --managed-state` is an explicit live startup diagnostic. Run as
host-discover UID/GID 970 in the eventual service's own mount namespace. It reads
canonical configuration through `state_inspect.inspect_live()`, retains its STATE
fd, calls the public `state_probe.probe_live()` and rechecks the retained mount.
The probe writes only temporary health files. No saved inspection output is
accepted. Unknown records fail before the probe; no private identity is read
before successful inspection and probe.

The production coordinator adapter currently reports `recovery-hold-unavailable`.
It does not assume an absent protected hold means false. Subsequent boundaries
require actual component schema declarations and an independently verified,
privileged consumption receipt. There is no invented root-owned receipt path or
JSON option that can bypass these requirements. Exit 2 means managed admission
is unavailable; it must not be wrapped in a fallback to the legacy daemon.

`ManagedState.decision()` accepts trusted **in-process** coordinator adapters for
integration tests and future integration, not externally supplied evidence. The
adapter must authenticate the receipt against the protected installer transaction
and current installation/volume/authorization ID. The diagnostic verifies its
agreement with host-identify's actual key and publication receipt through retained
directory descriptors. The identity private key never appears in reports.
An expected registry UUID additionally blocks pending a protected binding reader;
a matching fingerprint alone cannot prove UUID agreement.

The authoritative `state_gate.decide()` supplies lifecycle policy. Station status
is explicitly unavailable: heartbeat success, cached sessions and observer
registries cannot grant control. Even a completed synthetic coordinator fixture
has `live_admission: false` and `remote_control_enabled: false`.

Any detected mount/read/storage/evidence failure latches the admission object.
It cannot be retried or re-entered after failure or close. Managed CLI returns
before enrollment, signing, credential renewal, or the legacy mirror-role tick.
There is no background healthy-state writer and no claim of persisted fault/reset
handling. A subsequent process must repeat all inspections and authorization.

## Authoritative offline diagnostics

The provisional two-record parser and its partial fixtures have been removed.
`zog.host_install.state_contract` is the only executable record validator. Fixtures
are copied unchanged from the pinned producer, with provenance alongside them.

```
python -m zog.host_discover.bootstrap --bundle BUNDLE.json --evidence EVIDENCE.json
```

Evidence is a synthetic `state_gate` test record. Exit 0 means a nonblocking
**offline policy result**, never permission to initialize, sign or execute.
`policy_control_allowed` is a synthetic policy value; effective control stays false.
Exit 1 means blocked/recovery-only, exit 2 invalid/unreadable input.

Digest domains are deliberately distinct: host-install record canonical JSON has
**no trailing newline**; host-identify initialization authorization encoding has
**one trailing newline**. Its authorization_sha256 must use host-identify.encode,
not host-install.digest. The respective validators check their own domains.

## What remains before a Zog host can enroll

1. host-install must supply a privileged, current-boot initialization transaction,
   durable consumption publication, and protected recovery-hold reading/reset.
   Fresh mode alone is insufficient. Initialize/resume remain disabled here.
2. Each owner must expose actual state-schema compatibility declarations. Do not
   copy installer expectations into runtime evidence as a substitute.
3. Implement descriptor-anchored registry binding, trust, journal and credential
   writes before enabling managed network transport. This pass reads identities;
   it deliberately does not reuse legacy path-based destination/role writers.
4. station-access must establish an authenticated current-process session with
   pinned authority and independent epoch/checkpoint history. Coordinate the
   restricted local box-control gateway. Remote control remains disabled.
5. Integrate service mount ordering/lifetime, protected durable fault/reset policy,
   and real mount-loss, fsync, restart and restoration tests. The process latch is
   only the local precursor; it is not a completed boot/lifecycle supervisor.
6. AWS IID evidence verification, installation/runtime reporting and the first
   authenticated remote operation remain separate integration work. Foreign
   AL2023 boot is not Secure Boot, measured boot or filesystem attestation.

## Validation and deployment handoff

Tests include the producer's 19 complete scenarios, strict records, inspection/
probe ordering, mount-fault latch, absent consumption/hold/schema refusal, retained
STATE to actual temporary key/receipt validation, path replacement, and legacy
regression suites. The temporary-files integration translates ownership; it is
not a real mounted STATE/service-account or boot acceptance test.

host-deploy should keep its tested release pins until a coordinated update. A
future managed image must include all three packages at the recorded revisions.
Do not install an unconditional identity-creating service or configure managed
STATE as a legacy identity directory. Existing HTTPS/custom-CA, redirect rejection,
explicit fingerprint approval and non-managed beacon behavior are unchanged.

No live service, cloud resource, disk, DNS, station database, or production key was
modified. host-install itself was consumed and tested without source changes.
