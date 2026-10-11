# Getting started with Zog

## Installation approaches

Zog has distinct source-package, host-build and live-host deployment paths. The public Python `zog` distribution is not, by itself, proof of a bootable Zog host. Begin with the [development source guide](DEVELOPMENT.md) or the owning [host-install documentation](host-install/README.md) after it is imported into the reviewed aggregate.

## First host and identity

Host provisioning belongs to [host-deploy](host-deploy/README.md); immutable system installation and STATE preparation belong to [host-install](host-install/README.md). The identity and beacon stages belong to [host-identify](host-identify/README.md) and [host-discover](host-discover/README.md).

## First application

[station-access](station-access/README.md) supplies browser access to applications and workspaces; [box-control](box-control/README.md) owns application-runtime lifecycle and systemd integration. A ready application requires a reviewed immutable generation and explicit deployment composition.

## First inspection

Inspect runtime history and journald via the authorized controller and UI; inspect build evidence through [build-trace](build-trace/README.md), [build-record](build-record/README.md) and [integrate-observe](integrate-observe/README.md). Do not use historical fixture commands on production hosts without independent live acceptance.
