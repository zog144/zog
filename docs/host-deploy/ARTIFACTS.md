# Resumable transfers and artifact publication — 0.6.0

This release requires no S3 permission changes. New functionality is validated
locally using real files and injected interruption/storage faults. No new AWS
resources were created for this release; live S3 validation remains deferred.

## SSM transfer recovery

Uploads now use content-bound temporary files, check an existing prefix, resume
at its verified length, and publish the complete destination atomically. A lost
chunk reply does not require transferring that chunk again. Existing complete
matching files are reused. Interrupted attempts for different content have
separate temporary filenames; these are not automatically pruned.

Generic-job and reboot result collection persist verified download progress.
Retries check completed chunks and download only missing/damaged payloads.
Completed generic result archives are frozen on first collection so their hashes
remain stable across retries. Reboot archives are cached while workflow progress
is unchanged; changed progress produces a new snapshot. Keep the same local
output location and partial files to resume a download. Workspace checkpoints
do not include partially downloaded bytes; move them separately if needed.

SSM limits remain 2 MiB for source and 20 MiB for results. These changes do not
make the existing S3 backend resumable; S3 transfer enhancements/live acceptance
are deferred alongside its unavailable permissions.

## Filesystem artifact store

The store is an implemented filesystem backend and a stand-in for testing future
remote object storage. For independence from an EC2 VM, it must reside on an
externally backed shared filesystem, mounted where the publisher and retriever
can access it. No such mount is provisioned by host-deploy. A directory on the
VM's root disk does NOT survive termination; Work scratch is also transient.

```sh
host-deploy artifact-init --store /mounted/artifacts
host-deploy artifact-publish --store /mounted/artifacts --id build-one \
  --source ./results.tar.gz --retention-seconds 604800
host-deploy artifact-fetch --store /mounted/artifacts --id build-one \
  --output ./recovered-results.tar.gz
host-deploy artifact-prune --store /mounted/artifacts
```

Publication binds identity to full SHA-256, chunk hashes, size and metadata.
One-MiB chunks are committed durably and reused after interruption. A final
publication receipt is written only after every chunk verifies. Fetch requires
that receipt, verifies chunks/full hash, and can repair/resume a partial file.
It needs no running VM once the store is independently accessible.

Retention defaults to seven days from first publication intent, including failed
attempts. Allowed range: 60 seconds to 365 days. Retries do not extend retention.
Expired artifacts cannot be fetched. Prune explicitly deletes expired complete
and incomplete artifacts belonging to this store. Durable tombstones prevent
old retries from recreating pruned identities. Tombstones and lock files remain;
their bounded retention is not implemented. Use a dedicated trusted store, and
do not edit its internals. Operations serialize per artifact on filesystems with
working flock, atomic rename/link and fsync semantics. Distributed object-store
locking is not implemented.

## Publish automatically after a generic job

Add this optional field to a job recipe, using the path as seen on the VM:

```json
"publication": {
  "store": "/mounted/artifacts",
  "retention_seconds": 604800
}
```

Initialize/mount the store before submitting. The worker publishes its frozen
results after saving the terminal job outcome, using the job UUID as artifact ID.
Job-status includes the publication state. Publication failure is saved separately in publication.json and does not turn a
successful test into a failed test. Run `job-publish --workspace DIR --job NAME`
to retry publication after the worker is inactive; it never reruns the command.
The response reports published or publication_failed. Publication is bounded by
the job service's remaining RuntimeMaxSec allowance (90-second overhead); large or slow publication may require the explicit retry while the
VM is available. Publication does not automatically stop the host.

Once publication succeeds, artifact-fetch retrieves from the store without EC2
or SSM. The receipt contains source identity and terminal outcome. Recipes and
environments can contain sensitive application data; avoid secrets in them.
No AWS credentials are copied into the store or distributed starter by tooling.

## image-build readiness

The accessible image-build-handoff-pass1.zip is the 2026-08-29 archive, using
Fedora package closure and Podman. Its seven image-build tests passed locally.
It is not the newer Amazon Linux build-chain implementation discussed elsewhere.
A representative live compilation run remains blocked on that newer source and
its build recipe. The old archive was not modified, and no Fedora/Podman workload
was substituted for the requested Amazon Linux acceptance test.
