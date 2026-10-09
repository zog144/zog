from django.db import IntegrityError
import hmac
import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from zog.station_access.box_control import BoxControlUnavailable, get_gateway
from zog.station_access.models import VncWorkspace
from zog.station_access.services.authorization import (
    accessible_application_names,
    can_access_runtime,
)
from zog.station_access.services.vnc import (
    VncAuthorizationError,
    VncUnavailableError,
    issue_vnc_grant,
    resolve_vnc_target,
)
from zog.station_access.services.workspaces import (
    WorkspaceOperationError,
    ensure_workspace_ready,
    create_workspace,
    update_workspace,
    delete_workspace,
    reconcile_workspace,
    start_workspace,
    stop_workspace,
    workspace_runtime_state,
)
from .serializers import application_json, runtime_json, workspace_json


def _authenticated(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication_required"}, status=401)
    return None


def _gateway_or_response():
    try:
        return get_gateway(), None
    except BoxControlUnavailable as exc:
        return None, JsonResponse(
            {"error": "box_control_unavailable", "detail": str(exc)}, status=503
        )


def _json_payload(request):
    try:
        payload = json.loads(request.body or b"{}")
        if not isinstance(payload, dict):
            return None, JsonResponse({"error": "json_object_required"}, status=400)
        return payload, None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _workspace_for_user(request, workspace_id):
    queryset = VncWorkspace.objects.all()
    if not request.user.is_superuser:
        queryset = queryset.filter(owner=request.user)
    return get_object_or_404(queryset, pk=workspace_id)


@require_GET
@ensure_csrf_cookie
def session(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": request.user.pk,
                "username": request.user.get_username(),
                "is_superuser": request.user.is_superuser,
            },
        }
    )


@require_POST
def login_view(request):
    payload, error = _json_payload(request)
    if error:
        return error
    user = authenticate(
        request,
        username=payload.get("username", ""),
        password=payload.get("password", ""),
    )
    if user is None:
        return JsonResponse({"error": "invalid_credentials"}, status=401)
    login(request, user)
    return JsonResponse(
        {
            "authenticated": True,
            "user": {
                "id": user.pk,
                "username": user.get_username(),
                "is_superuser": user.is_superuser,
            },
        }
    )


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"authenticated": False})


@require_GET
def applications(request):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    allowed = accessible_application_names(request.user)
    values = [
        application_json(application)
        for application in gateway.list_applications()
        if allowed is None or application.name in allowed
    ]
    return JsonResponse({"applications": values})


@require_GET
def runtimes(request):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    values = [
        runtime_json(runtime)
        for runtime in gateway.list_runtimes()
        if can_access_runtime(request.user, runtime)
    ]
    return JsonResponse({"runtimes": values})


@require_GET
def runtime_detail(request, runtime_id: str):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    runtime = gateway.get_runtime(runtime_id)
    if runtime is None or not can_access_runtime(request.user, runtime):
        return JsonResponse({"error": "not_found"}, status=404)
    return JsonResponse({"runtime": runtime_json(runtime)})


@require_GET
def workspaces(request):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    queryset = VncWorkspace.objects.all() if request.user.is_superuser else VncWorkspace.objects.filter(owner=request.user)
    values = []
    for workspace in queryset.order_by("number"):
        try:
            value = workspace_json(workspace, workspace_runtime_state(workspace, gateway) if gateway else None)
        except Exception:
            value = workspace_json(workspace)
            value["status"] = "unknown"
        if gateway is None and (workspace.runtime_id or workspace.launch_pending):
            value["status"] = "unknown"
        values.append(value)
    return JsonResponse({"workspaces": values})


@require_POST
def workspace_create(request):
    denied = _authenticated(request)
    if denied:
        return denied
    payload, error = _json_payload(request)
    if error:
        return error
    name = payload.get("name", "")
    if not name:
        return JsonResponse({"error": "name_required"}, status=400)
    try:
        workspace = create_workspace(owner=request.user, name=name, network=payload.get("network", "default"))
        state = None
    except IntegrityError:
        return JsonResponse({"error": "workspace_name_conflict", "detail": "A workspace with this name already exists."}, status=409)
    except WorkspaceOperationError as exc:
        return JsonResponse({"error": "workspace_configuration", "detail": str(exc)}, status=409)
    except Exception as exc:
        # Desired state/request identity may already be safely persisted. Surface the failure;
        # startup reconciliation can resume it idempotently.
        return JsonResponse({"error": "workspace_launch_failed", "detail": str(exc)}, status=503)
    return JsonResponse({"workspace": workspace_json(workspace, state)}, status=201)


