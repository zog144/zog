# Workspace provenance

Station-access 0.4.28 adds a read-only **Provenance** action to each workspace card.
It lives on the workspace selection page beside Edit/Delete and does not add controls
to the live VNC workspace.

## Evidence basis

Workspace provenance is based on immutable box-control runtime history. For every
visible workspace runtime, station-access shows:

- immutable runtime identity;
- application name and instance identity;
- desktop versus attached-application role;
- recorded runtime state;
- the rootfs generation recorded when that runtime was launched;
- resolution of that generation against archived root-filesystem observations.

The page never re-resolves the current application declaration to answer what a past
or running runtime used. A later application-specification edit or a newly selected
generation therefore cannot rewrite the provenance shown for an already launched
runtime.

The endpoint declares this explicitly as:

`basis: immutable-runtime-history`

## Generation resolution

Station-access resolves a launched generation only against complete, successful archive
observations whose artifact kind is `root-filesystem` and whose recorded generation
identity exactly matches the runtime generation.

Repeated observations of the same rootfs are harmless. Resolution compares the distinct
rootfs SHA-256 digests observed for that generation:

- no matching digest → `unresolved`;
- exactly one digest → `resolved`;
- more than one distinct digest → `conflict`;
- no generation recorded on the runtime → `unknown`.

A conflict never selects one digest arbitrarily.

For a resolved generation, the newest complete observation of that exact digest is the
administrator detail binding. It carries the mirror UUID, observation snapshot UUID,
collection and digest required by Generation Detail. Generation Detail revalidates that
binding and its artifact-bound notice evidence independently.

## Permissions

Workspace ownership is checked before controller access. Ordinary workspace owners can
see the runtime identities and launched generation/rootfs digest for runtimes they are
authorized to see. Revoking access to an attached application removes that application's
runtime from this view. The workspace desktop remains visible to its workspace owner.

Generation Detail remains an Administration surface in 0.4.28. Ordinary workspace
owners therefore see that a generation resolved but do not receive its administrative
archive locator or link. Administrators receive the exact Generation Detail link.

This pass deliberately does not broaden Archive or Generation Detail permissions.

## Empty and unavailable states

A workspace that has never been registered with the current workspace controller has an
empty provenance history. Reading provenance does not register the workspace, launch a
desktop, reconcile lifecycle state, or create controller requests.

If controller runtime history itself cannot be read, the endpoint fails rather than
substituting the current application specification.

## API and browser route

The owner-scoped API is:

`GET /api/workspaces/<workspace-uuid>/provenance/`

The browser view is:

`/workspaces/<workspace-uuid>/provenance`

Both are read-only. The API response uses `Cache-Control: no-store`.

## Validation boundary

Regression tests cover:

- owner-scoped immutable runtime generation display;
- inclusion of the workspace desktop;
- exact administrator Generation Detail bindings;
- conflicting generation/digest observations;
- revoked attached-application access;
- authorization before controller access;
- a never-registered workspace with no side effects;
- direct browser routing and breadcrumbs;
- the workspace-list Provenance action;
- administrator versus ordinary-user Generation Detail links.

The normal execution-capable validation remains:

```sh
python tools/test-backend.py
cd frontend
npm ci
npm test
npm run build
```

This regular-chat source pass does not claim those commands were executed or that
0.4.28 was deployed to a running station.
