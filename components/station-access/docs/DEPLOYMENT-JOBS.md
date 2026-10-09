# Bounded deployment operations — station-access 0.4.11

This pass implements only **Inspect host deployment** and **Apply beacon destinations** under Administration → Deployments. It publishes source; it does not deploy, enable the worker, or change any running host. Migration `host_registry.0010_deployment_jobs` adds a job table without modifying existing records.

## Workflow

1. Save the intended HTTPS registry destinations. Saving only changes the station database.
2. Select an existing enrolled AWS host with an approved identity and inspect it. This queues a read-only SSM inspection; loading/refreshing pages only reads local job records.
3. A successful inspection reports observed versions and service states, the primary registry, installed destination summaries and whether application is supported. Unknown version/service observations remain unknown.
4. Within five minutes, request a review showing the target account/region/instance and complete old/new lists. Confirm the displayed job to queue application. The review expires after five minutes; changed saved settings, identity binding, or remote file contents invalidate it. Applying cannot disable or remove the existing primary registry.
5. The worker records verified installation separately from downstream beacon acceptance. A new registry still requires explicit fingerprint approval. A successful job does not prove delivery, approval, external reachability, or full deployment readiness.

## Deliberate boundaries

AWS only, existing running instances only. No provisioning, installation, upgrades, service restart, arbitrary shell command, custom remote path, saved cloud-account selection, or automatic retry of an uncertain change. Uses the worker's default AWS SDK credentials. The credentials must belong to the target account. A matching `ZogWorkspace` EC2 tag and the approved host's saved workspace ID are mandatory. This is a host-deploy workspace, distinct from a graphical workspace.

Remote inspection requires `/etc/host-discover/configuration.json` with matching AWS identity. Applying additionally requires an active host-discover process launched with that `--configuration` and `--destinations /var/lib/host-discover/beacon-destinations.json`, a valid existing file owned by the service user with mode 0600, and an enabled primary registry. A stock beacon unit without `--destinations` can be inspected but cannot use Apply. This pass intentionally does not rewrite units or bootstrap missing files.

The destination file is the existing host-discover schema, maximum 16 entries/30KB. Public custom CA certificates may be supplied; private keys are rejected. The remote operation replaces the complete list atomically, retains owner/group/mode, stores a private backup and prepared receipt under `/var/lib/host-deploy/station-deployments`, verifies the resulting SHA-256, and leaves identity files untouched. The beacon reloads the list on its next cycle. Removed/disabled destinations do not revoke remote keys or already issued tokens.

## Operator setup (explicit deployment required)

Install station-access and the exact external host-deploy commit from `version-share-handoff.json`; the optional `deployments` dependency specifies host-deploy 0.10.4. The package lives in its own repository. Run the usual `manage.py migrate` with the existing station environment and database backup procedure.

Set `HOST_DEPLOY_JOBS_ENABLED=1` in the existing protected station environment for both web and worker processes. Default is disabled. Install the example service/timer in `deployment/deployment-jobs/`, adapting paths to the actual installation layout. Enable/start the timer and restart the web process only during an authorized deployment. The service uses the venv Python directly, avoiding relocated console-script shebangs.

Configure credentials accessible to the station-access worker (prefer an instance role). Required operations are STS GetCallerIdentity, EC2 DescribeInstances, SSM SendCommand with AWS-RunShellScript on approved target instances, and SSM GetCommandInvocation. Scope SendCommand to the managed instances and this document; the adapter additionally verifies account, instance state and workspace tag. This pass does not modify IAM. Targets need a functioning SSM agent and Python 3; SSM runs the fixed helper as root. No artifact bucket or downloaded executable is used.

The timer runs one bounded batch of up to 25 jobs. Run only this worker for these jobs. State and attempt IDs also guard duplicate workers and late replies. Review expiry may require another inspection if a queue is delayed. Disabling the flag stops processing, not an SSM command already accepted; retain access to outstanding job evidence.

## Interruption and recovery

The database records submission intent before contacting SSM. A lost reply, invalid response, timeout, or interrupted submission becomes **uncertain**. It blocks replacement operations and host archival. **Check original outcome** sends only a read-only receipt/hash inspection under the same immutable job ID. It never applies again. An interrupted read-only inspection can instead be closed as failed so a new inspection can be requested. All unresolved jobs remain visible alongside the latest 25 records.

If the receipt is absent or the observed file differs, the UI conservatively retains uncertainty. An operator must investigate the original SSM command and remote receipt/backup; this pass has no “force success”, retry-apply, or automatic rollback button. Backups and receipts are private operational state, not source artifacts. Preserve them when diagnosing an interruption. The file hash precondition and operation lock coordinate this adapter's writers; unrelated manual writers must not modify the destination file during an application.

## Verification and later acceptance

Local tests exercise administrator/CSRF guards, immutable reviews, stale intent, target changes, duplicate submissions, interruption recovery, digest verification, retention of unresolved jobs, file replacement and remote target preflight. These are fixtures; no live AWS operation is claimed.

For an authorized deployment, first inspect one known host and compare its observed version/state/destinations with the host. On a supported beacon host, review a small intentional list change while retaining the primary, apply once, verify the receipt/file hash and subsequent signed heartbeats separately. Use a disposable host for interrupted-reply recovery testing. Never deliberately interrupt the release command center for acceptance.

## After release

Keep the broader Deployments ideas deferred: install/update station-access; install/update host-discover; broader provisioning/configuration application and credential selection; certificate workflows; and backup/recovery. Root filesystem completion and release remain the immediate priority. These are a backlog, not an authorization to implement or deploy them.
