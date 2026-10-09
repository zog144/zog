"""Read-only, allowlisted observations; never register, launch or repair a workspace."""
from django.utils import timezone
from . import controller_workspaces
from .workspace_applications import launch_actions

# Controller exception/message text can contain paths, parameters and secrets.
# Only known check codes and locally authored explanations cross the browser API.
CHECKS = {
    "project-snapshot": ("Controller snapshot", "Controller state is busy or unreadable. Refresh later."),
    "project-location": ("Controller configuration", "An administrator must check the controller project configuration."),
    "preparation-admission": ("Preparation admission", "Application preparation needs administrator attention."),
    "recovery": ("Controller recovery", "An administrator must inspect the controller recovery evidence."),
    "application-definition": ("Application definition", "The application declaration needs administrator attention."),
    "application-state": ("Application records", "Application records could not be verified."),
    "instance-policy": ("Instance policy", "The controller must verify the application instance policy."),
    "image-inputs": ("Root filesystem", "Publish and activate a usable image-build generation, then refresh."),
    "application-preparation": ("Application preparation", "Prepare the application for the selected filesystem generation."),
    "systemd-version": ("Systemd connection", "Check controller connectivity and the supported systemd version."),
    "workspace-binding": ("Workspace attachment", "Workspace attachment could not be verified."),
    "workspace-required": ("Workspace registration", "The workspace has not yet been registered by a desktop start."),
    "unknown-workspace": ("Workspace registration", "The workspace has not yet been registered by a desktop start."),
    "workspace-deleted": ("Workspace registration", "The controller records this workspace as deleted. Administrator recovery is required."),
    "cross-workspace-singleton": ("Application instance", "This single-instance application belongs to another workspace."),
    "application-ineligible": ("Workspace attachment", "This application does not support workspace attachment."),
    "desktop-not-ready": ("Desktop display", "The workspace desktop is not ready. Inspect its status and logs."),
    "workspace-unverified": ("Workspace attachment", "Workspace readiness could not be verified."),
    "inspection-busy": ("Controller snapshot", "The controller is busy. Refresh later."),
}


def preflight(workspace, gateway, application):
    try:
        gateway.require_workspace_contract()
        raw = gateway.preflight_workspace_application(application, str(workspace.pk))
        if raw.get("schema") != 1 or raw.get("application") != application or raw.get("advisory") is not True:
            raise ValueError("Unsupported preflight")
        checks = []
        for item in raw.get("checks", [])[:40]:
            code = item.get("code")
            title, advice = CHECKS.get(code, ("Additional controller check", "An administrator must inspect the controller diagnostics."))
            state = item.get("status")
            if state not in ("ready", "blocked", "unable-to-verify"):
                state = "unable-to-verify"
            checks.append(dict(code=code if code in CHECKS else "other", title=title, status=state,
                               detail="Read-only check passed." if state == "ready" else advice))
        status = raw.get("status")
        if status not in ("ready-to-attempt", "blocked", "unable-to-verify") or not checks or len(raw.get("checks", [])) > 40:
            status = "unable-to-verify"
        if any(c["status"] == "blocked" for c in checks):
            status = "blocked"
        elif any(c["status"] == "unable-to-verify" for c in checks):
            status = "unable-to-verify"
        return dict(status=status, checks=checks, advisory=True)
    except Exception:
        return dict(status="unable-to-verify", checks=[], advisory=True)


def inspect(workspace, gateway, user):
    result = dict(observed_at=timezone.now().isoformat(), read_only=True, advisory=True,
                  controller="unavailable", desktop="not-verified", desktop_runtime_id=workspace.runtime_id,
                  launch_pending=workspace.launch_pending, cleanup_pending=None,
                  registration="recorded" if workspace.controller_schema else "not-recorded",
                  pending_count=None, cleanup_count=None,
                  launch_actions=launch_actions(workspace, user), preflight=None)
    if not workspace.controller_schema and (workspace.launch_request_id or workspace.runtime_id or workspace.launch_pending):
        result["registration"] = "legacy-recovery-required"
    try:
        gateway.require_workspace_contract()
        result["controller"] = "available"
    except Exception:
        return result
    result["preflight"] = preflight(workspace, gateway, workspace.application_name)
    if workspace.controller_schema == controller_workspaces.SCHEMA:
        try:
            claims = gateway.workspace_membership(str(workspace.pk))
            result["pending_count"] = sum(item["kind"] != "runtime" for item in claims)
            result["cleanup_count"] = sum(bool(item.get("cleanup_pending")) and item.get("state") in ("failed", "terminated") for item in claims)
        except Exception:
            pass
    if workspace.runtime_id:
        try:
            runtime = gateway.get_current_runtime(workspace.runtime_id)
            if not runtime or runtime.workspace_id != str(workspace.pk) or runtime.application_name != workspace.application_name:
                raise ValueError("Unverified desktop identity")
            result["desktop"] = runtime.state if runtime.state in ("running", "failed", "terminated", "starting", "stopping") else "not-verified"
            result["cleanup_pending"] = bool(runtime.terminal and runtime.cleanup_pending)
            if runtime.state == "running":
                controller_workspaces.access(workspace, gateway)
                result["desktop"] = "ready"
        except Exception:
            # A running process is distinct from a verified X11/RFB endpoint.
            pass
    return result
