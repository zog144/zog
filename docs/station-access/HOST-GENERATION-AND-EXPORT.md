# Host generation provenance and JSON export

Station-access 0.4.29 connects verified host installation identity to the provenance
surfaces introduced in 0.4.26–0.4.28 and adds the first versioned machine-readable
generation-provenance export.

## Producer chain

The managed host path is:

`host-install 0.4.4 → host-discover 0.4.6 → signed station-access heartbeat`

Host-install owns the host installation/slot evidence. Host-discover does not infer
slot state; during managed live collection it attaches host-install's verified
`host_generation` report to the signed heartbeat.

The beacon contains immutable identities, not package manifests:

- installation UUID;
- installation record UUID/schema/operation;
- selected HOST slot;
- actually booted HOST slot when the live root PARTUUID proves one;
- HOST-A and HOST-B generation/root-PARTUUID identities when known;
- transitional foreign boot-bundle identity when recorded.

Legacy host-install records remain meaningful: the selected slot is known and the
inactive slot remains unknown. Station-access never reconstructs an inactive slot
from history.

`selected_slot` and `booted_slot` are deliberately separate. A host still booted
through the transitional Amazon Linux root reports `booted_slot: null`; selecting
HOST-A does not make HOST-A a boot fact.

## Signed ingestion

Station-access validates the `host_generation` object as a closed schema before
persisting it. It is accepted only on signed Ed25519 enrollment/heartbeat paths.
The legacy bearer-token heartbeat rejects this extension.

The signed report remains the retained host observation. Host-generation evidence
is therefore associated with the same approved host identity and heartbeat
signature as hostname/cloud observations; it is not a separate unsigned channel.

Malformed evidence is rejected before replacing the previous host report.

## Host display

Administration → Hosts → Host details shows a Host generation section with:

- installation identity and record version;
- selected and actually booted slot;
- HOST-A/HOST-B generation and root PARTUUID;
- archive resolution and rootfs SHA-256;
- transitional boot-bundle provider/reference/digest;
- Generation provenance deep links for uniquely resolved generations.

Generation resolution reuses the exact same resolver as Workspace Provenance:

- no matching observed rootfs → unresolved;
- exactly one distinct rootfs digest → resolved;
- multiple distinct digests for the same generation → conflict, with no arbitrary
  provenance link;
- missing generation identity → unknown.

Archive observation changes do not participate in the host-removal confirmation
revision. Refreshing provenance evidence therefore cannot invalidate an unrelated
archival review; actual host/dependency changes still do.

## Versioned generation provenance export

Generation Detail now exposes **Export provenance (.json)**. The endpoint is:

`GET /api/archives/generations/<generation>/export/?mirror=<uuid>&snapshot=<uuid>&collection=<name>&digest=<sha256>`

It has the same administrator permission and exact immutable archive binding as
Generation Detail.

The export is schema 1 with:

```json
{
  "schema": 1,
  "kind": "zog-generation-provenance",
  "generation": {
    "identity": "...",
    "rootfs_sha256": "..."
  },
  "archive": {},
  "evidence": {},
  "packages": [],
  "patches": {},
  "build_evidence": {}
}
```

The browser view and JSON export call the same canonical provenance payload builder.
The export does not independently recompute completeness, licensing, or missing
evidence.

Output is deterministic: object keys, package order, issues, component/exception
records and future patch items are ordered before compact JSON serialization. A
trailing newline is included. The response is `no-store`, `nosniff`, and carries
an attachment filename ending in `.provenance.v1.json`.

Unknown/missing evidence is preserved. In particular, the export never converts
missing source/license coverage into zero, and current patch/build evidence remains
`not-integrated`.

## Deferred work

This pass does not add:

- package manifests to host heartbeats;
- a deployment → request → slot → boot chain;
- signed provenance bundles;
- SPDX or CycloneDX exports;
- compliance PDFs;
- Secure Boot/TPM attestation presentation;
- slot switching or installation mutation;
- live deployment.

## Validation boundary

Source regression coverage includes:

- signed-only host-generation ingestion;
- malformed-evidence rejection without overwriting the prior report;
- legacy bearer rejection;
- Host Detail resolution and conflict handling;
- selected versus actually booted slot rendering;
- transitional boot display;
- archival revision independence from archive resolution;
- exact Generation Detail links;
- export schema, headers and immutable binding;
- deterministic package/component ordering;
- unknown-evidence preservation;
- export administrator authorization.

The normal execution-capable station validation remains:

```sh
python tools/test-backend.py
cd frontend
npm ci
npm test
npm run build
```

The producer repositories also require their normal Python suites. This regular-chat
source pass does not claim those commands were run and does not deploy any host.
