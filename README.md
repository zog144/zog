# Zog

Zog composes immutable root filesystems, application software and explicit writable
state into systemd-managed runtimes, with browser administration and workspaces.
This is the public aggregate source repository for the Zog project.

**0.1.0 is a development source snapshot, not a published release.** Development
uses `unstable`; this promotion does not change `main`. Boot, graphical workspace,
application installation and host acceptance remain separate milestones.

## Python installation and source layout

Use Python 3.12 or newer. From a checkout of this source tree:

```sh
python -m venv .venv
.venv/bin/python -m pip install .
```

The single distribution is `zog`. Its fourteen component packages live under
`src/zog/`; internal components are not separate PyPI requirements. The wheel
contains Python implementation and declared runtime resources. It does not contain
a root filesystem, frontend bundle, dependency trees or the recipe catalogue.

| Source | Purpose |
|---|---|
| `src/zog/` | Fourteen installed component namespaces |
| `components/` | Selected component tests, maintained docs and integration inputs |
| `components/image-build/project/` | Version-bound recipes, source pins and catalogue |
| `components/station-access/frontend/` | React frontend source, npm lockfile and notice tooling |
| `third-party/gcc/` | Explicitly attributed, separately licensed GCC test patches |
| `release-sources.json` | Exact source revisions, exported hashes and transformations |
| `src/zog/_release_manifest.json` | Component versions and internal relationships |

The component repositories remain independently maintained. This snapshot selects
exact revisions; it does not follow newer component branch heads. See
[development and build notes](docs/DEVELOPMENT.md) and
[license/source boundaries](THIRD-PARTY-NOTICES.md).

## Components

- archive-mirror: source archives and their notices.
- box-control: application and program runtime orchestration.
- build-record: canonical build provenance records.
- build-trace: read-only build inspection.
- host-deploy: explicit remote deployment and job orchestration.
- host-discover: host discovery and signed beacon transport.
- host-identify: durable host identity.
- host-install: host installation and persisted state preparation.
- image-build: package builds and immutable rootfs/application software production.
- integrate-observe: independent inspection of published observations.
- network-register: domain and DNS provider integration.
- root-control: privileged runtime operations.
- station-access: authenticated web administration and workspace access.
- version-share: exact source retrieval and publication tooling.

Installation does not start services, build a frontend, provision AWS resources,
or install a host. Configure deployment-specific values explicitly. Example cloud
identifiers are placeholders and must be replaced deliberately.

## Licensing and collaboration

Original Zog code, documentation and artwork in this export are licensed under
**BSD-3-Clause OR GPL-3.0-only**. Third-party terms remain separate. See
[LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

Zog is developed by its maintainers in collaboration with ChatGPT, an AI system
from OpenAI. This collaboration includes architecture, implementation, testing,
documentation and code review.

The public repository owns the guarded PyPI publication workflow. A later reviewed
release will build and test canonical artifacts once, retain them, and publish the
same bytes to GitHub Releases and PyPI through Trusted Publishing. No release tag
or package publication is part of this source snapshot.
