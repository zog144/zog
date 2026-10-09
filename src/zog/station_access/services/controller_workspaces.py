"""Workspace-v1 lifecycle. Called under the station workspace lock.

Controller admission/teardown is authoritative; no local namespace or systemd writes.
Old pending TCP-era requests retain their evidence and require explicit recovery.
"""
from pathlib import PurePosixPath
from zog.station_access.models import WorkspaceApplicationLaunch
from .workspaces import WorkspaceOperationError, _invalidate, _bind_runtime

SCHEMA = "zog-workspace-v1"


def register(workspace, gateway):
    gateway.require_workspace_contract()
    if not workspace.controller_schema:
        if workspace.launch_request_id or workspace.runtime_id or workspace.launch_pending:
            raise WorkspaceOperationError("Legacy desktop launch evidence requires explicit recovery before workspace-v1 migration")
        if workspace.network != "default":
            raise WorkspaceOperationError("Only shared host networking is supported")
        gateway.register_workspace(workspace)  # idempotent if the DB save loses its reply
        workspace.controller_schema = SCHEMA
        workspace.display_number = None
        workspace.vnc_host = None
        workspace.vnc_port = None
        workspace.launch_parameters = {}
        _invalidate(workspace)
        workspace.save()
    elif workspace.controller_schema != SCHEMA:
        raise WorkspaceOperationError("Unsupported saved workspace schema")


def bind(workspace, runtime):
    if runtime.workspace_id != str(workspace.pk):
        raise WorkspaceOperationError("Controller runtime belongs to another workspace")
    _bind_runtime(workspace, runtime)


def ensure(workspace, gateway):
    register(workspace, gateway)
    application = next((a for a in gateway.list_applications() if a.name == workspace.application_name), None)
    if not application or application.workspace_role != "desktop" or not application.multi_instance or application.start_policy != "externally-controlled":
        raise WorkspaceOperationError("Configure a multi-instance, externally-controlled workspace desktop application")
    current = gateway.get_current_runtime(workspace.runtime_id) if workspace.runtime_id else None
    if workspace.runtime_id and current is None:
        raise WorkspaceOperationError("Desktop runtime evidence missing; explicit recovery required")
    if current and not current.terminal:
        if current.workspace_id != str(workspace.pk) or current.application_name != workspace.application_name:
            raise WorkspaceOperationError("Desktop runtime binding is inconsistent")
        return current
    if not workspace.launch_pending:
        if workspace.launch_request_id and not workspace.runtime_id:
            raise WorkspaceOperationError("Desktop launch has no runtime evidence; explicit recovery required")
        workspace.launch_request_id = gateway.issue_application_request_id()
        workspace.launch_pending = True
        workspace.runtime_id = workspace.instance_id = None
        _invalidate(workspace)
        workspace.save()  # outside a transaction, before submitting controller work
    runtime = gateway.find_application_launch(workspace.application_name,
        request_id=workspace.launch_request_id, workspace_id=str(workspace.pk))
    if runtime is None:
        runtime = gateway.launch_application(workspace.application_name,
            request_id=workspace.launch_request_id, workspace_id=str(workspace.pk))
    bind(workspace, runtime)
    if runtime.terminal:
        raise WorkspaceOperationError("Desktop launch ended; inspect its logs before another attempt")
    return runtime


def access(workspace, gateway):
    value = gateway.workspace_desktop_access(str(workspace.pk))
    endpoint = value.get("vnc_endpoint") or {}
    path = endpoint.get("path")
    if (value.get("schema") != SCHEMA or value.get("workspace_id") != str(workspace.pk)
        or value.get("desktop_runtime_id") != workspace.runtime_id or value.get("ready") is not True
        or endpoint.get("kind") != "unix" or endpoint.get("browser_direct") is not False
        or not isinstance(path, str) or not path.startswith("/") or "\x00" in path
        or ".." in PurePosixPath(path).parts or len(path.encode()) > 107):
        raise WorkspaceOperationError("Controller desktop endpoint is unavailable or inconsistent")
    return path


def ready(workspace, gateway):
    runtime = ensure(workspace, gateway)
    path = access(workspace, gateway)
    if path != workspace.vnc_socket:
        _invalidate(workspace)
        workspace.vnc_socket = path
    workspace.endpoint_ready = True
    workspace.save()
    return runtime


def stop(workspace, gateway):
    if workspace.application_launches.filter(state__in=("pending", "uncertain")).exists():
        raise WorkspaceOperationError("Resolve pending application launch actions before stopping the desktop")
    _invalidate(workspace)
    workspace.save()
    register(workspace, gateway)
    if workspace.launch_pending:
        outcome = gateway.cancel_application_launch(workspace.application_name,
            request_id=workspace.launch_request_id, workspace_id=str(workspace.pk))
        if outcome["status"] == "accepted" and outcome.get("runtime_id"):
            runtime = gateway.get_current_runtime(outcome["runtime_id"])
            if runtime is None:
                raise WorkspaceOperationError("Cancelled request runtime cannot be inspected")
            bind(workspace, runtime)
        elif outcome["status"] == "cancelled" and not outcome.get("runtime_id"):
            workspace.launch_pending = False
            workspace.launch_request_id = None
            workspace.save()
        else:
            raise WorkspaceOperationError("Desktop cancellation is unresolved; retain the original request for recovery")
    current = gateway.get_current_runtime(workspace.runtime_id) if workspace.runtime_id else None
    if workspace.runtime_id and current is None:
        raise WorkspaceOperationError("Cannot prove desktop is stopped")
    if current and (current.workspace_id != str(workspace.pk) or current.application_name != workspace.application_name):
        raise WorkspaceOperationError("Desktop runtime binding is inconsistent")
    if current and (not current.terminal or current.cleanup_pending):
        gateway.terminate_application_runtime(current.runtime_id)
        current = gateway.get_current_runtime(current.runtime_id)
        if current is None or not current.terminal or current.cleanup_pending:
            raise WorkspaceOperationError("Desktop termination or cleanup is not yet confirmed")
    return current


def delete(workspace, gateway):
    register(workspace, gateway)
    if WorkspaceApplicationLaunch.objects.filter(workspace=workspace, state__in=("pending", "uncertain")).exists():
        raise WorkspaceOperationError("Resolve pending application launch actions before deleting this workspace")
    if gateway.workspace_dependencies(str(workspace.pk), excluding_runtime=workspace.runtime_id):
        raise WorkspaceOperationError("Stop attached applications and resolve pending operations before deleting")
    workspace.desired_running = False
    workspace.save()
    stop(workspace, gateway)
    # This call serializes with external launch admission. A prior empty query
    # alone never authorizes local deletion.
    gateway.delete_registered_workspace(str(workspace.pk))
    WorkspaceApplicationLaunch.objects.filter(workspace=workspace).delete()
