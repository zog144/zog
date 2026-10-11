# Zog documentation

Human-facing Zog documentation is centralized here. Program documentation lives
under `docs/<program>/`; the `components/` tree is reserved for tests, fixtures,
frontend/build inputs, recipes, service descriptors and other integration support.

Repository-wide development notes are in [DEVELOPMENT.md](DEVELOPMENT.md).

## archive-mirror

- [`NOTICE-CONTRACT.md`](archive-mirror/NOTICE-CONTRACT.md)
- [`REVIEWED-SOURCES.md`](archive-mirror/REVIEWED-SOURCES.md)

## box-control

- [`APPLICATION-MOUNTS.md`](box-control/APPLICATION-MOUNTS.md)
- [`IMAGE-BUILD-EXECUTION-TYPES-AND-MAPPING.md`](box-control/IMAGE-BUILD-EXECUTION-TYPES-AND-MAPPING.md)
- [`PERSISTENT-APPLICATIONS.md`](box-control/PERSISTENT-APPLICATIONS.md)
- [`REGISTRATION-RECOVERY.md`](box-control/REGISTRATION-RECOVERY.md)
- [`WORKSPACE-APPLICATIONS.md`](box-control/WORKSPACE-APPLICATIONS.md)
- [`catalogue/build-visibility.md`](box-control/catalogue/build-visibility.md)
- [`catalogue/launch-preflight.md`](box-control/catalogue/launch-preflight.md)
- [`catalogue/process-inspection.md`](box-control/catalogue/process-inspection.md)
- [`catalogue/recovery-explanations.md`](box-control/catalogue/recovery-explanations.md)
- [`catalogue/recovery-inspection.md`](box-control/catalogue/recovery-inspection.md)
- [`catalogue/request-retention.md`](box-control/catalogue/request-retention.md)

## build-record

- [`contract.md`](build-record/contract.md)
- [`generation-audit.md`](build-record/generation-audit.md)

## build-trace

- [`ci.md`](build-trace/ci.md)
- [`integration-observations.md`](build-trace/integration-observations.md)
- [`schema.md`](build-trace/schema.md)
- [`usage.md`](build-trace/usage.md)

## host-deploy

- [`ARTIFACTS.md`](host-deploy/ARTIFACTS.md)
- [`AUTHENTICATION.md`](host-deploy/AUTHENTICATION.md)
- [`CLOUD-DEADLINE.md`](host-deploy/CLOUD-DEADLINE.md)
- [`DISCOVERY.md`](host-deploy/DISCOVERY.md)
- [`GATEWAY-GITHUB.md`](host-deploy/GATEWAY-GITHUB.md)
- [`GATEWAY-PROTOCOL.md`](host-deploy/GATEWAY-PROTOCOL.md)
- [`IMAGE-BUILD-LANES.md`](host-deploy/IMAGE-BUILD-LANES.md)
- [`JOBS.md`](host-deploy/JOBS.md)
- [`REBOOT.md`](host-deploy/REBOOT.md)
- [`RECOVERY.md`](host-deploy/RECOVERY.md)
- [`S3.md`](host-deploy/S3.md)
- [`STARTER-RECIPES.md`](host-deploy/STARTER-RECIPES.md)
- [`STATION-DEPLOYMENT-JOBS.md`](host-deploy/STATION-DEPLOYMENT-JOBS.md)

## host-discover

- [`HOST-INSTALL.md`](host-discover/HOST-INSTALL.md)
- [`MANAGED-STATE.md`](host-discover/MANAGED-STATE.md)
- [`SESSION-RECOVERY.md`](host-discover/SESSION-RECOVERY.md)

## host-identify

- [`HOST-INSTALL.md`](host-identify/HOST-INSTALL.md)
- [`MANAGED-PROTOCOL.md`](host-identify/MANAGED-PROTOCOL.md)

## host-install

- [`fixture-plan.md`](host-install/fixture-plan.md)
- [`host-generation-provenance.md`](host-install/host-generation-provenance.md)
- [`image-build-integration.md`](host-install/image-build-integration.md)
- [`state-contract-v1.md`](host-install/state-contract-v1.md)

## image-build

