# Initial cross compiler and libc bootstrap

This pass targets x86_64 and LFS 13.1-systemd. It reuses a recorded Amazon Linux
`host-bootstrap` seed. It does not mark the cross tools as self-hosted.

Run with a dedicated project and the explicit controller configuration documented
in CONTROLLER-INTEGRATION.md:

```
python3.11 -m zog.zog.image_build.stages \
  --project /absolute/bootstrap-project \
  --package-dir /absolute/image-build-source/project/package \
  --plan /absolute/image-build-source/project/bootstrap/lfs-cross.py \
  --controller-config /absolute/controller.json \
  --seed /absolute/seed-project/state/image-build/generations/GENERATION
```

Exit 75 means pending: repeat the identical command. The durable pipeline retains
recipe snapshots, command identities, input bindings and completion evidence.
Changed inputs, failed commands and uncertain outcomes are not silently retried.
The operation record is under `state/image-build/cross-bootstrap/operation.json`.

## Stage graph

`project/bootstrap/lfs-cross.py` maps stable stage IDs to per-project recipe
directories. Each stage becomes a package node in the existing durable pipeline.
Dependencies refer to stage IDs; package names and stage names remain separate in
presentation metadata. This allows multiple recipes for the same upstream project.
The plan records build and target tuples; recipes also record host tuples.

The initial plan contains Binutils 2.47, GCC 16.2.0 with bundled GMP 6.3.0,
MPFR 4.2.2 and MPC 1.4.1, Linux 7.1.8 API headers, and Glibc 2.44 with the two
LFS patches. The Linux kernel itself is not built or replaced.

Cross tools install under `/tools`; the new headers and libraries install under
`/sysroot`. Commands use explicit PATH and CONFIG_SITE. Each stage installs only
into its output mount. Roots remain read-only and external network access is
disabled. Source acquisition occurs before isolated compilation.

The source tarballs and patches are pinned by SHA-256. Their downloaded bytes
were compared with the published LFS MD5 values over HTTPS. This is checksum
verification with an HTTPS trust source, not detached-signature verification.
GitHub repository mirrors are recorded as secondary references where verified;
they are not automatic substitutes for release tarballs, whose generated files
and digests may differ. Unverified mirror locations are not invented.

## Output ownership

Small packages retain exact `produce-manifest.py` file lists. Large toolchain
stages may use `{'trees': [...], 'required': [...]}`: every produced file must
belong to an explicitly allowed tree and required files must exist. The completed
package result records the complete exact inventory and hashes. Composition
still rejects file ownership conflicts. Shared Info index files are omitted from
the cross-tool recipes to avoid conflicting ownership of generated indexes.

## Verification and limits

A compile/link probe checks the new headers, sysroot startup objects, libc,
ELF interpreter and absence of RPATH/RUNPATH. A separate verification root is
assembled from the source-built sysroot and the probe executable. That executable
checks the runtime Glibc version. No seed shell, compiler or library is copied
into this verification root. Execution remains through box-control.

The cross compiler executables themselves still run against the Amazon Linux
seed runtime. Native compiler stages, libstdc++, complete temporary tools and
self-hosted rebuilding remain later work. Bootstrap validation is not a claim
that the full GCC/Glibc upstream suites have run.

## Build visibility for station-access

The current image-build completion/recovery implementation is retained, with
pass11 box-control and its `build_job_logs` and `list_build_jobs` API.

For each authorized attempt directory, call:

```
zog.image_build.build_views.read_build_commands(attempt, after=None, limit=50)
```

Mappings contain pipeline ID, attempt ID, stage ID, upstream project, phase,
command index, argv and durable job/request identities. They are saved before
submission; null IDs mean no checkpoint yet and do not imply execution. Use the
job ID with `control.inspect_build_job` for persisted outcome and
`control.build_job_logs` for invocation-scoped log pages. Keep a cursor per job.
A view mapping is presentation data, not authoritative completion evidence.
Use `ImageBuild.inspect_pipeline(pipeline_id)` for the overall persisted status
and error, including preparation/registration failures before a job exists.

Station-access must authorize project/attempt/job access before calling these
local APIs; never accept arbitrary filesystem paths from browser requests.
Poll summaries separately from the selected command's logs. Restart paginated
command enumeration each polling cycle to find newly added entries. Render log
text as text and display cursor-unavailable as an explicit history gap.

Probe jobs are grouped under their verification attempt names with package null.
They are finite build jobs, not ordinary application runtimes. This pass supplies
and exercises the integration API; it does not deploy a station-access website.

References:
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter05/chapter05.html
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/packages.html
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/patches.html

For these large source trees, the acceptance controller configuration uses a
600-second transport wait. Registration includes durable tree preparation and
may exceed the 60 seconds sufficient for M4. This caller wait is distinct from
the 1500-second command execution bound and the one-second pending-result wait.
A registration timeout must resume the same resource identity; it is not evidence
that registration or execution never happened.

## Explicit failed-stage restart

After inspection, `--restart-incomplete-stage glibc-cross-initial` explicitly
retires that incomplete stage and starts it with new controller identities. It
requires a failed/unknown job, refuses running jobs and completed stages, proves
process cleanup and releases registrations before retirement. All original files
and job IDs remain under a named retired stage directory. Verified dependency
outputs remain in place and are revalidated by the normal pipeline. The durable
restart journal makes repeating this explicit request idempotent; a second failure
requires separate investigation, not another automatic attempt.

The acceptance harness starts root-control as an independent systemd service.
Its D-Bus references must outlive a timed-out host-deploy caller so completed
transient units retain their exit status until controller observation. Production
deployment must likewise keep root-control independent of individual build jobs.

The first log request returns the latest entries (a tail), not the oldest page.
Poll `next_cursor` even when `has_more` is false: new output may arrive later.
An empty next page at completion is normal. The live acceptance retains a cursor
from compilation and confirms that reading forward from it advances afterward.

## Temporary native build environment

After the native compiler/M4 acceptance, `zog.zog.image_build.build_environment.run` builds the eight reviewed stages in `project/bootstrap/lfs-native-environment.py`, then verifies and publishes their combined root. See [NATIVE-BUILD-ENVIRONMENT.md](NATIVE-BUILD-ENVIRONMENT.md) for its input binding, dependency graph, cleanup and promotion boundary.

A recipe correction requires a new operation identity. If the earlier pipeline is unfinished, first use the existing `release_pipeline` API after its controller confirms process cleanup. This retains diagnostic files and explicitly prevents resuming the superseded pipeline; it does not silently change its recorded recipe.
