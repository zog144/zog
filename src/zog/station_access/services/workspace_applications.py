"""Authorized workspace membership and durable launch actions over controller-v1."""
from django.http import Http404
from django.conf import settings
from zog.station_access.models import WorkspaceApplicationLaunch
from zog.station_access.box_control import BoxControlUnavailable
from .authorization import can_access_runtime
from .locks import workspace_lock
from .workspaces import WorkspaceOperationError

LAUNCH_BLOCK = {
    "available": False,
    "code": "workspace_launch_not_supported",
    "reason": "Launching into a workspace is awaiting controller support for shared networking and desktop access.",
}


def application_members(workspace, gateway, user):
    selector = str(workspace.pk) if hasattr(gateway, "workspace_capabilities") else workspace.number
    if hasattr(gateway, "workspace_capabilities") and not workspace.controller_schema:
        return ()
    return tuple(runtime for runtime in gateway.workspace_application_runtimes(selector)
                 if runtime.runtime_id != workspace.runtime_id
                 and runtime.application_name != workspace.application_name
                 and can_access_runtime(user, runtime))


def stop_application(workspace, gateway, user, runtime_id):
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        runtime = next((runtime for runtime in application_members(workspace, gateway, user)
                        if runtime.runtime_id == runtime_id), None)
        if runtime is None:
            raise Http404()
        # Identity is immutable: an application replacement must never change the target.
        observe = getattr(gateway, "get_current_runtime", gateway.get_runtime)
        current = observe(runtime.runtime_id)
        if current is None:
            raise BoxControlUnavailable("Runtime history is unavailable; no stop was submitted")
        if current.runtime_id != runtime.runtime_id or current.application_name != runtime.application_name:
            raise WorkspaceOperationError("Runtime identity changed; no stop was submitted")
        if current.terminal and not current.cleanup_pending:
            return current
        gateway.terminate_application_runtime(runtime.runtime_id)
        observed = observe(runtime.runtime_id)
        if observed is None:
            raise BoxControlUnavailable("Stop submitted but current runtime status is unavailable")
        if observed.runtime_id != runtime.runtime_id or observed.application_name != runtime.application_name:
            raise WorkspaceOperationError("Stop observation does not match the requested runtime")
        return observed


def launch_availability(gateway):
    if not hasattr(gateway, "workspace_capabilities"):
        return LAUNCH_BLOCK
    gateway.require_workspace_contract()
    if not settings.STATION_ACCESS_WORKSPACE_LAUNCH_ENABLED:
        return {"available": False, "code": "workspace_acceptance_pending",
                "reason": "Application launch awaits desktop and authenticated-proxy acceptance on this installation."}
    return {"available": True, "code": "workspace_launch_available",
            "reason": "Launch uses this workspace's desktop and shared host network."}


def launch_application(workspace, gateway, user, *, name, action_id):
    from .authorization import can_access_application
    from .controller_workspaces import register
    if name == workspace.application_name or not can_access_application(user, name):
        raise Http404()
    availability = launch_availability(gateway)
    if not availability["available"]:
        raise WorkspaceOperationError(availability["reason"])
    with workspace_lock(workspace.pk):
        workspace.refresh_from_db()
        action = WorkspaceApplicationLaunch.objects.filter(pk=action_id).first()
        if action:
            if action.workspace_id != workspace.pk or action.application_name != name:
                raise WorkspaceOperationError("Launch action belongs to different intent")
            if action.state == "cancelled":
                raise WorkspaceOperationError("This launch was cancelled; choose a new launch explicitly")
            if action.runtime_id:
                runtime = gateway.get_runtime(action.runtime_id)
                if runtime is None or runtime.workspace_id != str(workspace.pk) or runtime.application_name != name or runtime.request_id != action.request_id:
                    raise WorkspaceOperationError("Accepted runtime evidence is unavailable; no replacement was submitted")
                return action, runtime
        else:
            register(workspace, gateway)
            eligible = next((item for item in gateway.workspace_catalogue() if item['name'] == name), None)
            if not eligible or not eligible.get('eligible') or eligible.get('role') != 'client':
                raise WorkspaceOperationError("Application does not support workspace launch")
            # A visit normally starts the desktop first. Do not nest the same file lock.
            from .controller_workspaces import ready
            workspace.desired_running = True
            workspace.save(update_fields=("desired_running", "updated_at"))
            ready(workspace, gateway)
            preflight = gateway.preflight_workspace_application(name, str(workspace.pk))
            if preflight.get('status') != 'ready-to-attempt':
                raise WorkspaceOperationError("Application preflight is not ready; inspect preparation and desktop readiness")
            if workspace.application_launches.filter(state__in=('pending', 'uncertain')).count() >= 100:
                raise WorkspaceOperationError('Resolve pending launch actions before starting more applications')
            action = WorkspaceApplicationLaunch.objects.create(id=action_id, workspace=workspace,
                application_name=name, request_id=gateway.issue_application_request_id())
        try:
            runtime = gateway.find_application_launch(name, request_id=action.request_id, workspace_id=str(workspace.pk))
            if runtime is None:
                runtime = gateway.launch_application(name, request_id=action.request_id, workspace_id=str(workspace.pk))
            if runtime.workspace_id != str(workspace.pk) or runtime.application_name != name or runtime.request_id != action.request_id:
                raise WorkspaceOperationError("Application launch returned inconsistent identity")
            action.runtime_id = runtime.runtime_id
            action.state = 'accepted'
            action.save()
            return action, runtime
        except Exception:
            # This includes lost replies. Never mint a replacement request on retry.
            action.state = 'uncertain'
            action.save(update_fields=('state', 'updated_at'))
            raise


def launch_actions(workspace, user):
    from .authorization import can_access_application
    return [{"id": str(action.pk), "application": action.application_name,
             "state": action.state, "runtime_id": action.runtime_id or None}
            for action in workspace.application_launches.filter(state__in=('pending', 'uncertain')).order_by('created_at')[:100]
            if can_access_application(user, action.application_name)]


def cancel_launch(workspace, gateway, user, *, action_id):
    from .authorization import can_access_application
    with workspace_lock(workspace.pk):
        action = WorkspaceApplicationLaunch.objects.filter(pk=action_id, workspace=workspace).first()
        if action is None or not can_access_application(user, action.application_name):
            raise Http404()
        if action.state == 'cancelled':
            return 'cancelled'
        outcome = gateway.cancel_application_launch(action.application_name,
            request_id=action.request_id, workspace_id=str(workspace.pk))
        if outcome['status'] == 'cancelled' and not outcome.get('runtime_id'):
            action.state = 'cancelled'
        elif outcome['status'] == 'accepted' and outcome.get('runtime_id'):
            runtime = gateway.get_runtime(outcome['runtime_id'])
            if runtime is None or runtime.workspace_id != str(workspace.pk) or runtime.application_name != action.application_name or runtime.request_id != action.request_id:
                raise WorkspaceOperationError('Accepted launch identity is unavailable')
            action.runtime_id = runtime.runtime_id
            action.state = 'accepted'
        else:
            action.state = 'uncertain'
        action.save()
        return action.state
