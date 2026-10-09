# Install only after image-build supplies this foreground launcher and source-built
# TurboVNC/i3. Declarative data, not imported Python. See IMAGE-BUILD-HANDOFF.md.
application(
    name="vnc-workspace",
    multiple_instances=True,
    workspace_role="desktop",
    start_policy="externally-controlled",
    programs=(program(
        name="vnc-server",
        command=("/usr/libexec/zog/vnc-workspace", "{workspace-display}",
                 "{workspace-xauthority}", "{workspace-vnc-socket}"),
        user="regular",
    ),),
)
