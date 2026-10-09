import uuid

from django.conf import settings
from django.db import models


class ApplicationOwnership(models.Model):
    """Station-access authorization boundary for an ordinary declarative Zog application."""

    application_name = models.CharField(max_length=255, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_zog_applications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("application_name",)

    def __str__(self) -> str:
        return f"{self.application_name} -> {self.owner}"


class RuntimePresentation(models.Model):
    """Mutable station-access presentation data; never a declarative application definition."""

    runtime_id = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)


class VncWorkspace(models.Model):
    """User-owned desired state for one VNC application instance.

    box-control owns the actual application runtime and systemd services.  station-access
    persists its controller-issued request id before launch so repeating reconciliation after
    a crash cannot accidentally create an additional multi-instance runtime.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vnc_workspaces",
        null=True, blank=True,
    )
    name = models.CharField(max_length=255)
    application_name = models.CharField(max_length=255)
    number = models.PositiveIntegerField(unique=True)
    network = models.CharField(max_length=64, default="default")
    desired_running = models.BooleanField(default=False)
    launch_pending = models.BooleanField(default=False)
    display_number = models.PositiveIntegerField(null=True, blank=True, unique=True)
    launch_parameters = models.JSONField(default=dict, blank=True)
    endpoint_ready = models.BooleanField(default=False)
    controller_schema = models.CharField(max_length=64, blank=True)
    vnc_socket = models.CharField(max_length=4096, blank=True)

    launch_request_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    runtime_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    instance_id = models.CharField(max_length=255, null=True, blank=True)

    # This binding is intentionally explicit.  Current box-control does not yet expose a
    # per-instance launch overlay or VNC endpoint discovery contract.
    vnc_host = models.CharField(max_length=255, null=True, blank=True)
    vnc_port = models.PositiveIntegerField(null=True, blank=True)
    endpoint_revision = models.PositiveIntegerField(default=0)

    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("owner", "name"), name="unique_workspace_name_per_owner"),
            models.UniqueConstraint(fields=("vnc_host", "vnc_port"), name="unique_workspace_endpoint"),
        ]

    def __str__(self) -> str:
        return f"{self.owner}: {self.name}"


class VncAccessGrant(models.Model):
    """Short-lived bearer capability used only for websockify target resolution.

    The raw token is returned once to the browser and is never persisted. Only its SHA-256
    digest is stored, limiting credential disclosure from the Django database.
    """

    token_digest = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vnc_access_grants"
    )
    workspace = models.ForeignKey(
        VncWorkspace, on_delete=models.CASCADE, related_name="access_grants"
    )
    runtime_id = models.CharField(max_length=255, db_index=True)
    endpoint_revision = models.PositiveIntegerField()
    target_host = models.CharField(max_length=255)
    target_port = models.PositiveIntegerField(null=True, blank=True)
    target_socket = models.CharField(max_length=4096, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=("runtime_id", "expires_at"), name="station_acc_runtime_3f40fd_idx")]


class WorkspaceNumberSequence(models.Model):
    """Never reuse a deleted workspace number for an unrelated graphical seat."""
    next_number = models.PositiveIntegerField(default=2)


class WorkspaceApplicationLaunch(models.Model):
    """Durable browser action identity; controller retains authoritative execution intent."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(VncWorkspace, on_delete=models.PROTECT, related_name="application_launches")
    application_name = models.CharField(max_length=255)
    request_id = models.CharField(max_length=255, unique=True)
    runtime_id = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=32, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
