# Cloud credentials — station-access 0.4.4

Administration → Cloud credentials (`/clouds`) supports AWS entries and explicitly
unavailable Microsoft Azure / Google Cloud placeholders. Only superusers can read or
change cloud metadata or run checks; mutations require CSRF. Responses use no-store.

## Administrator workflow

1. Enter a label, expected 12-digit AWS account ID, commercial AWS region and source.
2. Prefer the station service's default SDK credential chain where suitable. This may
   resolve environment credentials, a service profile or an instance role; it is not a
   claim that an instance role exists, nor does this attach one. The web user cannot
   choose arbitrary profiles, endpoints or credential-process commands.
3. Alternatively enter access key ID and secret access key. Temporary credentials also
   require a session token and its timezone-qualified expiry. The expiry is the
   administrator's supplied value, not a value retrieved from STS. No automatic session
   refresh is provided for these saved keys.
4. Save, then explicitly select Check AWS identity. The fixed regional HTTPS STS
   GetCallerIdentity request compares the returned account with the expected account.
   It does not establish EC2, SSM, billing or provisioning permission. TLS verification
   remains enabled. Connection/read timeouts are 5/10 seconds and one request attempt;
   default-chain credential resolution can take additional time under local SDK setup.
5. Replacing keys requires the whole key set. Blank fields on edit preserve the saved
   key set and expiry. Account and source are immutable; add a separate entry to change
   them. Disable old entries to retain their configuration/audit history. Disabling
   does not revoke credentials at AWS or stop running workers/jobs.

## Storage and boundaries

Saved keys use the existing HOST_VAULT_CONFIGURATION AES-GCM keyring with distinct cloud
AAD binding UUID, AWS account, credential source, region and revision. Metadata APIs,
checks and audit events never return keys, session tokens, raw SDK errors or caller ARNs.
The page clears entered secret fields after both successful and failed submissions.
Default-chain entries need no vault key. Static entries fail closed without the vault.
Do not enable SDK HTTP/debug logging on a credential-handling service.

The page saves **intent only**. It does not select or replace credentials used by existing
AWS inventory, DNS, host-deploy or beacon workers, and has no credential export endpoint.
Do not mistake a saved/checked account for an applied configuration. A future explicit
host-deploy job must bind credential UUID + revision + target account, recheck enabled
state and expiry, verify AWS identity immediately before operations, and resolve secrets
only inside the trusted worker. Default-chain credentials refer to the executing service;
checks on this station do not prove another worker resolves the same credentials.

Checks are explicit, globally serialized within cloud checks using a database-backed
60-second attempt lease, and rate-limited per entry. Network I/O holds no database gate.
Results cannot overwrite a newer attempt and cannot verify a changed revision. An
expired attempt can be retried after restart; interrupted and stale checks remain visible.
A matching result is current for at most 15 minutes, and only for an enabled, unexpired
entry. Entries are capped at 32. These checks do not provision or purchase anything.

## Deployment and verification

Back up the database and vault keyring with protected permissions. Stage the source and
frontend assets, install the existing dependencies, and run Django migrations through
host_registry 0009_cloud_credentials (0008 is also needed on hosts still at 0007).
The migration is additive and does not rewrite existing host/security/registrar records.
Restart station-access through its normal deployment mechanism, then check admin-only
navigation, an entry save, and an explicit identity check. Keep the previous release for
code rollback; do not reverse database migrations over newer saved configuration.

Local verification: 192 Django tests and 56 frontend tests passed, plus production
TypeScript/Vite build. New coverage exercises encrypted storage and AAD binding, redacted
API/audit/errors, admin/CSRF enforcement, no network on save/read, account mismatch,
expiry, default credentials, stale updates, credential-change races, attempt recovery,
throttling and UI secret clearing. AWS responses use mocks; no live AWS credentials,
cloud operations or command-center deployment were used for this pass.

References: https://docs.aws.amazon.com/boto3/latest/guide/credentials.html and
https://docs.aws.amazon.com/boto3/latest/reference/services/sts/client/get_caller_identity.html

Concurrent work preserved: this pass was reapplied without overlapping edits onto
6e8e9ff5af799d90cbe8d183d5c64cc65a199207, including host-discover 0.3.4
cancellation compatibility and persistent archive-mirror live acceptance evidence.