- [`BOOTSTRAP-STAGES.md`](image-build/BOOTSTRAP-STAGES.md)
- [`CONTROLLER-INTEGRATION.md`](image-build/CONTROLLER-INTEGRATION.md)
- [`LICENSING.md`](image-build/LICENSING.md)
- [`MONTHLY-PINS.md`](image-build/MONTHLY-PINS.md)
- [`NATIVE-BUILD-ENVIRONMENT.md`](image-build/NATIVE-BUILD-ENVIRONMENT.md)
- [`application-software-artifacts.md`](image-build/application-software-artifacts.md)
- [`archive-mirror-sources.md`](image-build/archive-mirror-sources.md)
- [`boot-build-tools.md`](image-build/boot-build-tools.md)
- [`build-record-integration.md`](image-build/build-record-integration.md)
- [`build-trace-contract.md`](image-build/build-trace-contract.md)
- [`catalogue/BOX-CONTROL-BUILD-EXECUTION-REQUEST.md`](image-build/catalogue/BOX-CONTROL-BUILD-EXECUTION-REQUEST.md)
- [`catalogue/IMAGE-BUILD-ARCHITECTURE.md`](image-build/catalogue/IMAGE-BUILD-ARCHITECTURE.md)
- [`catalogue/SEED-GENERATION.md`](image-build/catalogue/SEED-GENERATION.md)
- [`catalogue/TOOLCHAIN-CATALOGUE.md`](image-build/catalogue/TOOLCHAIN-CATALOGUE.md)
- [`cryptography-bootstrap.md`](image-build/cryptography-bootstrap.md)
- [`host-boot-packages.md`](image-build/host-boot-packages.md)
- [`host-readiness.md`](image-build/host-readiness.md)
- [`http-signatures-bootstrap.md`](image-build/http-signatures-bootstrap.md)
- [`integration-observations.md`](image-build/integration-observations.md)
- [`maturin-bootstrap.md`](image-build/maturin-bootstrap.md)
- [`observation-snapshot-publication.md`](image-build/observation-snapshot-publication.md)
- [`payload-paths.md`](image-build/payload-paths.md)
- [`python-enrollment.md`](image-build/python-enrollment.md)
- [`python-libraries.md`](image-build/python-libraries.md)
- [`python-runtime.md`](image-build/python-runtime.md)
- [`registration-continuation.md`](image-build/registration-continuation.md)
- [`registration-recovery.md`](image-build/registration-recovery.md)
- [`remote-operations.md`](image-build/remote-operations.md)
- [`retained-compiler.md`](image-build/retained-compiler.md)
- [`rust-bootstrap.md`](image-build/rust-bootstrap.md)
- [`systemd-core.md`](image-build/systemd-core.md)
- [`systemd-native.md`](image-build/systemd-native.md)
- [`systemd-prerequisites.md`](image-build/systemd-prerequisites.md)

## integrate-observe

- [`design.md`](integrate-observe/design.md)

## network-register

- [`ADOPTION-CUTOVER.md`](network-register/ADOPTION-CUTOVER.md)
- [`HOST-DISCOVER-DNS-DESIGN.md`](network-register/HOST-DISCOVER-DNS-DESIGN.md)
- [`NAME-LIFECYCLE.md`](network-register/NAME-LIFECYCLE.md)

## root-control

- [`JOURNAL-BARRIER.md`](root-control/JOURNAL-BARRIER.md)

## station-access

- [`ARCHIVE-AUTHORIZATION.md`](station-access/ARCHIVE-AUTHORIZATION.md)
- [`BOX-CONTROL-ADAPTER.md`](station-access/BOX-CONTROL-ADAPTER.md)
- [`BOX-CONTROL-LOGS.md`](station-access/BOX-CONTROL-LOGS.md)
- [`CLOUD-CREDENTIALS.md`](station-access/CLOUD-CREDENTIALS.md)
- [`DEPLOYMENT-JOBS.md`](station-access/DEPLOYMENT-JOBS.md)
- [`DNS-DESTINATIONS.md`](station-access/DNS-DESTINATIONS.md)
- [`DNS-EVIDENCE.md`](station-access/DNS-EVIDENCE.md)
- [`DNS-MEMBERSHIP.md`](station-access/DNS-MEMBERSHIP.md)
- [`DNS-SETUP.md`](station-access/DNS-SETUP.md)
- [`GENERATION-PROVENANCE.md`](station-access/GENERATION-PROVENANCE.md)
- [`HOST-GENERATION-AND-EXPORT.md`](station-access/HOST-GENERATION-AND-EXPORT.md)
- [`MANAGED-SESSION-RECOVERY.md`](station-access/MANAGED-SESSION-RECOVERY.md)
- [`MANAGED-SESSIONS.md`](station-access/MANAGED-SESSIONS.md)
- [`MIRROR-STARTUP-CONTRACT.md`](station-access/MIRROR-STARTUP-CONTRACT.md)
- [`PORKBUN-ONBOARDING.md`](station-access/PORKBUN-ONBOARDING.md)
- [`PORTAL.md`](station-access/PORTAL.md)
- [`PROVENANCE-ENCOUNTERS.md`](station-access/PROVENANCE-ENCOUNTERS.md)
- [`REGISTRIES-DEPLOYMENTS.md`](station-access/REGISTRIES-DEPLOYMENTS.md)
- [`USERS-AND-RELEASE.md`](station-access/USERS-AND-RELEASE.md)
- [`VNC-WORKSPACES.md`](station-access/VNC-WORKSPACES.md)
- [`WEBSOCKIFY.md`](station-access/WEBSOCKIFY.md)
- [`WORKSPACE-PROVENANCE.md`](station-access/WORKSPACE-PROVENANCE.md)
- [`integration/IMAGE-BUILD.md`](station-access/integration/IMAGE-BUILD.md)

Documentation that is itself part of a fixture/example remains colocated with
that fixture. Documentation specific to separately licensed third-party material
remains beside that material.
