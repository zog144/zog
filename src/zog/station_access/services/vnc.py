import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

from zog.station_access.box_control.port import BoxControlGateway
from zog.station_access.models import VncAccessGrant, VncWorkspace


class VncAuthorizationError(PermissionError):
    pass


class VncUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class IssuedVncGrant:
    token: str
    expires_at: str
    novnc_url: str


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_vnc_grant(
    user, workspace: VncWorkspace, gateway: BoxControlGateway
) -> IssuedVncGrant:
    if not user.is_superuser and workspace.owner_id != user.pk:
        raise VncAuthorizationError("workspace is not owned by this user")
    workspace.refresh_from_db()
    if not user.is_active:
        raise VncAuthorizationError("user is inactive")
    if not workspace.desired_running or not workspace.runtime_id:
        raise VncUnavailableError("workspace is not running")
    runtime = getattr(gateway, "get_current_runtime", gateway.get_runtime)(workspace.runtime_id)
    if runtime is None or runtime.terminal:
        raise VncUnavailableError("workspace runtime is not active")
    if runtime.application_name != workspace.application_name:
        raise VncUnavailableError("workspace/runtime binding is inconsistent")
    if not workspace.endpoint_ready:
        raise VncUnavailableError("workspace display is not ready")
    if workspace.controller_schema:
        from .controller_workspaces import access
        if access(workspace, gateway) != workspace.vnc_socket:
            raise VncUnavailableError("Desktop endpoint changed; request a new grant")
    elif not workspace.vnc_host or workspace.vnc_port is None:
        raise VncUnavailableError("workspace VNC endpoint is not bound yet")
    if not workspace.controller_schema and not 1 <= int(workspace.vnc_port) <= 65535:
        raise VncUnavailableError("workspace has an invalid VNC port")

    now = timezone.now()
    VncAccessGrant.objects.filter(expires_at__lt=now - timedelta(minutes=5)).delete()

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=settings.STATION_ACCESS_VNC_TOKEN_TTL_SECONDS)
    VncAccessGrant.objects.create(
        token_digest=_digest(token),
        user=user,
        workspace=workspace,
        runtime_id=runtime.runtime_id,
        endpoint_revision=workspace.endpoint_revision,
        target_host=workspace.vnc_host or "",
        target_socket=workspace.vnc_socket,
        target_port=workspace.vnc_port,
        expires_at=expires_at,
    )

    websocket_path = f"{settings.STATION_ACCESS_WEBSOCKIFY_PATH}?{urlencode({'token': token})}"
    novnc_query = urlencode({"autoconnect": "1", "resize": "scale", "path": websocket_path})
    return IssuedVncGrant(
        token=token,
        expires_at=expires_at.isoformat(),
        novnc_url=f"{settings.STATION_ACCESS_NOVNC_PATH}?{novnc_query}",
    )


def resolve_vnc_target(token: str, gateway: BoxControlGateway):
    now = timezone.now()
    try:
        grant = VncAccessGrant.objects.select_related("workspace", "workspace__owner", "user").get(
            token_digest=_digest(token)
        )
    except VncAccessGrant.DoesNotExist:
        return None

    workspace = grant.workspace
    if grant.revoked_at is not None or grant.expires_at <= now:
        return None
    if not workspace.endpoint_ready or not workspace.desired_running or workspace.runtime_id != grant.runtime_id:
        return None
    if not grant.user.is_active or (workspace.owner_id != grant.user_id and not grant.user.is_superuser):
        return None
    if workspace.endpoint_revision != grant.endpoint_revision:
        return None
    if (workspace.vnc_host or "") != grant.target_host or workspace.vnc_port != grant.target_port or workspace.vnc_socket != grant.target_socket:
        return None
    runtime = getattr(gateway, "get_current_runtime", gateway.get_runtime)(grant.runtime_id)
    if runtime is None or runtime.terminal:
        return None
    if runtime.application_name != workspace.application_name:
        return None
    if workspace.controller_schema:
        from .controller_workspaces import access
        try:
            if access(workspace, gateway) != grant.target_socket:
                return None
        except Exception:
            return None
        return "unix_socket", grant.target_socket
    return grant.target_host, grant.target_port
