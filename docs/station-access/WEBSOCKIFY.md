# noVNC / websockify capability flow

station-access uses websockify token-based target selection with `JSONTokenApi`.
The browser does not choose an arbitrary private VNC host/port.

## Flow

1. An authenticated user opens one of their running `VncWorkspace` records.
2. Django verifies ownership, the exact box-control runtime binding, desired-running state,
   and that the workspace has a VNC endpoint binding.
3. Django returns a short-lived random capability to React and stores only its SHA-256
   digest.
4. React passes the capability into the noVNC iframe WebSocket path.
5. websockify receives `?token=<capability>` and calls the private Django resolver.
6. Django re-checks workspace/runtime/endpoint-revision binding and returns `{host, port}`.
7. websockify connects to that server-selected TurboVNC endpoint.

The token is intended for connection establishment. The persistent iframe remains mounted
while the user navigates through station-access, so ordinary React navigation does not
reconnect the VNC session.

## Example websockify configuration

Conceptually:

```sh
websockify \
  --token-plugin=JSONTokenApi \
  --token-source='https://station-internal/internal/websockify-target/<secret>/?token=%s' \
  6080
```

Use the exact current websockify command-line syntax when deploying; the essential contract
is the HTTP token lookup returning JSON `host` and `port`.

The `/internal/websockify-target/...` route should not be exposed by the public reverse
proxy. The path secret is defense in depth for a resolver that websockify cannot call with
an arbitrary authorization header.

## Workspace-v1 Unix targets

For controller-managed workspaces the private resolver returns
`{"host":"unix_socket","port":"/controller/resolved/path/vnc.sock"}`.
The `port` field is a Unix path in this websockify token-plugin convention, not a
TCP port. Source inspection of websockify 0.13.0 verified that `JSONTokenApi`
forwards the pair and its proxy handles the `unix_socket` sentinel. Pin/test that
version or verify the same convention when upgrading. This is source validation,
not a live browser/proxy acceptance result.

Run the proxy with the unprivileged desktop account's socket access and restrict
the internal resolver route. Django checks fresh desktop incarnation/readiness
both when issuing a token and when resolving it; endpoint changes invalidate
previous grants. Host paths are never returned by public workspace APIs.
Existing TCP grant fields remain solely for old fixture/legacy records; workspace-v1
uses only controller-owned Unix endpoints. There is one token-routing proxy listener.
