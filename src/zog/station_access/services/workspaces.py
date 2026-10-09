from __future__ import annotations
from dataclasses import dataclass
import logging
import socket
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from zog.station_access.models import VncAccessGrant, VncWorkspace, WorkspaceNumberSequence
from .locks import workspace_lock

logger = logging.getLogger(__name__)

class WorkspaceOperationError(RuntimeError):
    pass

@dataclass(frozen=True)
class WorkspaceRuntimeState:
    runtime: object | None
    status: str

def _revoke_grants(workspace):
    VncAccessGrant.objects.filter(workspace=workspace, revoked_at__isnull=True).update(revoked_at=timezone.now())

def _invalidate(workspace):
    _revoke_grants(workspace)
    workspace.endpoint_ready = False
    workspace.endpoint_revision += 1

def workspace_runtime_state(workspace, gateway):
    runtime = getattr(gateway, "get_current_runtime", gateway.get_runtime)(workspace.runtime_id) if workspace.runtime_id else None
    if workspace.last_error:
        status = "fault"
    elif workspace.launch_pending:
        status = "launch-pending" if workspace.desired_running else "stopping"
    elif not workspace.desired_running:
        status = "stopping" if runtime and not runtime.terminal else "stopped"
    elif runtime is None or runtime.terminal:
        status = "launch-pending"
    else:
        status = "running" if workspace.endpoint_ready else "display-starting"
    return WorkspaceRuntimeState(runtime, status)

def validate_workspace_fields(name, network):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        raise WorkspaceOperationError("Workspace name must contain 1–255 characters")
    if network != "default":
        raise WorkspaceOperationError("Only Default — shared host network is supported")


def create_workspace(*, owner, name, gateway=None, network="default"):
    validate_workspace_fields(name, network)
    with workspace_lock("allocation"), transaction.atomic():
        number = (VncWorkspace.objects.aggregate(value=Max("number"))["value"] or 0) + 1
        sequence, _ = WorkspaceNumberSequence.objects.get_or_create(pk=1, defaults={"next_number": number})
        number = max(number, sequence.next_number)
        if number > 9999:
            raise WorkspaceOperationError("Controller workspace number range is exhausted")
        sequence.next_number = number + 1
        sequence.save()
        return VncWorkspace.objects.create(owner=owner, name=name.strip(), network=network,
            number=number, application_name=settings.STATION_ACCESS_VNC_APPLICATION_NAME)

def _allocate(workspace):
    if workspace.display_number is not None:
        return
    with workspace_lock("allocation"), transaction.atomic():
        used = set(VncWorkspace.objects.exclude(display_number=None).values_list("display_number", flat=True))
        occupied_ports = set(VncWorkspace.objects.filter(vnc_host=settings.STATION_ACCESS_VNC_HOST).exclude(vnc_port=None).values_list("vnc_port", flat=True))
        display = next((n for n in range(settings.STATION_ACCESS_DISPLAY_MINIMUM, settings.STATION_ACCESS_DISPLAY_MAXIMUM + 1)
            if n not in used and settings.STATION_ACCESS_VNC_PORT_BASE + n not in occupied_ports), None)
        if display is None:
            raise WorkspaceOperationError("workspace display allocation exhausted")
        port = settings.STATION_ACCESS_VNC_PORT_BASE + display
        if not 1 <= port <= 65535:
            raise WorkspaceOperationError("invalid configured VNC port range")
        workspace.display_number = display
        workspace.vnc_host = settings.STATION_ACCESS_VNC_HOST
        workspace.vnc_port = port
        workspace.launch_parameters = {"workspace-number": workspace.number,
            "display-number": display, "vnc-port": port}
        _invalidate(workspace)
        workspace.save()

def _contract(workspace, gateway):
    application = next((a for a in gateway.list_applications() if a.name == workspace.application_name), None)
    if not application or not application.multi_instance or application.start_policy != "externally-controlled":
        raise WorkspaceOperationError("VNC application must be declared, multi-instance, and externally-controlled")

def _bind_runtime(workspace, runtime):
    if runtime.application_name != workspace.application_name or runtime.request_id != workspace.launch_request_id:
        raise WorkspaceOperationError("controller returned an inconsistent workspace runtime")
    workspace.runtime_id, workspace.instance_id = runtime.runtime_id, runtime.instance_id
    workspace.launch_pending = False
    workspace.save()

