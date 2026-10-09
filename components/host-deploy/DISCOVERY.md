# Signed discovery, host-deploy 0.10.5

`host-install` and `install-discover` are aliases for the same signed installer.
The pinned external packages are host-discover 0.3.4 and host-identify 0.3.0. Retrieve the exact dependencies in version-share-handoff.json and pass --source DIRECTORY containing both package directories; see README.md. The payload allowlist and SHA-256 checks reject missing or modified sources before upload. The beacon rejects an approved or saved binding that contradicts the configured migration UUID; it never silently adopts the other record.
The old bearer reporter has been removed. No live rollout is performed by installing
host-deploy locally.

## Before testing

Deploy the matching command-center pass3 release and database migration 0005 first.
`--server-ready` is your explicit acknowledgement of that prerequisite; the installer
does not inspect/migrate the command-center database or approve keys. The selected
AWS host must be running, owned by the saved workspace, reachable through SSM, and
have Python >=3.12 with venv/pip, 512 MiB free under /opt, and dependency network access.
The previously tested Amazon Linux host's Python 3.9 is insufficient. Provision
Python 3.12 separately, or use an appropriate image. `--python /absolute/python`
selects another existing interpreter. The installer fails its interpreter preflight
before changing a working service. Third-party wheels are not bundled.

There is no default origin or bundled command-center workspace. Public CA trust is
the fresh-install default. `--system-ca` explicitly removes an old custom CA setting;
`--ca-file FILE` installs custom trust. Without either flag, reinstall preserves
existing trust. TLS verification is never disabled.

## Existing bearer beacon: migrate on the same EC2 instance

```
host-deploy host-install --workspace TARGET --registry-workspace COMMAND_CENTER --migrate --server-ready \
  --server https://registry.example.org --system-ca
```

This stages both new packages and a virtual environment, preserves the existing
registry UUID as a claim, and removes the legacy token only from the activated
configuration. It creates a dedicated signing key locally when missing. Compare
the printed public fingerprint with the pending entry in the command-center UI;
approve that exact key against the existing record. Do not create a replacement
registry record. Labels/history/DNS reservations belong to that existing record.
The old token cannot approve the key. A pass2 signed upgrade uses the same command
and retains its existing key, binding, role request IDs and credentials.

The first successful contact can be **pending**, not approved. Once approved, rerun
the same install command to check the binding and then again if its result says
`binding-received`; the next bound contact can report `signed-accepted`. The normal
service also retries every minute, so waiting before rerunning is sufficient.
Reinstall does not reset identity or schedule another service. `discover-status`
shows systemd state only; it does not establish current central approval.

## Fresh host

```
host-deploy host-install --workspace NEW_TARGET --configuration-file examples/host-discover.example.json --server-ready --system-ca
```

Copy and edit the example outside the source checkout; `registry.example.org` is a
placeholder, never an automatic default. Select the domain in station-access first,
then pass that destination here. The installer does not infer a domain from the UI
or a bundled workspace. A signed reinstall can omit the server to retain the host’s
existing configuration; a fresh installation without a server fails before service
activation. CLI `--server` takes precedence over the explicit JSON file.

When a receipt records a command-center instance, migration requires the matching
`--registry-workspace`; it can be combined with `--configuration-file`. The installer
never silently substitutes another command center.

A fresh host generates its own key and requests pending enrollment. Manually
compare/approve its fingerprint in the UI, then verify as above. No central bearer
enrollment command or central SSM access is required. `--registry-workspace`
remains available to identify an alternate command center for migration checks.
`--configuration-file` supplies nonsecret daemon configuration, including another
HTTPS origin and archive settings; AWS identity must match the selected target.
Never copy identity/credential directories or target configuration to another host.

Automatic discovery during `provision` uses the same installer. Supply
`--registry-configuration` pointing to a copy of `examples/registry-provision.example.json`
after replacing its example server and setting `server_ready` to true after server preparation. Both an explicit server and readiness acknowledgement are checked before launch.
Use `--no-discovery` when preparing an image/host that does not yet have Python 3.12.
A dependency/activation failure after launch leaves an owned host available for
repair; it does not silently destroy or stop it.

## Archive-mirror role

Role handling, lease state, scoped grant storage, consumer helpers and the optional
box-control adapter are included. A mirror elected without a local adapter reports
`blocked` / `bridge-unconfigured`. Installation does not elect mirrors or grant
archive access. This bundle contains no archive-mirror application or usable rootfs.
Actual mirror start/readiness acceptance remains deferred until those exist.

Before enabling archive policy, configure the exact `archive_mirror`,
`archive_issuer`, and `archive_audience` values using `--configuration-file`.
Do not deploy the upstream example domains. Optional `mirror_box_control` requires
an already provisioned compatible application/project, dependencies in the beacon
venv, and narrowly scoped service permissions. Reinstall refuses changes to an
existing bridge or identity path: withdraw/stop its owned runtime and review the
migration first. Existing administrator systemd drop-ins are preserved.

Station-admin login export is optional and is never copied through host-deploy.
If needed, perform the verified on-host export described in the upstream handoff,
then configure its protected local `station_login_file` path. No station-access
installation or login is required for ordinary reporting.

## Failure and state handling

Code/venv releases live under /opt/host-discover/releases. Private keys/binding/role
state remain under /var/lib/host-discover/identity (0700); scoped credentials under
/var/lib/host-discover/credentials (0750, archive-consumers). Only authorized
consumers should belong to archive-consumers. The service is non-root, has a 0077
umask and writable access limited to these state directories.

The installer uses a host-side lock and atomic configuration writes. It stages
dependencies before stopping the old daemon and performs the contact probe while
that daemon is stopped. Ordinary activation failure restores the previous config
and unit; key/role state is never rolled back. Root-only rollback copies may contain
the old bearer token: they stay on the host and must not be exported or baked into
images. An interrupted activation can leave the service stopped; rerun the same
command to complete installation. A Work interruption is not a transactional
rollback guarantee. Do not downgrade or disable the beacon to stop a mirror:
withdraw its role and confirm the exact runtime stopped while retaining archives.

Receipts contain only public fingerprint, identifiers and installation state.
They distinguish pending, binding-received and signed-accepted; archive access and
mirror state are separate observations. Neither service-active nor exit code zero
alone proves approval or readiness. Credentials and identity state never enter
workspace checkpoints or the distributable ZIP.

Protocol, filesystem, mirror startup and administrator details are preserved in
the station-access repository’s historical `HOST-DEPLOY-HANDOFF.md` and `docs/` directory. Those documents describe their original release, not a bundled source dependency.

Legacy bearer receipts that lack cloud fields are accepted only with --migrate, a saved registry UUID and command center. Present but conflicting fields are rejected. The owned target workspace and on-host configuration must still agree on cloud identity and registry UUID.