@require_POST
def workspace_start(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    workspace = _workspace_for_user(request, workspace_id)
    try:
        runtime = start_workspace(workspace, gateway)
    except Exception as exc:
        return JsonResponse({"error": "workspace_start_failed", "detail": str(exc)}, status=503)
    return JsonResponse({"workspace": workspace_json(workspace, workspace_runtime_state(workspace, gateway)), "runtime": runtime_json(runtime)})


@require_POST
def workspace_stop(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    workspace = _workspace_for_user(request, workspace_id)
    try:
        stop_workspace(workspace, gateway)
    except Exception as exc:
        return JsonResponse({"error": "workspace_stop_failed", "detail": str(exc)}, status=503)
    workspace.refresh_from_db()
    return JsonResponse({"workspace": workspace_json(workspace, workspace_runtime_state(workspace, gateway))})


@require_POST
def workspace_reconcile(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    workspace = _workspace_for_user(request, workspace_id)
    try:
        state = reconcile_workspace(workspace, gateway)
    except Exception as exc:
        return JsonResponse({"error": "workspace_reconcile_failed", "detail": str(exc)}, status=503)
    workspace.refresh_from_db()
    return JsonResponse({"workspace": workspace_json(workspace, state)})


@require_POST
def workspace_vnc_grant(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    workspace = _workspace_for_user(request, workspace_id)
    try:
        ensure_workspace_ready(workspace, gateway)
        grant = issue_vnc_grant(request.user, workspace, gateway)
    except VncAuthorizationError:
        return JsonResponse({"error": "not_found"}, status=404)
    except (VncUnavailableError, WorkspaceOperationError) as exc:
        return JsonResponse({"error": "vnc_unavailable", "detail": str(exc)}, status=409)
    except Exception as exc:
        return JsonResponse({"error": "workspace_unavailable", "detail": str(exc)}, status=503)
    return JsonResponse(
        {
            "token": grant.token,
            "expires_at": grant.expires_at,
            "novnc_url": grant.novnc_url,
        },
        status=201,
    )


@require_GET
def websockify_target(request, secret: str):
    # JSONTokenApi cannot attach arbitrary headers, so websockify receives a private
    # configured URL containing this server-side secret. Production reverse proxies
    # should not publish /internal at all; the secret is defense in depth.
    if not hmac.compare_digest(
        secret, settings.STATION_ACCESS_WEBSOCKIFY_RESOLUTION_SECRET
    ):
        return JsonResponse({"error": "not_found"}, status=404)
    token = request.GET.get("token", "")
    if not token:
        return JsonResponse({"error": "not_found"}, status=404)
    gateway, error = _gateway_or_response()
    if error:
        return error
    target = resolve_vnc_target(token, gateway)
    if target is None:
        return JsonResponse({"error": "not_found"}, status=404)
    host, port = target
    return JsonResponse({"host": host, "port": port})


@require_GET
def runtime_logs(request, runtime_id):
    from dataclasses import asdict
    from zog.station_access.box_control.logs import LogsUnavailable, LogCursorExpired, validate_page
    denied = _authenticated(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    runtime = gateway.get_runtime(runtime_id)
    if runtime is None or not can_access_runtime(request.user, runtime):
        return JsonResponse({"error": "not_found"}, status=404)
    program = request.GET.get("program") or None
    if program and program not in {p.name for p in runtime.programs}:
        return JsonResponse({"error": "not_found"}, status=404)
    cursor = request.GET.get("cursor") or None
    try:
        limit = int(request.GET.get("limit", "50"))
        if not 1 <= limit <= 100 or (cursor and len(cursor) > 4096):
            raise ValueError()
    except ValueError:
        return JsonResponse({"error": "invalid_log_query"}, status=400)
    try:
        page = validate_page(gateway.read_logs(runtime_id, program=program, cursor=cursor, limit=limit), runtime, limit)
        if program and any(entry.program != program for entry in page.entries):
            raise LogsUnavailable("log adapter returned a different program")
    except LogCursorExpired as exc:
        return JsonResponse({"error": "log_cursor_expired", "detail": str(exc)}, status=410)
    except (LogsUnavailable, BoxControlUnavailable) as exc:
        return JsonResponse({"error": "logs_unavailable", "detail": str(exc)}, status=503)
    response = JsonResponse(asdict(page))
    response["Cache-Control"] = "no-store"
    return response


def _build_administrator(request):
    denied = _authenticated(request)
    if denied:
        return denied
    if not request.user.is_superuser:
        return JsonResponse({'error': 'not_found'}, status=404)
    return None


@require_GET
def build_jobs(request):
    denied = _build_administrator(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        result = gateway.list_build_jobs(after=request.GET.get('after') or None, limit=50)
    except Exception as exc:
        return JsonResponse({'error': 'builds_unavailable', 'detail': str(exc)}, status=503)
    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def build_job_detail(request, job_id):
    denied = _build_administrator(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        record = gateway.get_build_job(job_id)
    except Exception:
        return JsonResponse({'error': 'not_found'}, status=404)
    keys = ('job_id', 'runtime_id', 'state', 'outcome', 'exit_code', 'signal',
            'process_cleanup_complete', 'resources_released', 'invocation_id', 'boot_id')
    return JsonResponse({'job': {key: record.get(key) for key in keys}})


@require_GET
def build_job_logs(request, job_id):
    from dataclasses import asdict
    from zog.station_access.box_control.logs import LogsUnavailable, LogCursorExpired, validate_page
    from zog.station_access.box_control.types import RuntimeSummary, ProgramSummary
    denied = _build_administrator(request)
    if denied:
        return denied
    gateway, error = _gateway_or_response()
    if error:
        return error
    cursor = request.GET.get('cursor') or None
    try:
        limit = int(request.GET.get('limit', '50'))
        if not 1 <= limit <= 100 or (cursor and len(cursor) > 4096):
            raise ValueError()
    except ValueError:
        return JsonResponse({'error': 'invalid_log_query'}, status=400)
    try:
        record = gateway.get_build_job(job_id)
    except Exception:
        return JsonResponse({'error': 'not_found'}, status=404)
    runtime = RuntimeSummary(job_id, 'build-job', job_id, record['state'],
        programs=(ProgramSummary('build-command', '', record['state'], invocation_id=record.get('invocation_id')),))
    try:
        page = validate_page(gateway.read_build_logs(job_id, cursor=cursor, limit=limit), runtime, limit)
    except LogCursorExpired as exc:
        return JsonResponse({'error': 'log_cursor_expired', 'detail': str(exc)}, status=410)
    except (LogsUnavailable, BoxControlUnavailable) as exc:
        return JsonResponse({'error': 'logs_unavailable', 'detail': str(exc)}, status=503)
    response = JsonResponse(asdict(page))
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def workspace_provenance(request, workspace_id):
    from zog.station_access.services.workspace_provenance import workspace_provenance as provenance
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        value = provenance(workspace, gateway, request.user)
    except Exception:
        return JsonResponse({
            "error": "workspace_provenance_unavailable",
            "detail": "Workspace provenance is temporarily unavailable. No current application specification was substituted.",
        }, status=503)
    response = JsonResponse(value)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def workspace_detail(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    return JsonResponse({"workspace": workspace_json(_workspace_for_user(request, workspace_id))})


@require_POST
def workspace_update(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    payload, error = _json_payload(request)
    if error:
        return error
    try:
        update_workspace(workspace, name=payload.get("name"), network=payload.get("network"), revision=payload.get("revision"))
    except IntegrityError:
        return JsonResponse({"error": "workspace_name_conflict", "detail": "A workspace with this name already exists."}, status=409)
    except WorkspaceOperationError as exc:
        return JsonResponse({"error": "workspace_update_failed", "detail": str(exc)}, status=409)
    return JsonResponse({"workspace": workspace_json(workspace)})


@require_POST
def workspace_delete(request, workspace_id):
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    payload, error = _json_payload(request)
    if error:
        return error
    if payload.get("confirmed_workspace_id") != str(workspace.pk):
        return JsonResponse({"error": "workspace_confirmation_required"}, status=400)
    gateway, _ = _gateway_or_response()
    try:
        delete_workspace(workspace, gateway, revision=payload.get("revision"))
    except Exception as exc:
        return JsonResponse({"error": "workspace_delete_failed", "detail": str(exc)}, status=409)
    return JsonResponse({"deleted": True})


@require_GET
def workspace_applications(request, workspace_id):
    from zog.station_access.services.workspace_applications import application_members, launch_availability, launch_actions
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    gateway, error = _gateway_or_response()
    if error:
        return error
    allowed = accessible_application_names(request.user)
    try:
        catalogue = [application_json(application) for application in gateway.list_applications()
                     if application.name != workspace.application_name
                     and (allowed is None or application.name in allowed)]
        members = [runtime_json(runtime) for runtime in application_members(workspace, gateway, request.user)]
        availability = launch_availability(gateway)
        authoritative = hasattr(gateway, "workspace_capabilities") and bool(workspace.controller_schema)
        claims = []
        if hasattr(gateway, "workspace_capabilities"):
            eligibility = {item['name']: item for item in gateway.workspace_catalogue()}
            for application in catalogue:
                item = eligibility.get(application['name'], {})
                application.update(eligible=item.get('eligible', False), reason=item.get('reason') or 'workspace-required')
            if authoritative:
                # Ownership claims are visible only as aggregate counts: they can
                # include another user's applications and private operation IDs.
                claims = gateway.workspace_membership(str(workspace.pk))
    except Exception:
        return JsonResponse({"error": "workspace_applications_unavailable", "detail": "Application information is temporarily unavailable. Retry without starting another application."}, status=503)
    response = JsonResponse({"workspace": workspace_json(workspace), "applications": catalogue,
        "runtimes": members, "launch": availability,
        "launch_actions": launch_actions(workspace, request.user),
        "membership": {"source": "controller" if authoritative else "recorded_launch_parameters",
                       "authoritative": authoritative,
                       "pending_count": sum(item['kind'] != 'runtime' for item in claims),
                       "cleanup_count": sum(bool(item.get('cleanup_pending')) and item.get('state') in ('failed', 'terminated') for item in claims)},
        "state_source": "recorded"})
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def workspace_application_launch(request, workspace_id):
    from zog.station_access.services.authorization import can_access_application
    from zog.station_access.services.workspace_applications import launch_availability, launch_application
    from uuid import UUID
    from django.http import Http404
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    payload, error = _json_payload(request)
    if error:
        return error
    name = payload.get('application')
    if not isinstance(name, str) or not name or len(name) > 255:
        return JsonResponse({'error': 'invalid_application'}, status=400)
    if name == workspace.application_name or not can_access_application(request.user, name):
        return JsonResponse({'error': 'not_found'}, status=404)
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        availability = launch_availability(gateway)
        if not availability['available']:
            return JsonResponse({'error': availability['code'], 'detail': availability['reason']}, status=409)
        action_id = payload.get('action_id')
        if str(UUID(action_id)) != action_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'invalid_launch_action'}, status=400)
    except Exception:
        return JsonResponse({'error': 'workspace_controller_unavailable'}, status=503)
    try:
        action, runtime = launch_application(workspace, gateway, request.user, name=name, action_id=action_id)
    except Http404:
        raise
    except WorkspaceOperationError as exc:
        return JsonResponse({'error': 'workspace_launch_blocked', 'detail': str(exc), 'action_id': action_id}, status=409)
    except Exception:
        return JsonResponse({'error': 'workspace_launch_unconfirmed',
            'detail': 'Launch outcome is unresolved. Retry this same action; do not start a replacement.', 'action_id': action_id}, status=503)
    response = JsonResponse({'action_id': str(action.pk), 'runtime': runtime_json(runtime)}, status=200)
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def workspace_application_stop(request, workspace_id, runtime_id):
    from django.http import Http404
    from zog.station_access.services.workspace_applications import stop_application
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    payload, error = _json_payload(request)
    if error:
        return error
    if payload.get('confirmed_runtime_id') != runtime_id:
        return JsonResponse({'error': 'runtime_confirmation_required'}, status=400)
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        runtime = stop_application(workspace, gateway, request.user, runtime_id)
    except Http404:
        raise
    except Exception:
        return JsonResponse({'error': 'workspace_application_stop_unconfirmed', 'detail': 'Could not confirm application termination. Refresh its status before retrying.'}, status=503)
    response = JsonResponse({'runtime': runtime_json(runtime), 'stopped': runtime.terminal and not runtime.cleanup_pending})
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def workspace_application_cancel(request, workspace_id, action_id):
    from django.http import Http404
    from zog.station_access.services.workspace_applications import cancel_launch
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    payload, error = _json_payload(request)
    if error:
        return error
    if payload.get('confirmed_action_id') != str(action_id):
        return JsonResponse({'error':'launch_confirmation_required'}, status=400)
    gateway, error = _gateway_or_response()
    if error:
        return error
    try:
        state = cancel_launch(workspace, gateway, request.user, action_id=action_id)
    except Http404:
        raise
    except Exception:
        return JsonResponse({'error':'workspace_cancellation_unconfirmed', 'detail':'Cancellation remains unresolved. Keep the original launch action for inspection or retry.'}, status=503)
    response = JsonResponse({'action_id':str(action_id), 'state':state})
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def workspace_readiness(request, workspace_id):
    from zog.station_access.services.workspace_readiness import inspect, preflight
    from zog.station_access.services.authorization import can_access_application
    denied = _authenticated(request)
    if denied:
        return denied
    workspace = _workspace_for_user(request, workspace_id)
    application = request.GET.get("application")
    if application is not None and (not application or len(application) > 255 or
            (application != workspace.application_name and not can_access_application(request.user, application))):
        return JsonResponse({"error": "not_found"}, status=404)
    try:
        gateway = get_gateway()
    except Exception:
        gateway = None
    data = preflight(workspace, gateway, application) if application is not None else inspect(workspace, gateway, request.user)
    response = JsonResponse(data)
    response["Cache-Control"] = "no-store"
    return response
