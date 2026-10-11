# Workspace-v1 image-build integration contract

The installed controller dependency is box-control pass18 revision1, commit
`b17a1ea4dc4f41309795e7cb548674d0c5cf8b78`, contract `zog-workspace-v1`.
Source compilation and the final root filesystem remain image-build responsibilities.
No distribution TurboVNC substitute or untested executable is supplied here.

`application.py` is a parseable desktop declaration. Its foreground launcher
`/usr/libexec/zog/vnc-workspace` must be supplied by the generation. It receives
three positional arguments, resolved by the controller:

1. X display, `:<non-reused workspace number>`.
2. Xauthority file, `/run/zog-workspace/Xauthority`.
3. Private Unix VNC socket, `/run/zog-workspace/vnc.sock`.

The launcher must use exactly these bindings, consume the supplied X11 cookie,
serve its filesystem X11 socket in `/tmp/.X11-unix`, and configure a private Unix
VNC listener without a public TCP listener. Include both mount target directories
in the immutable rootfs. Do not regenerate the supplied Xauthority file, choose a
free display automatically, daemonize out of controller ownership, or stop the
server when a browser disconnects. The intended minimal window manager is i3;
application launching stays with station-access/box-control.

Desktop and client definitions use the same unprivileged host account/group.
Clients declare `workspace_role="client"` and leave DISPLAY, XAUTHORITY and
reserved mount targets to the controller. Workspace networking is explicitly
`host-shared`: all workspaces share the host network. No isolation is promised.
VNC authentication policy remains an administrator-owned recipe choice and
must be tested along with X11 authentication. Browser tokens authorize access
through the proxy; they are not credentials supplied to the VNC protocol.

The websockify process needs host-account access to the controller's private Unix
socket. Do not expose Xauthority, host paths or the internal resolver to browsers.
The controller returns the endpoint to the trusted station adapter. No separate
websockify listener or port per workspace is necessary.

Acceptance: two workspaces started in reverse numbering order; different desktop
incarnations and displays; authenticated proxy/RFB/X11 connections; a client in
each workspace; invocation-scoped logs; one client stopping without affecting
its peers; pending/cleanup claims blocking desktop teardown; lost-reply and
reboot recovery; stale-grant rejection; navigation retaining both noVNC frames.
This is still a live gate, not satisfied by local controller fixtures.