def _ensure(workspace, gateway):
    if hasattr(gateway, "workspace_capabilities"):
        from .controller_workspaces import ensure
        return ensure(workspace, gateway)
    _contract(workspace, gateway)
    if workspace.launch_pending and not workspace.launch_parameters:
        raise WorkspaceOperationError("legacy pending launch requires explicit recovery with its original parameters")
    current = getattr(gateway, "get_current_runtime", gateway.get_runtime)(workspace.runtime_id) if workspace.runtime_id else None
    if current and not current.terminal:
        return current
    _allocate(workspace)
    if workspace.runtime_id and current is None:
        raise WorkspaceOperationError("bound runtime is missing; inspect controller history before replacing it")
    if workspace.launch_pending:
        runtime = gateway.find_application_launch(workspace.application_name,
            request_id=workspace.launch_request_id, parameters=workspace.launch_parameters)
        if runtime is None:
            runtime = gateway.launch_application(workspace.application_name,
                request_id=workspace.launch_request_id, parameters=workspace.launch_parameters)
        _bind_runtime(workspace, runtime)
        if runtime.terminal:
            raise WorkspaceOperationError("recovered launch already ended; reconcile again to create a new runtime")
        return runtime
    if workspace.launch_request_id and not workspace.runtime_id:
        raise WorkspaceOperationError("launch identity has no runtime evidence; manual recovery required")
    checker = getattr(gateway, "assert_endpoint_available", assert_endpoint_available)
    checker(workspace.vnc_host, workspace.vnc_port)
    workspace.launch_request_id = gateway.issue_application_request_id()
    workspace.runtime_id = workspace.instance_id = None
    workspace.launch_pending = True
    _invalidate(workspace)
    workspace.save()  # commit before calling box-control; no encompassing DB transaction
    runtime = gateway.launch_application(workspace.application_name,
        request_id=workspace.launch_request_id, parameters=workspace.launch_parameters)
    _bind_runtime(workspace, runtime)
    if runtime.terminal:
        raise WorkspaceOperationError("workspace server exited during launch")
    return runtime

def _stop(workspace, gateway):
    if hasattr(gateway, "workspace_capabilities"):
        from .controller_workspaces import stop
        return stop(workspace, gateway)
    _invalidate(workspace)
    workspace.save()
    if workspace.launch_pending:
        runtime = gateway.cancel_application_launch(workspace.application_name,
            request_id=workspace.launch_request_id, parameters=workspace.launch_parameters)
        if runtime:
            _bind_runtime(workspace, runtime)
        else:
            workspace.launch_pending = False
            workspace.launch_request_id = None
            workspace.save()
    current = getattr(gateway, "get_current_runtime", gateway.get_runtime)(workspace.runtime_id) if workspace.runtime_id else None
    if current is not None and not current.terminal:
        return gateway.terminate_application_runtime(current.runtime_id)
    _allocate(workspace)
    if workspace.runtime_id and current is None:
        raise WorkspaceOperationError("cannot prove missing runtime is stopped")
    return current

def _operate(workspace, gateway, desired=None):
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        if desired is not None:
            workspace.desired_running = desired
        workspace.last_error = ""
        workspace.save()
        try:
            return _ensure(workspace, gateway) if workspace.desired_running else _stop(workspace, gateway)
        except Exception as exc:
            logger.exception("Workspace operation failed", extra={"workspace_id": str(workspace.pk), "request_id": workspace.launch_request_id})
            VncWorkspace.objects.filter(pk=workspace.pk).update(last_error=str(exc), endpoint_ready=False)
            workspace.refresh_from_db()
            raise

def start_workspace(workspace, gateway):
    return _operate(workspace, gateway, True)

def stop_workspace(workspace, gateway):
    return _operate(workspace, gateway, False)

def reconcile_workspace(workspace, gateway):
    _operate(workspace, gateway)
    return workspace_runtime_state(workspace, gateway)

def reconcile_all_workspaces(gateway):
    results = []
    for workspace in VncWorkspace.objects.order_by("number"):
        try:
            state = reconcile_workspace(workspace, gateway)
        except Exception:
            state = WorkspaceRuntimeState(None, "fault")
        results.append((workspace, state))
    return results

def assert_endpoint_available(host, port):
    # Detect a pre-existing listener before assigning a new launch identity. The server
    # must still fail on bind conflict; this preflight is not a socket reservation.
    try:
        with socket.create_connection((host, port), timeout=1):
            raise WorkspaceOperationError("reserved VNC endpoint already has a listener; refusing launch")
    except ConnectionRefusedError:
        return


def probe_display(host, port):
    # RFB banner, bounded total read; TCP connect alone is not display readiness.
    with socket.create_connection((host, port), timeout=1) as connection:
        connection.settimeout(1)
        banner = connection.recv(12, socket.MSG_WAITALL)
        return len(banner) == 12 and banner.startswith(b"RFB ") and banner.endswith(b"\n")

