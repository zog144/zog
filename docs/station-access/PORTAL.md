# Station-access portal operation and development

Station-access is the React/Django UI for Zog applications, graphical workspaces,
runtime history, journald logs and host administration. The backend calls box-control's
Python API locally; browser users never receive direct controller access.

## Local first use

Use Linux and Python 3.12+. Install the aggregate Zog distribution as described in
the [development guide](../../../docs/DEVELOPMENT.md), then from `components/station-access`:

```sh
python serve.py --state-directory /absolute/private/station-state
```

The launcher runs migrations and creates an administrator only when the database has no
users. New deployment secrets and the first-login export live in the selected state
directory. Existing users, passwords and permissions are preserved.

Use `--initialize-only` to prepare state without serving, `--host`/`--port` to
change the listener, and `--project` to select the trusted local Zog declaration/state
project. Without a project, database-backed views work while live controller operations
report unavailable.

For maintenance commands, keep the same state directory:

```sh
export STATION_ACCESS_STATE_DIRECTORY=/absolute/private/station-state
python manage.py changepassword station-admin
```

Installing or initializing the portal does not provision root-control, a rootfs
generation, TurboVNC, noVNC/websockify or TLS.

## Configuration and deployment state

| Setting | Purpose |
| --- | --- |
| `STATION_ACCESS_STATE_DIRECTORY` | SQLite database, deployment secrets and workspace locks |
| `STATION_ACCESS_ZOG_PROJECT_DIRECTORY` | Trusted local controller project |
| `STATION_ACCESS_ALLOWED_HOSTS` | Served hostnames |
| `STATION_ACCESS_CSRF_TRUSTED_ORIGINS` | Browser origins accepted for CSRF |
| `STATION_ACCESS_SECURE_COOKIES` | Enable secure cookies for HTTPS |
| `STATION_ACCESS_TRUST_PROXY` | Trust replaced forwarded-protocol headers only behind the configured proxy |
| `HOST_IDENTITY_ORIGIN` | Canonical external HTTPS origin for signed host requests |
| `HOST_DNS_CONFIGURATION` | Central DNS reconciliation configuration |
| `HOST_VAULT_CONFIGURATION` / `HOST_ARCHIVE_CONFIGURATION` | Optional vault/archive policy configuration |
| `ARCHIVE_MIRROR_CONFIGURATION` | Optional archive-mirror integration |

Private state, credentials, signing keys and databases are deployment state, never source
or wheel inputs.

## Frontend boundary

Frontend source is maintained in `frontend/`. Production assets are built before
runtime as part of image/application construction and activated from immutable
application state. The Python wheel does not carry Node/npm or build frontend assets at
runtime.

See the [aggregate frontend build notes](../../../docs/DEVELOPMENT.md#frontend-source-build) and the maintained
[image-build integration contract](../integration/IMAGE-BUILD.md).

## Workspace applications

The workspace Applications panel searches authorized applications, shows attached runtime
history, links logs and supports confirmed exact-runtime stop operations. Reads do not
launch applications.

The workspace-v1 adapter uses durable controller request identity, authoritative
pending/cleanup membership and controller-owned display/Xauthority/VNC bindings. Launch
remains gated until the installed desktop/proxy environment has passed its own acceptance.
When enabled, `STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED=1` is an explicit deployment
choice.

## Workspaces and VNC

Workspace identity is stable across renames. Numbers are never reused. The default
supported network is host-shared; the UI does not claim network isolation.

Persistent noVNC sessions remain mounted while navigating the SPA. Opening a viewer can
start the workspace desktop on demand; explicit Stop stops it. Reboot recovery of the
desktop does not imply recovery of graphical client processes that were lost with the
boot.

Reconcile recorded workspace intent with:

```sh
python manage.py reconcile_vnc_workspaces
```

`STATION_ACCESS_VNC_APPLICATION_NAME` defaults to `vnc-workspace`. The declaration in
`integration/application.py` requires the selected generation to provide the foreground
launcher and runtime prerequisites. See [VNC-WORKSPACES.md](VNC-WORKSPACES.md) and
[WEBSOCKIFY.md](WEBSOCKIFY.md).

## Logs

Runtime log views use invocation-scoped journald reads with opaque cursors, retention-gap
handling, program/severity filters and bounded frontend buffering. Build logs are
administrator-only. Log reads are observational and do not trigger lifecycle
reconciliation. See [BOX-CONTROL-LOGS.md](BOX-CONTROL-LOGS.md).

## Provenance

Workspace Provenance follows immutable runtime history and the generation recorded at
launch; it never substitutes the current application specification. Host details can
display signed host-install slot/generation evidence, and Generation Detail exposes the
same canonical provenance read model as the JSON export.

See [WORKSPACE-PROVENANCE.md](WORKSPACE-PROVENANCE.md),
[GENERATION-PROVENANCE.md](GENERATION-PROVENANCE.md), and
[HOST-GENERATION-AND-EXPORT.md](HOST-GENERATION-AND-EXPORT.md).

## Development

The source boundaries are:

```text
../../src/zog/station_access/  Python/Django runtime (from component root)
tests/                    source-only backend tests
frontend/                 React source and build inputs
integration/              application/image integration declarations
```

Backend checks:

```sh
python manage.py test tests
```

Frontend developer loop:

```sh
cd frontend
npm ci
npm test
npm run test:licenses
npm run build
npm run dev -- --host 127.0.0.1
```

Vite proxies portal APIs to Django on port 8000 and websockify to port 6080. Local fixture
gateways simulate controller state only; they are not VNC/systemd acceptance.

The canonical installed Python package is `zog.station_access`, the executable is
`station-access`, and the aggregate owns the shared `zog` namespace. The wheel installs
all fourteen components together; no separate companion distribution is required.
