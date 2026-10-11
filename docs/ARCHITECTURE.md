# Zog architecture

## Component map

- **Build and supply:** archive-mirror obtains reviewed sources; image-build produces immutable rootfs and application artifacts; build-record maintains canonical provenance; build-trace exposes factual observations; integrate-observe compares selected evidence.
- **Host ownership:** host-install establishes disk generations and durable STATE; host-identify owns host identity; host-discover announces authenticated host evidence; root-control is the privileged controller boundary.
- **Runtime and control:** box-control manages expected application launches and reconciliation; station-access exposes authenticated browser administration; host-deploy provisions and coordinates owned remote operations; network-register reconciles authorized DNS names.

## Trust and privilege boundaries

The host-root controller, locally trusted runtime orchestrator and network-facing command center are separate responsibilities. Credentials, authorization, host identity and provider inventory must be verified by their owning services; UI observations alone do not establish authorization.

## Immutable artifacts and runtime architecture

Image-build supplies pinned, immutable generations. Box-control launches native applications in systemd-managed cgroups and mount namespaces using those artifacts, while persistent runtime STATE is mounted deliberately and not silently merged into immutable software views.

## Host lifecycle and control plane

Installation, enrollment, signed beacons, inventory reconciliation and workspace/application dispatch are distinct state transitions. See the program-specific manuals for currently implemented protocols versus future designs.

## Evidence and provenance

Build-record and build-trace form the canonical producer/read-only-query split. Integrate-observe compares facts without independently deciding causation, severity or policy.
