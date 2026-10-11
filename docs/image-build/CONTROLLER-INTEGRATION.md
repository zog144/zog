# image-build integration pass 2

Use the `image-build-source` distribution with box-control pass8 in a dedicated
Python 3.11+ environment on a host with systemd 250 or later. The sibling `image-build` directory is the preserved
legacy application image provider, not this source builder.

## Deployment

Start root-control using its existing deployment procedure. Configure a dedicated
nonzero build UID/GID different from the project owner. Give the image-build
caller appropriate access to build-group files; automatic ACL management is not
provided. Compilation runs only through box-control/root-control and systemd.

`--state-dir` is PROJECT/state, not PROJECT/state/image-build. Controller resource
registration requires attempts below PROJECT/state/image-build/attempts.

Example controller.json (replace paths and identity with your deployment values):

```json
{
  "project_root": "/home/project/zog",
  "socket_path": "/run/zog/root-control.sock",
  "execution_user_id": 21001,
  "execution_group_id": 21001,
  "startup_timeout_seconds": 30,
  "execution_timeout_seconds": 3600,
  "termination_grace_seconds": 10,
  "wait_timeout_seconds": 300,
  "transport_timeout_seconds": 90,
  "resource_limits": {
    "thread-count-maximum": 256,
    "memory-maximum-bytes": 2147483648
  }
}
```

Execution identities, resource limits, deadlines and controller project/socket are
explicit. Input-manifest identity is derived from the engine's verified package
preparation record, including recipe/dependency/toolchain identities and the
prepared root inventory. Mutable post-configure source trees are not rehashed as
if they were fresh inputs. Probe identity binds its prepared root inventory.

```sh
python -m zog.image_build --package-dir PROJECT/package --state-dir PROJECT/state \
  --controller-config controller.json bootstrap HOST_GENERATION stages.py
python -m zog.image_build --package-dir PROJECT/package --state-dir PROJECT/state \
  --controller-config controller.json build TOOLCHAIN_GENERATION package-name
```

## Interrupted callers

A pipeline snapshots package definitions and saves its intent before executing.
The pipeline ID is the directory name under state/image-build/pipelines, appears
in exception notes, and is accepted by `inspect`, `resume`, and `release`.

```sh
python -m zog.image_build --package-dir PROJECT/package --state-dir PROJECT/state \
  inspect PIPELINE_ID
python -m zog.image_build --package-dir PROJECT/package --state-dir PROJECT/state \
  --controller-config controller.json resume PIPELINE_ID
```

Resume continues the recorded pipeline, using its recipe snapshot and original
controller request IDs. It verifies prepared roots and completed package output
inventories before reuse. Changed original recipe files do not change the
pipeline. Source URLs still must supply their recorded checksums (or be cached).
The execution policy remains bound; caller wait and transport timeouts may change.
A caller wait expiry does not cancel the command. Whole bootstrap continuation
includes both stages, their probes, publication and activation.

A failed or uncertain pipeline blocks starting a new pipeline until it is resumed
or explicitly released. A nonzero command stays failed on resume; it is never
silently rerun. To change a recipe after failure, release the old pipeline and
start a new one. This first pass does not migrate pre-pass2 attempt directories;
retain and resolve those separately.

## Release

After successful package output validation, image-build synchronizes and records
outputs, then calls box-control to release command pins and imported roots. Caller
source/output trees remain available for composition and diagnostics. A lost
release reply is retried before continuing, without rerunning completed commands.
Generation reclamation remains box-control's responsibility.

`release PIPELINE_ID` explicitly abandons continuation, records retained outputs,
and requests release of its controller resources. This does not cancel running
commands. The controller refuses release without proven cleanup; retry release
after the finite job ends, or use box-control's cancellation API. Missing or
ambiguous controller records require investigation rather than assumed success.
The abandonment intent is recorded before release and prevents later resume.

## Host-seed acceptance

`verify-seed HOST_GENERATION TARGET...` exercises source compilation/composition
from a recorded host seed. It publishes a `seed-check` generation and does not
activate it or mark it as a source-built toolchain. Ordinary builds continue to
require a promoted second-stage toolchain.

The Amazon Linux fixture under acceptance/ uses host-deploy, checks execution
isolation/result cases, then invokes the CLI with a short caller wait and resumes
its pipeline in a new process. It verifies the static executable prints 42, its
build-only library is absent from the composed root, and resources are released.
This is not full GCC/libc toolchain self-hosting or abrupt-power-loss acceptance.

Build dependency overlays preserve existing toolchain directory modes while
adding files. Temporary owner permissions are restored after staging; final image
composition retains strict directory-mode and file-collision checks.
