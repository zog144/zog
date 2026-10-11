# Box-control log integration

The default factory is `zog.station_access.box_control.journal:create_reader`.

| Portal operation | Controller operation |
|---|---|
| Runtime program log page | `application_logs(runtime_id, program, cursor=None, limit=50)` |
| Administrator build list | `list_build_jobs(after=None, limit=50)` |
| Administrator build details | `inspect_build_job(job_id)` |
| Administrator build log page | `build_job_logs(job_id, cursor=None, limit=50)` |

Both log HTTP endpoints accept 1–100 entries (default 50) and opaque cursors up to
4096 characters. The controller binds cursors to the recorded boot and invocation.
First read tails recent entries; subsequent reads advance from the returned position.
The portal never supplies arbitrary journal match expressions or unit names.
Application authorization uses persisted runtime references without synchronously
observing systemd. Workspace connection authorization separately uses fresh observation.

The UI selects one program at a time, resets its cursor on selection changes, and
retains up to 2000 entries. It supports severity filtering, loaded-message search,
multiline messages, pause/resume, hidden-tab suspension, follow-newest and visible-entry
download. There is no synthesized multi-program cursor.

`ok` and `empty-history` preserve the server cursor. `cursor-unavailable` maps to HTTP410
and explicit reload. `identity-unavailable` and `unavailable` map to HTTP503; the UI
retains its position for retry. Missing bounded MESSAGE data gets a visible marker.
Since pass11 exposes only a page cursor, UI row IDs are stable hashes of stream scope,
input/output page cursors and row position. Repeated identical messages remain distinct.

Django authorizes every request, checks program/invocation membership, bounds the page,
and returns successful log pages with `Cache-Control: no-store`. React renders escaped
text, not HTML or terminal escape sequences. Ordinary users cannot access build routes;
no per-user build ownership exists in this integration.


The portal treats these reads as observational only; log access never triggers lifecycle reconciliation.
