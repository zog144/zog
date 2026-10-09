# Registries and Deployments setup

Station-access 0.4.1 builds on the workspace-menu commit 8e67b34d4731af8fcaf2b0435c188643009cd7d5 on `unstable`. The Home → Administration navigation and workspace behavior are preserved. New pages are Administration → Registries and Administration → Deployments. Host-discover is 0.3.3; host-identify remains 0.3.0.

## Registries

Superusers can add and label Cloudflare or Porkbun accounts and replace API credentials. Cloudflare requires its account ID and API token; Porkbun requires API key and secret API key. Porkbun credentials can be stored and explicitly checked using the external network-register 0.4.0 dependency, including domain listing; it cannot be selected for DNS reconciliation. Saving either account does not test permissions, purchase a domain or alter provider DNS.

Provider secrets are AES-GCM encrypted with the existing protected station vault keyring, using a separate associated-data namespace that binds row identity, provider, account and revision. They are never returned, revealed, included in destination exports, or placed in audit details. Blank credential fields during editing preserve the saved value; supplied credentials replace the entire provider credential set. Provider and account identity cannot change in place. Keep backups of encrypted data and vault keys separately. A database backup alone cannot decrypt the credentials.

An operator must initialize `HOST_VAULT_CONFIGURATION` with `manage.py create_station_vault /absolute/private/vault.json` if it is not already configured. Run as the station-access service account with an owner-only parent directory. Never overwrite an existing keyring. The page reports vault readiness; it does not regenerate a missing key.

“Use for DNS reconciliation” selects a credential whose Cloudflare account must match the existing authoritative controller configuration. The background reconciler decrypts the selected credential in memory on its next run. Returning to the configured credential file restores the legacy source. Domain, suffix, controller state directory, ownership ledger and single-writer lock remain unchanged. Missing vault material or account mismatch fails closed; a selected credential never silently falls back to another secret.

## Deployments

The list stores normalized HTTPS registry origins, labels, enabled state and optional public CA certificates. Origins cannot contain paths, credentials, queries or fragments. A hostname change creates a different destination. Disable the former entry rather than losing its history. All changes require administrator sessions and CSRF, use revision checks, and produce nonsecret audit events. Limits: 32 provider accounts, 16 destinations, 30 KB total exported list.

Save persists deployment intent. Download exports `beacon-destinations.json`; **it is not automatic installation and the page explicitly reports installation status unknown**. There is no provider password or host private key in this file. It does contain network topology and should be protected. No arbitrary outbound URL is contacted while saving.

Host-discover 0.3.3 accepts:

```sh
host-discover --configuration /etc/host-discover/configuration.json \
  --destinations /var/lib/host-discover/beacon-destinations.json
```

Install the list atomically as the beacon service account, file mode 0600, outside reusable root images. The daemon rereads it every cycle. Existing single-configuration invocations continue to work. Always include the primary URL from the existing configuration; mark it disabled to stop its reports. This preserves the original migration UUID, key and authority. A public CA certificate is optional; blank selects system trust, while a PEM certificate selects custom trust. HTTPS verification and redirect rejection remain enabled.

Additional destinations are **observation-only**. Each gets its own persistent key, registry UUID binding and owner-protected storage below the primary identity directory, named by the normalized origin's SHA-256. They do not inherit the migration UUID, login export, role adapter or archive authority. They do not save archive grants or execute mirror roles. This avoids competing controllers and password disclosure. Multi-controller failover and shared authority are not implemented by a beacon list.

Read public fingerprints on the trusted deployment connection:

```sh
host-discover --configuration /etc/host-discover/configuration.json \
  --destinations /var/lib/host-discover/beacon-destinations.json --fingerprint
```

With the list flag this prints a JSON list of destination origins and fingerprints. Without it, the original single fingerprint output remains. Compare each fingerprint independently and approve it in that destination registry. Adding a destination or holding an old bearer token never approves a key. A failing destination does not prevent attempts to the others, although sequential request timeouts can lengthen a cycle.

Disabling a destination stops attempts once the installed file is read, clears its local archive credential, and withdraws primary role intent when applicable. It does not revoke the remote identity, erase historical state, or invalidate bearer tokens already copied elsewhere before expiry. Secondary destinations are intentionally read-only reporting endpoints in this pass.

## Current host-deploy handoff

Use this repository's complete `host-discover/` 0.3.3 and existing `host-identify/` 0.3.0. Do not install historical `reference/host-deploy-0.7.0`. Update the current host-deploy beacon bundle and readiness/version markers in its own repository before advertising bundled support. Add an optional destination-list input to `host-install`; validate/stage it, retain owner-only permissions, pass `--destinations` in the service command, and preserve identity/credential state on ordinary reinstalls. Compare `--fingerprint` output through SSM, but leave GUI approval to the operator. Removing the list option returns to the original primary configuration. Current host-deploy has not been republished by this pass.

## Remaining installation UI gaps

| Setup area | Current gap / next action |
| --- | --- |
| Provider onboarding | Porkbun adapter, read-only credential permission checks and domain discovery/selection are missing. |
| Authoritative DNS controller | Domain/suffix initialization, durable state recovery and authoritative-controller selection still require operator setup; do not regenerate ownership state automatically. |
| Applying deployment settings | No host-deploy job integration, per-host profile assignment, installation acknowledgements or rollback UI. The list must be installed explicitly. |
| Cloud compute | AWS/GCP account onboarding, IAM/SSM checks, instance creation, instance size/disk selection and inventory region configuration remain outside this UI. |
| Public HTTPS | Public origins, Django allowed hosts, proxy configuration, certificate issuance/renewal and firewall checks require deployment configuration. Beacon destinations do not configure inbound web domains. |
| Root filesystem / controller | Selecting and verifying rootfs generations, controller readiness, persistent application preparation and upgrades need an installation workflow. |
| Graphical workspaces / Networks | Existing network menu is a placeholder; shared namespace setup, TurboVNC/websockify prerequisites and end-to-end desktop checks remain. |
| Archive service | Host grants and role selection exist; issuer key provisioning/rotation, mirror storage/endpoints, adapter setup and serving readiness need guided setup. |
| Recovery | Backup/restore, protected key recovery, administrator credential rotation and a consolidated setup/readiness page are missing. |

A useful next pass is a read-only setup checklist that distinguishes configured, installed and verified states, followed by an explicit host-deploy apply job. Saving a form must not be presented as proof that a provider, daemon or desktop is operational.

## Deployment and rollback

Back up database, application code, environment and protected state before installation. Apply migrations `host_registry.0007_setup_configuration` and the merged `station_access.0003_workspace_network_and_sequence`. Both are additive; compare existing rows/columns before and after. Deploy the rebuilt frontend with both new routes and breadcrumb labels. Keep DNS/inventory/beacon services running except for the short maintenance window required for consistent backup/migration. Do not create a new host or approve/revoke keys during migration.

On application failure restore the previous source/frontend and restart. Leave the additive schema in place rather than restoring a stale database over new decisions. Restore protected data only through a separately reviewed recovery operation. Existing file-backed DNS credentials remain the default until an administrator chooses a stored account.
