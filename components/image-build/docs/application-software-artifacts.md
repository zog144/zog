# Immutable application software and views

Image-build owns immutable application software as a lifecycle separate from both
base rootfs generations and persistent application data. The producer contract for
individual software artifacts remains `applications-v1`.

A published artifact is identified as `sha256:<digest>` over its frozen manifest.
The manifest includes:

- application and reviewed revision identity;
- canonical source URL/SHA-256 identities;
- architecture and conservative runtime compatibility requirements;
- retained license/notice paths;
- producer provenance, including build-record/build-trace references when available;
- the complete installed-file inventory including file hashes and modes.

Mutable databases, secrets, credentials and other application data do not belong in
this store. Provenance metadata rejects credential-like fields, source URLs reject
embedded credentials, special/set-id files are rejected by the common inventory
logic, and artifact symlinks may not escape the artifact root.

## Explicit installation phase

`ApplicationSoftwareStore.begin()` creates the writable **installation staging root**
for one durable operation. Build tooling may use source trees and temporary build
directories elsewhere, but only runtime material installed below `operation.root`
is eligible for publication. For station-access this means, for example:

- installed station-access Python modules and Django/runtime dependencies;
- executable entry points and immutable package data;
- the already compiled frontend/static assets;
- immutable configuration defaults and retained notices.

Frontend source trees, Node build caches, compilers, and other build-only inputs do
not become runtime dependencies merely because they were used to produce the staging
tree.

The producer sequence is:

```text
reviewed declaration
-> begin(operation)
-> install runtime material only into operation.root
-> finalize(operation)
-> sync + inventory + compatibility/notices validation
-> freeze exact manifest and artifact ID
-> move through same-filesystem candidate
-> atomic immutable publication
-> durable result binding
```

State is stored below:

```text
PROJECT/state/image-build/application-software/
    operations/<operation>/
        intent.json
        root/
        frozen.json
        result.json
    candidates/<operation>/
    artifacts/<sha256-hex>/
        manifest.json
        root/
```

If publication succeeds but the caller loses the response, `finalize()` discovers
and verifies the exact previously frozen artifact and records the same result. A
changed retained operation intent is rejected. A staging tree changed after freeze,
a conflicting/tampered published artifact, or a missing notice is an integrity fault;
publication does not silently generate a replacement identity.

The store shares image-build's cross-process
`PROJECT/state/image-build.lock`.

## Immutable application views

`ApplicationSoftwareViewStore` composes one or more already-published artifacts into
a separately content-addressed immutable view. The view contract is
`application-software-view-v1`; it references `applications-v1` artifacts without
copying or modifying them.

A view publication freezes:

- the application name and profile;
- the exact sorted artifact IDs;
- the deterministic path ownership/composition plan;
- the exact generated symlink targets and output inventory;
- conventional executable/library/resource visibility.

No artifact has overwrite priority. Two artifacts may contribute the same directory
only when its mode agrees. Any file/symlink ownership collision, file-vs-directory
collision, or parent-path collision is rejected.

The view itself contains directories plus deterministic symlinks. At runtime the
links address immutable artifact mounts below:

```text
/applications/.store/<artifact-hex>/
```

while the view is mounted at:

```text
/applications/<application>/
```

This gives applications conventional paths such as:

```text
/applications/<application>/bin
/applications/<application>/lib
/applications/<application>/lib64
/applications/<application>/share
/applications/<application>/libexec
```

without modifying the Basic root filesystem and without OverlayFS.

View publication state is durable:

```text
PROJECT/state/image-build/application-software/
    view-operations/<operation>/
        intent.json
        frozen.json
        result.json
    view-candidates/<operation>/
    views/<sha256-hex>/
        manifest.json
        root/
```

A partially composed candidate is never a published view. Recovery reconstructs only
the frozen composition from the exact retained artifact IDs. If the atomic view
publication succeeds but its response is lost, retry verifies and returns the same
view identity.

## Box-control consumer manifest

Image-build exports a verified `application-software-consumer-v1` manifest through:

```python
from zog.image_build.application_views import ApplicationSoftwareViewStore

views = ApplicationSoftwareViewStore(project_state)
binding = views.consumer_manifest(view_id, rootfs_compatibility)
```

Before returning, image-build verifies:

- the view identity and exact symlink inventory;
- every referenced artifact identity and installed-file inventory;
- `applications-v1` compatibility against the selected rootfs descriptor;
- all required artifact objects are available.

The manifest supplies controller-owned host roots, manifest paths, the exact rootfs
compatibility descriptor that was checked, deterministic runtime mount points for the
view and every referenced artifact, and a content digest of the consumer binding. It
also exports the exact `reclamation_protection` set. Box-control can therefore mount those objects read-only
without invoking image-build at application launch and can keep the referenced view
and artifacts protected while a runtime or prepared operation depends on them.

Corrupt, unavailable, or incompatible objects fail resolution. The consumer never
falls back to another artifact or reconstructs a view.

## Basic and Everything

**Basic** remains the minimal immutable host/rootfs generation and is not synthesized
from application views.

The `everything` view profile is the contract for an optional richer software view.
It uses the same immutable artifact/view/consumer semantics as ordinary applications.
The contract is complete without requiring all future packages to exist today.
Current or future artifacts such as xterm, TurboVNC, Qt, and Kate can be selected
explicitly; adding a package creates a new immutable view rather than changing an old
one.

## Reclamation and provenance

View manifests are durable references to their exact artifact IDs.
`referenced_artifacts(view_id)` and the consumer manifest expose those references for
reclamation protection. Artifact or view reclamation must never remove an object
protected by a prepared/running runtime or by a retained view that is still selected
by policy.

Artifact provenance remains producer-supplied immutable metadata; build-record owns
canonical provenance record identity/storage and build-trace remains read-only.
Views record composition, not a rewritten provenance graph.

## CLI

Artifact publication remains available through:

```sh
python -m zog.image_build.application_software --state-dir PROJECT/state ...
```

View publication/inspection/consumer binding are available through:

```sh
python -m zog.image_build.application_views \
  --state-dir PROJECT/state publish OPERATION view.json

python -m zog.image_build.application_views \
  --state-dir PROJECT/state inspect sha256:VIEW

python -m zog.image_build.application_views \
  --state-dir PROJECT/state binding sha256:VIEW rootfs-compatibility.json
```

The view declaration contains `application`, explicit `artifacts`, and optionally
`profile` (`application` or `everything`). No command accepts package-install or
arbitrary shell instructions.
