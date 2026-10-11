# Generation provenance

Station-access 0.4.26 adds an administrator-only Generation Detail view for immutable
root-filesystem artifacts already observed through Administration → Archives.

## Evidence boundary

The page does not discover provenance and does not make new build claims. A request is
valid only when it is bound to all four values from an existing complete archive
observation:

- mirror host UUID;
- immutable observation snapshot UUID;
- root-filesystem collection;
- rootfs SHA-256 digest.

The generation in the URL must equal the generation identity recorded for that exact
rootfs archive item. A source archive cannot be opened as a generation. Superseded
snapshots return the existing refresh-required behavior.

Package/source/license information comes only from the artifact-bound notice bundle
whose digest was reported in that same archive observation. Before display,
station-access validates the stored bundle with archive-mirror's notice contract and
checks its root-filesystem identity, digest and generation again.

## Coverage semantics

Generation Detail exposes separate source-provenance and license-evidence coverage.

A package evidence record has complete source provenance only when both a source
SHA-256 and reviewed public upstream origin are present in the validated evidence.

License evidence is complete only when the record has a license expression, its review
state is `declared` or `reviewed`, it has no unresolved issues, and every recorded
exception/component also has an expression with a `declared` or `reviewed` state.

The headline counts are computed from the validated records on every request; there is
no separately mutable completeness flag. Any incomplete source or license record counts
toward unresolved provenance.

If notice evidence is unavailable, broken, or reported but its immutable bundle has not
been received, package totals and unresolved counts are **Unknown**. Station-access does
not turn missing evidence into `0 / 0 complete`, zero unresolved items, or a successful
coverage claim.

## Deliberately unavailable evidence

Patch provenance is not present in the current artifact-bound notice contract. The page
therefore displays **Patch evidence unavailable** and does not report zero patches or
infer patch state from package names, stages, digests or notice text. Station-access
0.4.27 makes this state explicit on every package card; a future positive patch count
will render a prominent **Patched** indicator.

Build-record and build-trace are likewise shown as not integrated. They should populate
this same page once their stable consumer contracts are connected rather than creating
a second definition of generation provenance.

## Routes

The browser route is:

`/generations/<generation>?mirror=<uuid>&snapshot=<uuid>&collection=<name>&digest=<sha256>`

The administrator API is:

`GET /api/archives/generations/<generation>/`

with the same four required query parameters. It is read-only, administrator-only and
returns `Cache-Control: no-store` through the archive response helper.

Administration → Archives exposes **Generation provenance** only for root-filesystem
items that already carry a generation identity.

## Validation

The source pass includes backend regression coverage for complete, incomplete, missing
and unauthorized/wrong-generation cases, plus frontend tests for complete and unknown
coverage rendering. The repository's normal execution-capable validation remains:

```sh
python tools/test-backend.py
cd frontend
npm ci
npm test
npm run build
```

Those commands require the repository's pinned external dependencies and Node install.
This regular-chat source pass does not claim they were executed or deployed.


See [Provenance encounters](PROVENANCE-ENCOUNTERS.md) for the reusable Source & license, patch-state, and application encounter rules introduced in 0.4.27.


## JSON export

Station-access 0.4.29 adds **Export provenance (.json)** to Generation Detail. The
schema-1 export is bound to the same mirror/snapshot/collection/digest query and is
built from the same validated provenance payload as the browser page. It preserves
unknown evidence and current patch/build not-integrated states, and orders package
and nested evidence deterministically. See
[Host generation provenance and JSON export](HOST-GENERATION-AND-EXPORT.md).
