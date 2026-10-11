# Managed STATE: narrow identity verification

This document describes `--managed-state` and the older fixture runtime.
The additional explicitly provisioned `--managed-beacon` profile has separate
composition and live-acceptance requirements; this document does not validate it.

host-discover 0.4.0 requires host-install 0.4.0 and host-identify 0.3.3 at the
exact revisions in version-share-handoff.json. The production managed entry point
is a diagnostic. Enrollment, signing transport, credential renewal and remote
control remain disabled pending full component capability gating and joint live
acceptance. Existing non-managed beacon behavior remains available separately.

Run `host-discover --managed-state` as UID/GID 970 in the intended service namespace.
It performs live inspection and the service-account storage probe, retaining STATE's
file descriptor. It obtains a fresh observation using
`zog.host_install.state_admission.request_live(context)`, rejects holds/refusals, loads
only the existing consumed identity through host-identify's descriptor API, then
obtains another fresh observation. The receipt and boot/configuration/mount bindings
must agree. No cached JSON, CLI report or `/run/host-install/identity-consumed.json`
projection can substitute for this socket exchange.

On success, JSON reports `status: existing-identity-verified`, public fingerprint,
`identity_action: verify-existing`, and `code: full-admission-pending`. Exit status
is 0 for that narrow result. `transport_enabled`, `control_authorized`,
`live_admission`, and `remote_control_enabled` all remain false. Exit 2 means the
attempt failed; do not fall back to legacy startup. Missing dependencies refuse.

Every failure latches the admission object's lifetime, discards the loaded key,
and forbids retry on that object. Missing/corrupt keys never cause generation.
Expected registry UUIDs still require a protected binding reader and currently
refuse; a matching fingerprint alone does not prove UUID agreement. Installer
schema expectations are not used as runtime component declarations.

Install/review host-install's admission socket/service templates only in a
coordinated disposable-host test. The included `deployment/host-discover-managed.service`
is a oneshot diagnostic, requires the admission socket, binds lifetime to STATE,
and has no restart or identity/journal creation. Review executable paths. Per-path
bind mounts under STATE conflict with the producer's nested-mount checks.

An observation is point-in-time. No durable consumer-fault reporting/reset or
continuous health lease is implemented. This code does not clear protected holds,
initialize identity, modify DNS, upgrade the live command center or manipulate disks.

## Experimental integration modules

`managed_transport.Runtime` and `admission.Journal` exercise the next transport
boundary with explicitly injected local fixtures. The default `Transport` refuses;
there is no managed-run or managed-prepare command. Do not enable transport by
removing this gate alone.

The fixture flow uses explicit empty-journal preparation, a process-exclusive lock,
descriptor-relative writes and fsync barriers, protected identity evidence, pending
enrollment, operator fingerprint approval, TLS-origin-bound station key pinning,
a fresh signed station session and independent epoch/checkpoint history. A lost
session response is reconciled using the durable request, then replaced with a new
process session. An expired unresolved handshake requires reconciliation, not reset.
Restoring only host or station history conflicts; restoring both still needs
external recovery. Keys are not TPM-bound and these tests do not claim attestation.

The journal lives under `control/managed.json` in the fixture layout. Interrupted
writes leave a blocking `managed.pending` marker; startup does not repair it. Its
schema describes this journal only, not box-control or other components. Commands
are limited to signed, session-bound `inspect` requests. A bounded 128-entry replay
journal is persisted before calling the UID-checked gateway. Entries survive process
restart and are retained through command expiry; old-session commands are rejected.
Uncertain requests are not automatically repeated. Results are signed by the host
and bound to the same request and session IDs. No lifecycle mutation is supported.

The gateway client connects only to `/run/box-control/host-discover.sock`, verifies
971:973 mode 0660 and kernel server UID 971. The box-control receiver requires UID
970 and exposes persisted runtime identity/state through its local library. Service
composition and command queue/delivery/results UI remain follow-up work. Observation
registries cannot dispatch commands. Key substitution and expired sessions refuse.

Fixture heartbeats do not persist archive grants, export station-login passwords,
execute mirror roles, or use legacy state writers. These need separate descriptor-
anchored delivery integration before wider transport is enabled. Full AWS IID
verification also remains separate; cloud metadata is only a matching hint.