def ensure_workspace_ready(workspace, gateway):
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        workspace.desired_running = True
        workspace.last_error = ""
        workspace.save()
        try:
            if hasattr(gateway, "workspace_capabilities"):
                from .controller_workspaces import ready as controller_ready
                return controller_ready(workspace, gateway)
            runtime = _ensure(workspace, gateway)
            ready = getattr(gateway, "workspace_ready", probe_display)(workspace.vnc_host, workspace.vnc_port)
            workspace.endpoint_ready = bool(ready)
            workspace.save(update_fields=("endpoint_ready", "updated_at"))
        except OSError:
            workspace.endpoint_ready = False
            workspace.save(update_fields=("endpoint_ready", "updated_at"))
        except Exception as exc:
            logger.exception("Workspace first-use failed", extra={"workspace_id": str(workspace.pk), "request_id": workspace.launch_request_id})
            VncWorkspace.objects.filter(pk=workspace.pk).update(last_error=str(exc), endpoint_ready=False)
            raise
        if not workspace.endpoint_ready:
            raise WorkspaceOperationError("Display is starting or unavailable; retry shortly")
        return runtime

def require_workspace_number(*, user, number, gateway):
    # Shared entry point for future application launch flows; never accepts raw DISPLAY.
    query = VncWorkspace.objects.filter(number=number)
    if not user.is_superuser:
        query = query.filter(owner=user)
    workspace = query.get()
    ensure_workspace_ready(workspace, gateway)
    return workspace

def bind_workspace_endpoint(workspace, *, host, port):
    # Administrative integration helper; never browser-controlled.
    if (host is None) != (port is None) or (port is not None and not 1 <= port <= 65535):
        raise WorkspaceOperationError("invalid endpoint")
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        if (workspace.vnc_host, workspace.vnc_port) != (host, port):
            _invalidate(workspace)
            workspace.vnc_host, workspace.vnc_port = host, port
            workspace.save()


def update_workspace(workspace, *, name, network, revision):
    validate_workspace_fields(name, network)
    with workspace_lock(workspace.pk), transaction.atomic():
        workspace.refresh_from_db()
        if revision != workspace.updated_at.isoformat():
            raise WorkspaceOperationError("Workspace changed. Reload before saving.")
        workspace.name, workspace.network = name.strip(), network
        workspace.save(update_fields=("name", "network", "updated_at"))
    return workspace


def delete_workspace(workspace, gateway, *, revision):
    # Shared with start/readiness locks: never delete between recording a launch and
    # binding its runtime. Controller calls must not run inside a database transaction.
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        if revision != workspace.updated_at.isoformat():
            raise WorkspaceOperationError("Workspace changed. Reload before deleting.")
        try:
            if gateway is None:
                raise WorkspaceOperationError("Controller unavailable; cannot verify workspace ownership claims")
            if hasattr(gateway, "workspace_capabilities"):
                from .controller_workspaces import delete
                delete(workspace, gateway)
                with transaction.atomic():
                    _revoke_grants(workspace)
                    workspace.delete()
                return
            if workspace.controller_schema:
                raise WorkspaceOperationError("Controller unavailable; cannot delete a registered workspace")
            has_launch = bool(workspace.launch_request_id or workspace.runtime_id or workspace.launch_pending)
            if has_launch:
                if gateway is None:
                    raise WorkspaceOperationError("Controller unavailable; cannot prove the workspace is safe to delete")
                if workspace.launch_pending and not workspace.runtime_id:
                    recovered = gateway.find_application_launch(workspace.application_name,
                        request_id=workspace.launch_request_id, parameters=workspace.launch_parameters)
                    if recovered is not None:
                        _bind_runtime(workspace, recovered)
                dependencies = gateway.workspace_dependencies(workspace.number, excluding_runtime=workspace.runtime_id)
                if dependencies:
                    raise WorkspaceOperationError("Stop attached applications before deleting: " + ", ".join(dependencies))
                workspace.desired_running = False
                workspace.last_error = ""
                workspace.save()
                _stop(workspace, gateway)
                current = getattr(gateway, "get_current_runtime", gateway.get_runtime)(workspace.runtime_id) if workspace.runtime_id else None
                if workspace.launch_pending or (workspace.runtime_id and (current is None or not current.terminal)):
                    raise WorkspaceOperationError("Desktop termination is not yet confirmed. Retry after it stops.")
            with transaction.atomic():
                _revoke_grants(workspace)
                workspace.delete()
        except Exception as exc:
            VncWorkspace.objects.filter(pk=workspace.pk).update(last_error=str(exc), endpoint_ready=False)
            raise
