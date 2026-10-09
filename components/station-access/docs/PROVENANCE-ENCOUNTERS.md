# Provenance encounters

Station-access 0.4.27 makes provenance an ordinary part of software encounters while
keeping every link and status bound to evidence that already exists.

## Source & license

Administration → Archives now labels the artifact-bound notice control **Source &
license**. It still uses the exact mirror/snapshot/collection/digest binding and the
same authenticated immutable notice bundle; the wording change does not broaden what
the evidence means.

Generation Detail uses reusable provenance components for every package. Each package
shows:

- source-provenance completeness;
- license-evidence completeness;
- patch-evidence state;
- an expandable **Source & license** section with source SHA-256, validated public
  upstream origin when recorded, license expression/review, component exceptions,
  unresolved issues, and the generation notice download.

The upstream link is rendered only from the notice contract's validated HTTPS public
origin. The notice download remains station-access's same-origin authenticated endpoint.

## Patch visibility

Patch state is always rendered beside package source/license state.

The UI contract distinguishes three states:

- `available` with count greater than zero → a prominent **Patched · N** indicator;
- `available` with zero → **No patches recorded**;
- `unknown` or `not-integrated` → **Patch evidence unavailable**.

The current generation API returns `not-integrated` for every package and for the
generation aggregate. That is intentional. The artifact-bound notice evidence does not
contain patch records, so station-access must not infer an unpatched package.

Build-record already has immutable patch artifacts in canonical `build-inputs`
records, but station-access does not yet have the trusted generation-snapshot/store
integration needed to join those records to this page. Its patch artifact contract also
does not by itself supply every desired human field such as origin or rationale. Those
facts will remain unavailable until a producer records them.

## Application encounters

Both the Administration application cards and the workspace application search now
show the source/license state.

The current box-control application specification has no authoritative application
source/license identity. Station-access therefore serializes:

```json
{
  "source_license": {
    "state": "unavailable",
    "reason": "application-source-identity-not-published"
  }
}
```

and renders **Source & license unavailable** rather than linking an application to a
runtime rootfs and implying that the rootfs license is the application's license.

Once the controller publishes an explicit application provenance identity, the same UI
surface can become a real Source & license action without changing the encounter design.

## Validation boundary

Regression tests cover:

- application provenance serialization;
- unavailable application provenance rendering without a fake link;
- patch evidence unavailable versus positive **Patched** versus confirmed zero;
- package Source & license rendering on Generation Detail;
- the renamed Archive Source & license action;
- existing generation completeness semantics.

The normal execution-capable validation remains:

```sh
python tools/test-backend.py
cd frontend
npm ci
npm test
npm run build
```

This source pass does not claim those commands were executed or that 0.4.27 was
deployed to a running station.
