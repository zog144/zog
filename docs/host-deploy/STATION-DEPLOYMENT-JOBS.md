# Station deployment adapter — host-deploy 0.10.4

`zog.host_deploy.station.StationDeployment` provides asynchronous submit/poll for the station-access deployment job worker. It supports only fixed read-only inspection, destination-file application, and read-only outcome recovery. No CLI operation or live host is changed automatically.

Target preflight verifies STS account, exact running EC2 instance and ZogWorkspace tag. Submission uses a fixed stdlib Python helper through AWS-RunShellScript, with retries disabled. Validation failures before send raise NotSubmitted; any error from send may mean acceptance and must never cause an automatic resend. Poll responses are schema/job-ID checked and exclude stderr. The caller persists job intent before send and keeps command IDs privately.

The helper accepts only canonical config and destination paths. It checks the beacon's configured AWS binding, active process arguments, destination-file schema/owner/mode and enabled primary registry. It reports installation versions/service state without claiming health or delivery. Missing optional station-access service/version remains unknown. It does not install missing files or rewrite systemd units.

Application requires the inspected file hash, takes an exclusive operation lock, writes a private backup and prepared receipt before atomic replacement, preserves ownership/mode and verifies the new hash. Repeating a receipt ID cannot change its intent. Recovery only reads receipts/current configuration; absent receipts or conflicting files remain uncertain. No identity keys are changed or returned. Independent registry fingerprint approval remains required.

Canonical files: `/etc/host-discover/configuration.json`, `/var/lib/host-discover/beacon-destinations.json`. Private receipts/backups: `/var/lib/host-deploy/station-deployments`. Do not modify the destination file manually during an operation; the adapter lock does not coordinate unrelated writers.

Consumers must install the exact pinned repository commit. Local fixture tests are separate from live AWS acceptance; no live commands were sent in this pass. See station-access docs/DEPLOYMENT-JOBS.md for the user workflow, optional worker configuration and limitations.
