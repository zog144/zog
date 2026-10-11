# image-build architecture — checkpoint

## Ownership

image-build resolves reviewed package metadata, obtains verified sources, prepares
build roots and stages, records outputs, and composes immutable generations.
box-control executes build programs using systemd and owns their cgroups,
namespaces, lifecycle, durable runtime identities and cleanup. root-control
provides privileged mechanisms. host-deploy supplies remote AWS test hosts.

RPM tooling is developer assistance only. Host development RPMs may seed the
bootstrap; normal image creation uses reviewed Zog source recipes. Amazon Linux
is the first host target, with separate AL2023/AL2/Fedora preparation profiles.

## Accepted bootstrap

Host-derived seed → first source-built toolchain → fresh root from only those
outputs → second source-built toolchain → ordinary package builds. Each source
stage must compile and execute a C probe. Only stage two is eligible for ordinary
builds. This workflow is implemented as orchestration but not yet executable
through the missing box-control build-job API. Full toolchain recipes are also
not included. Self-hosting and reproducibility are not inferred from mocks.

Stage-specific package recipes must explicitly handle compiler/library cycles
and temporary prefixes. Arbitrary dependency cycles are rejected; no toolchain
file is silently overwritten during dependency-root composition.

## Execution integration

`BoxControlRunner` accepts an explicit integration callable. Its request carries
the prepared root, staged source/output paths, exact argv/environment, working
directory, read-only and network-disabled requirements, and timeout. The typed
result must supply runtime/Invocation/journal identities, exit code and cleanup
completion. Missing adapter/evidence, nonzero exit or incomplete cleanup fails.
This is an image-build-owned port, **not an existing box-control API binding**.

The current box-control generation/mount restrictions are kept. The required
controller extension is specified separately; image-build must not synthesize
legacy manifests, write systemd units, call systemd directly, or invoke another
container manager to get around that missing interface.

## Package and filesystem model

Metadata uses Python literals. Sources specify HTTPS/local URLs and SHA256.
Patches are regular source inputs applied in explicit prepare commands. Archives
accept regular files/directories and reject traversal, links, devices and
repeated entries. Unusual archives need reviewed preprocessing/repacking.

Every package receives a fresh copy of its selected toolchain and runtime
closures of its direct build/runtime dependencies. Source and output directories
are separate. Only selected outputs plus runtime dependencies enter the image;
build-only dependencies are omitted. Exact produced paths must match the
produce-manifest. Directory modes must agree and file ownership conflicts fail.

Inventories record paths, modes, file content hashes and symlink targets. They do
not model UID/GID, ACLs, xattrs or file capabilities yet. Set-ID outputs and special
files are rejected. Composition never traverses a destination symlink to write
another package's output. Recipe authors are trusted code authors.

## State and publication

Construction is serialized using `state/image-build.lock`. Generations live in
`state/image-build/generations`; `active` and `toolchain-active` point to selected
generations. Identity includes schema, recipes/source digests, dependency and
toolchain lineage. Stored outputs are checked before reuse. Filesystem-level
write protection is not installed by this checkpoint.

Publication copies into an unpublished directory, synchronizes files/directories,
renames into the store, then switches and synchronizes the active reference.
Failures before activation preserve the old reference. A failure synchronizing
activation is an uncertain durability outcome, not a promise of rollback.
There is no automatic build crash recovery or project storage-fault latch.

Attempts, failure traces and logs are retained. Image-build deletes no published
generations; box-control owns reclamation. The capacity limit is 10 across seeds,
intermediate toolchains and images. Attempts and source caches need a future
explicit retention policy; they are not automatically pruned.

## Integration migration

The public selection shape and schema differ from the extraction. Old
BuildProgram callers and legacy generation readers need a deliberate adapter.
No box-control implementation was modified. Current application/recovery code
must consume completed selections without implicitly rebuilding an image.

## References and deferred work

AWS package managers: https://docs.aws.amazon.com/linux/al2023/ug/package-management.html
DNF evidence commands: https://dnf.readthedocs.io/en/latest/command_ref.html

The optional DNF4 collector records a solved binary transaction, source-package
mapping, source requirements and inert spec/patch files. It does not resolve a
recursive source bootstrap or automatically translate spec macros/hooks.
DNF5 support, arbitrary conversion, full bootstrap recipes, real controller
acceptance, reproducibility comparison and security-network publication remain
unimplemented or unverified as detailed in IMPLEMENTATION-REPORT.md.
