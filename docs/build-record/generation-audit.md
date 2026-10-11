# Independent generation audit

`audit_generation(bundle, expected, *, paths=None)` and CLI `audit-generation`
reuse canonical graph validation and artifact verification. No schema-1 record,
identity, recovery rule or existing inspection response changes. There is no
controller/network dependency, owner-state mutation or automatic source retrieval.

Obtain this expectation object independently from a trusted owner publication:

```json
{
  "schema_version": 1,
  "record": "sha256:<64 lowercase hex characters>",
  "generation_id": "the exact opaque canonical generation subject identity",
  "packages": ["installed-package-a", "installed-package-b"]
}
```

`record` is the canonical generation record ID. `generation_id` is its opaque owner
subject identity, not necessarily the owner's short generation fingerprint.
For image-build the subject is the compact JSON string `[host,project,generation]`;
take scope from the verified publication rather than guessing it. Package names
are the exact **installed** set, not every build dependency or history record in
the graph. Order is ignored; duplicates are invalid. An absent owner inventory
is unknown and cannot be supplied as an empty set. Empty is valid only when the
owner explicitly declares an empty generation. Never derive expectations from the
same untrusted export simply to make it match; that tests internal consistency only.

```sh
python -m zog.build_record audit-generation generation.json --expected expected.json
python -m zog.build_record audit-generation generation.json --expected expected.json \
  --artifacts artifact-paths.json
```

The report keeps target matching, reference closure, declared gaps, byte status
and authenticity separate. `matches_expected_generation` confirms the supplied
record, subject and package set; it does not erase incomplete historical inputs.
`inspection.complete` retains the canonical meaning: no missing reachable records
and no declared gaps. A package with an explicit legacy binding is listed as
legacy. Missing output records leave package membership unavailable, not empty;
`packages.missing` is null when the complete installed set cannot be determined.
Transitive source/material/history records remain covered by graph inspection.

`passed` requires matching expectations, complete metadata, and (when `paths` is
supplied) every referenced artifact verified. Exit 0 indicates this requested
scope passed, 3 indicates a mismatch/gap/incomplete requested check, and 2 indicates
invalid records/expectations, wrong root kind/count or a file operation failure.
A valid generation with declared historical gaps therefore returns 3; this does
not relabel a successful compilation as failed. Inspection results explain why.

Without `--artifacts`, the scope is **metadata**, and artifact bytes remain
`not-checked`. With a mapping, omitted paths are `not-provided`; missing files are
`unavailable`, and changed hash/size is `mismatch`. Record artifact names/URLs are
never opened. Verification hashes the supplied files, not recursively the files
named inside a content manifest. Signature/authenticity checks and live job/log
availability remain unchecked in both modes. An owner receipt is not a signature.

## Producer handoff

Provide the immutable final generation pointer, scoped generation identity, exact
installed package inventory, canonical closure export, and an authorized digest
to retained-local-path mapping for on-host byte verification. The JSON export is
metadata only; do not embed archives or journals in it. Preserve explicit inherited
legacy gaps. If a later composition adds a base root, removes files, updates trust
configuration or merges a package generation, its final assembly must itself be
recorded. A package-only export cannot attest the resulting combined rootfs.

Historical output without a producing binding remains legacy. A missing canonical
generation root cannot be repaired by labeling it with current recipes or pins.
Audit the next prospectively captured generation without rewriting previous ones.
