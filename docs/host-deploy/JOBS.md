# Generic background jobs (pass 3)

A job is a trusted source ZIP plus a JSON recipe. The command is an argv list,
executed from the extracted source directory. Use ["bash", "build.sh"] for a
shell script. ZIP executable mode bits are not restored. Outputs are relative
paths to collect along with the job record, status and combined stdout/stderr.

Jobs run as root on a disposable host. They are not a sandbox for untrusted code.
Each job has a separate directory and systemd service. Jobs may overlap on the
same host; CPU/memory admission and build-cache management are not included.
Do not put credentials into sources or recipes: job definitions and environment
values are retained in evidence, and SSM commands remain in AWS command history.

## Submit and disconnect

```sh
host-environment/bin/host-deploy job-submit --workspace ./build-workspace \
  --job compile-one --source ./source.zip \
  --recipe host-deploy/examples/background-job.json
host-environment/bin/host-deploy job-status --workspace ./build-workspace \
  --job compile-one
host-environment/bin/host-deploy job-collect --workspace ./build-workspace \
  --job compile-one --output ./compile-one.tar.gz
```

The host must already be running and SSM-ready. Submit returns after starting a
systemd service; Work can disconnect. Submit does not wait for completion or stop
the host, since other jobs may still be using it. The host's uptime timer remains
the ultimate operating-system deadline. Explicit stop/terminate commands can
interrupt jobs and should be used only when that is intended.

The example allows a one-hour command, so provision with a maximum uptime longer
than an hour before using it. Admission checks the saved host uptime budget and
reserves 120 seconds. It does not extend the deadline. The default 30-minute host
example is intentionally too short for that one-hour job. A modified timer or an
additional shutdown scheduled externally can shorten the actual available time.

The command timeout is recorded separately from its return code. A nonzero exit
is failed; a command deadline is timed_out. A killed worker without a terminal
record is reported interrupted when inspected after the service disappears.
Source extraction is covered by the systemd service deadline, which includes
90 seconds beyond the command timeout. No job resumes automatically after reboot.

Job names are request identities within a workspace. Reusing a name with matching
source hash, recipe and host returns the existing job; changed inputs are rejected.
Use job-status after an interruption. Preserve the workspace/jobs files. A source
ZIP does not need to remain local for status or collection. A repeated submit
still requires it to verify the request matches.

Both local submission intent and remote dispatch/worker status use synchronized
writes. A durable dispatch record prevents replay. If dispatch was recorded but
no execution evidence can be established, status is submission_uncertain; the
program does not restart it. It cannot guarantee execution in every crash window.
A new job name is an explicit new execution, so do not invent one merely because
a prior submission timed out. Inspect the existing evidence first.

Collect does not extract downloaded archives locally. It verifies SHA-256 and
length before publishing the result path. Existing output paths are refused.
Failed and timed-out jobs have downloadable evidence too. The CLI command itself
can succeed at inspection/collection even when the job failed; inspect the state.
Source and remote result directories persist on the host until explicit host
termination. Automatic pruning remains future work. Cancellation is now supported; see RECOVERY.md.

## Larger files through S3

See [S3.md](S3.md) for the default shared bucket, source/result transfer,
verified recovery without the VM, and workspace-scoped cleanup.
