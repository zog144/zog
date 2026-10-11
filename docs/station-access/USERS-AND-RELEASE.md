# Users and frontend release preparation — 0.4.12

Administration → Users replaces the need for Django's admin UI. Only active
station-access administrators may list, create, edit or delete accounts. Fields
are username, optional name/email, active status, administrator access and a new
password. The API never returns plaintext passwords or password hashes.

New/reset passwords use Django validation (minimum 12 characters, common-password,
numeric-only and account-similarity checks). Blank password on edit preserves the
existing password. Existing passwords are not changed by upgrading.

Edits/deletes carry an opaque keyed revision to reject stale forms. Deletion
requires typing the exact username. Self-deletion, self-disablement and self-demotion
are blocked. At least one active administrator is retained. Accounts owning
workspaces or applications cannot be deleted; make them inactive, or resolve
ownership through existing supported workflows first. This pass does not implement
ownership transfer. User-management mutations are serialized by the existing
security gate, with actor permissions rechecked inside the transaction. Audit
entries retain user IDs/names and action metadata, never passwords.

Password/status/role changes revoke existing database-backed sessions and unused
VNC grants. An administrator changing their own password keeps the current session;
other sessions are removed. Reactivation does not restore old sessions. Running
applications and already connected VNC sessions are not terminated by account
management. This is account CRUD, not remote process teardown. Changing a password
also does not rewrite FIRST-LOGIN.txt, exported station-login credentials or
credentials stored at another registry; refresh those through the existing explicit
credential export/delivery workflow if used.

`/admin`, `/admin/` and all descendants are unavailable (404). Django admin's installed
app/migration history is retained for database compatibility; no admin site URL is
mounted. Existing users and audit history are preserved. No new migration is required
for this pass. A deployment upgrading from 0.4.10 still needs migration 0010 from
the preceding deployment-jobs pass.

## Production build

The previously active checked-in JavaScript already contained React's production
implementation. The earlier public-export review instead excluded `dist` and noted
that source files alone did not provide a working browser page. No production
feature requires the development server or a development React build.

`npm run build` now forces NODE_ENV=production before loading Vite, uses production
mode, clears stale output assets, includes third-party license notices and emits
`frontend/dist/frontend-build.json` with exact source/output hashes and bundled
package/license inventory. A build invoked directly in development mode is rejected.
`npm run dev` remains available for local development only. Django DEBUG now defaults
to false; explicit local debugging is still possible with STATION_ACCESS_DEBUG=1.
React StrictMode in source is not evidence of a development deployment.

Run `npm ci --include=dev`, `npm test`, `npm run build`, then from repository root
`python tools/check-frontend-release.py`. Build tools are required at build time;
Node/Vite are not needed on a host serving the compiled assets through Django/Waitress
and its HTTPS proxy. The standard source archive includes the complete built frontend,
license files and inventory. The Python wheel is a backend distribution; deployment
must also install the frontend assets and configure STATION_ACCESS_FRONTEND_DIRECTORY
when not using the documented source layout.

## Licensing and remaining release work

Correction, 2026-10-02: the dual-license declaration previously added to this
component was a scope mistake. Public licensing work belongs to release-build.
Original station-access material now carries the private Alex Black copyright
notice (Alex Black is a pseudonym). Python/npm metadata and emitted browser
notices agree with that declaration. Third-party licenses remain separate and
unchanged. See THIRD-PARTY-NOTICES.md.

This is not a full Zog release certification. The consolidation export must be
rebased on current source/pins, include compiled frontend assets plus their notices,
and audit the actual companion, Python and rootfs license/provenance inventories.
The final image-build rootfs, X11/TurboVNC and end-to-end workspace acceptance remain
pending. Production operators must retain unique secret keys, HTTPS, correct proxy
trust/secure-cookie/host settings and private state. The DEBUG default alone does
not establish secure deployment. No live deployment is performed by this pass.

The release check also found npm advisories on the previous React Router 7.9.1
and Vite 7.1.7 pins. This pass updates them to React Router DOM 7.18.4 and Vite
7.3.6, retaining the existing major versions, then rechecks tests/build/audit.
The deployment does not expose Vite or React Router server-rendering endpoints;
this update is not a claim that every reported advisory was exploitable here.
