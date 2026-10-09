# Upstream package licensing

All 39 current catalogue projects have a literal `license.py`. These records bind
upstream name/version, release URL and archive SHA256 to paths and full-file hashes
of evidence inspected in that archive. They record primary terms, scoped component
exceptions and unresolved patch licensing separately from Zog's own licensing.

The initial records are **declared**, not completed public-release reviews. A
primary SPDX expression is not a blanket license for bundled files. LicenseRef
identifiers refer to retained upstream terms where a precise SPDX mapping has not
been established. Remaining component review is explicit for every project.
Six previously unpinned catalogue sources were downloaded for this review; their
license records bind the observed archive hashes without silently authorizing a
new build recipe or changing its upstream source-pin review status.

## Authoring and execution

Use the existing `license.py` files as the schema. Required fields are schema,
package, version, source (url/sha256), status, expression, scope, evidence,
components, patches and notes. Evidence records contain path, sha256 and
source_sha256. Components and patches contain scope, expression, status and notes.
Review states are declared, reviewed and unresolved. Expressions support AND, OR,
WITH and parentheses, a deliberately explicit SPDX identifier subset, and local
LicenseRef identifiers. Extend the supported subset when reviewing a new license.
Do not mark unresolved terms as reviewed merely to pass validation.

Catalogue validation requires a license record. Stage materialization snapshots
one canonical project record into each stage, unless an explicit stage override
exists. Its source digest must match a declared recipe input. Record changes alter
package fingerprints and cache input identities. Historical standalone recipes
without license metadata retain their old fingerprints for compatibility.

Before successful package cleanup, image-build verifies each required notice in
both the extracted source and the original checksum-verified archive. It retains
full notice bytes and a receipt under:

    /usr/share/licenses/zog-packages/<stage-name>/

For exclusively sysroot/ or tools/ outputs, the same directory is placed under
that prefix. Receipts contain the record identity, source inputs, reconstructable
recipe data and file ownership hashes. They enter normal output inventories,
composition collision checks and generation provenance. Source archives and raw
patch inputs are copied and synced separately to:

    <state>/image-build/release-inputs/<sha256>

This store has no automatic expiry. Normal extracted-source cleanup can continue;
source-cache/mirror expiry must not remove retained release inputs. The release
store is local retention infrastructure, not a public corresponding-source offer.

## Offline release readiness

    python -m zog.zog.image_build.licensing GENERATION_DIRECTORY --state STATE_DIRECTORY

The JSON report contains eligibility, package records, issues and unresolved file
paths. Exit status is 1 when review/evidence/source retention or file coverage is
incomplete. A reviewed synthetic package passes the tests; the current catalogue
intentionally does not claim public readiness. Existing generations remain
readable and unreviewed. Inherited/seed files without matching ownership receipts
are listed explicitly rather than being relabelled source-built or reviewed.
Additional source/patch inputs currently require further review and block release.
Prefix-relocated staged receipts and composition-modified shared files can also
remain uncovered; the check fails conservatively until ownership transformations
are explicitly recorded. It does not infer a complete dependency licence audit
from an executable's primary SPDX declaration.

This implementation does not restart or rewrite ongoing build snapshots. New
materialized runs acquire the metadata after deploying this version. Station-access
and packaging still need separate coverage for pip/npm dependencies outside the
image-build package catalogue.

## License notice access across execution identities

For new source preparations, image-build verifies each declared license notice
against its frozen evidence digest and adds read bits (`mode | 0444`) to that
notice alone before controller registration. Existing write/execute bits, bytes,
and timestamps remain unchanged. Unrelated source files and installed output
modes are untouched. Symlink paths and shared hard links are rejected.
`license-readability.json` records the policy and changed paths/modes/hashes in
the package attempt. The original archive and its digest remain authoritative.

This is needed because box-control returns workspace directory ownership after
execution while regular files keep the build identity. Archive notices with
modes such as 0640 would otherwise become unreadable to the orchestrator.
Finalization still verifies extracted working content and original archive
notices; it never silently skips a notice or falls back to unverified content.
If a build subsequently removes access, finalization fails closed.

The policy applies only before preparing a new attempt. Resuming an existing
attempt does not silently normalize its frozen working tree. Administrative
recovery must independently establish completed cleanup, safe file ownership,
and unchanged evidence, and retain an explicit receipt.
