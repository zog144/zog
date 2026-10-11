# Operating Zog

## Provision and install

Start with [host-deploy](host-deploy/README.md) for provisioning and inventory, then [host-install](host-install/README.md) for disk preparation, immutable boot generations and persistent STATE. Never substitute fixture procedures for production cutover acceptance.

## Enroll and discover

[host-identify](host-identify/README.md) owns identity. [host-discover](host-discover/README.md) transmits authenticated host evidence to the registry. Enrollment approval, inventory verification and DNS ownership remain explicit controls.

## Create a workspace and launch applications

[station-access](station-access/README.md) provides browser workflows; [box-control](box-control/README.md) launches applications, protects expected state and records lifecycle history. Workspace and application lifetime must not be conflated.

## Run and inspect a build

Use [image-build](image-build/README.md) for source-pinned recipes and immutable output publication. Inspect provenance and verification with [build-record](build-record/README.md), [build-trace](build-trace/README.md) and [integrate-observe](integrate-observe/README.md).

## Diagnose, recover and replace

Use owning service recovery interfaces, preserve operation identity and uncertain markers, and prefer bounded inspection before retrying mutations. Host provisioning, controller replay, build publication and production cutover each require separate acceptance.
