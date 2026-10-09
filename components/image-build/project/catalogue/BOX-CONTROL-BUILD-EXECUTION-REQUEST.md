# Required box-control interface for image-build

## Direction

image-build owns source/package resolution, bootstrap stages, immutable build
inputs, staging and output manifests. **box-control owns build process execution
and its systemd cgroup/namespace environment**, using root-control for privileged
mechanisms. host-deploy owns AWS provisioning and remote test batching.

No Docker, Podman, direct systemd-run, direct D-Bus, or native execution fallback
belongs in image-build. The old image-build extraction included a Podman runner;
carrying that forward was an implementation mistake and has been removed.

## Inspected baseline and concrete gap

Inspected `zog-recovery-inspection-pass7.zip`, retrieved September 13, 2026.
The older attached `box-control-systemd-structure-pass7.zip` exposes only a
systemd runtime placeholder.

The newer `BoxControl` facade launches declared applications and exposes runtime
and request inspection. `SystemdServiceDefinition` handles roots, binds,
working directory, identities and journald, but does not expose build-job
network isolation, a whole-job deadline or numeric exit status. root-control
validates roots against `state/rootfs/generations/<generation>/root` with the
legacy generation manifest, and writable sources beneath `state/mounts`.

Image-build's disposable roots currently live in its attempt tree. They cannot
be passed through that existing API as though they were registered application
generations. Its checks must remain intact. Registering fabricated legacy
manifests or bypassing root-control would not implement this boundary correctly.

## Proposed capability, not an existing API

Provide a synchronous build-job operation (or an asynchronous submit/inspect/stop
set with an equivalent caller adapter). It needs:

- A durable request identity bound to the complete build execution configuration.
- Explicit registration/pinning of the prepared build root. It consists of the
  selected immutable toolchain plus the declared build dependencies.
- Read-only root enforcement and writable source/output directories mapped to
  `/image-build/source` and `/image-build/output`, plus private temporary space.
  The controller decides and validates the permitted host-side path namespace.
- Exact argv, working directory, environment, execution user/group and timeout.
  Executable lookup must occur against the prepared root; recipe commands such
  as `cc` and relative test programs must not resolve on the host.
- An explicit network-disabled policy. Missing support must reject the request.
- A systemd transient service in a controller-owned slice, with recorded runtime
  and Invocation identities. No automatic restart of a build command.
- Completion evidence: numeric exit status or signal/timeout/fault classification,
  cgroup-empty/cleanup result, and an Invocation-scoped journald reference.
- Failure/uncertainty handling that retains the build root and staged inputs while
  execution or cleanup could still be live. No image-build deletion of active
  controller resources, and no implicit resubmission after a lost reply.

The interface must accept an already prepared root without calling image-build
again. That avoids a circular dependency through normal image selection.
Normal application reconciliation and recovery retain their existing semantics.

## Caller work already prepared

`image_build.runner.BoxControlRunner` is an explicit **integration port**. It
accepts an injected callable translating a `BuildExecutionRequest` to a typed
`BuildExecutionResult`; it does not pretend the current box-control has that API.
Without an adapter it raises an actionable error and starts nothing. Its request
carries read-only-root and network-disabled requirements. It rejects missing
runtime/Invocation/journal evidence, unsuccessful exit and incomplete cleanup.

This port is not production execution. Once the controller operation exists,
implement its adapter here and wire the CLI/API to a configured controller.
Unit tests currently use a recording executor; they do not establish systemd
isolation or full toolchain self-hosting.

## Acceptance through host-deploy

On an independently owned Amazon Linux host, with box-control/root-control and
the new interface installed:

1. Assemble and register a host seed and build the example library/executable.
2. Verify the root is read-only, networking is disabled, only declared writable
   mounts are available, and actual commands execute inside the prepared root.
3. Verify zero/nonzero exits, timeout, descendant cleanup, and Invocation-scoped
   journal evidence. A failed/uncertain job must not publish an image.
4. Execute the resulting static example expecting `42`; verify its build-only
   library is absent from the final image.
5. Separately author and execute a complete toolchain recipe set through both
   bootstrap stages. Only that establishes the agreed self-hosted toolchain.

The source bootstrap orchestration is ready for these controller semantics;
full GCC/glibc/tool-utility recipes are not supplied in this checkpoint.
