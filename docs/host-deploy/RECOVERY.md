# Recovery and deliberate controller handoff

Version 0.5.0 can move the saved identity of an existing host and its jobs to a
fresh controller. Install the same starter version and supply credentials
separately. Restoration does not launch an instance or execute a job.

## Move an active job to another controller

After `job-submit` returns, export the initialized workspace:

```sh
host-deploy checkpoint-export --workspace ./build-workspace \
  --output ./build-checkpoint.zip --handoff
```

This retires the original workspace before publishing the archive. Further
workspace operations refuse to run there. Export can be retried to a new output
filename if publication fails after retirement. Keep the exported checkpoint in
a durable location accessible to the next Work container; scratch alone is not
a backup. The tool does not automatically upload checkpoints to ChatGPT.

In the new container:

```sh
python3 host-deploy/bootstrap.py --environment ./host-environment \
  --workspace ./restored-workspace --restore-checkpoint ./build-checkpoint.zip \
  --credentials-file ./aws.txt
host-environment/bin/host-deploy doctor --workspace ./restored-workspace --remote
host-environment/bin/host-deploy job-status --workspace ./restored-workspace --job compile-one
host-environment/bin/host-deploy job-collect --workspace ./restored-workspace \
  --job compile-one --output ./compile-one.tar.gz
```

Use the credential profile named in the checkpoint; bootstrap defaults to
zog-development. `doctor --remote` requires a running, SSM-online host. If it has
stopped, `start` verifies the host timer and permits new submissions again.
Starting the VM does not restart a previously interrupted job.

Export without `--handoff` creates a backup and leaves the workspace usable.
Restore backups only after abandoning the old controller. A checkpoint is a
snapshot: jobs submitted afterward are absent. Save another checkpoint after
new submissions or resource changes. Source archives and downloaded results
are separate artifacts, not copied into the checkpoint.

## Integrity and scope

Checkpoint archives include only workspace, launch, host, optional storage, and
job and reboot-workflow JSON records, with SHA-256 hashes and cross-checked identities. Unexpected
paths, duplicate entries, oversized data, identity inconsistencies and damaged
content are rejected before the destination is published. Restore requires a
new directory. Writes are synchronized to disk; a failed export may leave the
original workspace retired, from which export can safely be retried.

Credentials files are excluded. Job command lines and recipe environments are
included because they are part of the saved execution identity. Do not place
secrets in recipes; treat a checkpoint as sensitive if you have done so. Hashes
detect damage, not malicious rewriting by someone who can replace the archive.

Retirement is a local workflow safeguard, not distributed access control.
Do not restore the same checkpoint into two controllers for concurrent use.
Use independently initialized workspaces for independent EC2 resources. A
shared IAM key can still access whatever AWS authorizes; local ownership tags
and checkpoint validation are not an IAM security boundary.

## Cancel or shut down

```sh
host-deploy job-cancel --workspace ./restored-workspace --job compile-one
host-deploy job-collect --workspace ./restored-workspace \
  --job compile-one --output ./cancelled-results.tar.gz
host-deploy stop --workspace ./restored-workspace
```

Cancellation records intent before stopping the systemd service and its cgroup.
Repeating cancellation is safe. A completed success/failure/timeout is preserved;
a stopped unfinished job is reported as cancelled. Cancellation does not delete
logs or outputs. If delivery is uncertain, retry cancellation or inspect status.

Routine stop and terminate inspect remote jobs and refuse active or uncertain
submissions. Failure to inspect also blocks shutdown. Dispatch and shutdown
admission share a remote lock; successful admission closes the host to new jobs
until `start` verifies readiness and reopens it. A failed EC2 stop request can
leave admission closed: retry stop or use start to reopen it.

`--force` on stop/terminate explicitly bypasses inspection for emergency cleanup,
including an unreachable host. Termination still requires the exact owned
instance ID and destroys its disk. The uptime deadline remains a hard stop and
does not wait for jobs. Local process crashes do not disable that VM-side timer.
There is no AWS-side deadline in this release.

Reboot workflow records are included starting with version 0.5.0. Use REBOOT.md
for the separate persistent test-state directory on the VM and for coordinating
preparation, normal reboot, reconnection and verification.
