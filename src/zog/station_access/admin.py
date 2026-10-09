from django.contrib import admin

from .models import ApplicationOwnership, RuntimePresentation, VncAccessGrant, VncWorkspace
from .services.workspaces import bind_workspace_endpoint


@admin.register(ApplicationOwnership)
class ApplicationOwnershipAdmin(admin.ModelAdmin):
    list_display = ("application_name", "owner", "updated_at")
    search_fields = ("application_name", "owner__username")


@admin.register(RuntimePresentation)
class RuntimePresentationAdmin(admin.ModelAdmin):
    list_display = ("runtime_id", "display_name", "changed_by", "updated_at")
    search_fields = ("runtime_id", "display_name")


@admin.register(VncWorkspace)
class VncWorkspaceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "desired_running",
        "runtime_id",
        "instance_id",
        "vnc_host",
        "vnc_port",
        "updated_at",
    )
    list_filter = ("desired_running", "application_name")
    search_fields = ("name", "owner__username", "runtime_id", "instance_id")
    readonly_fields = (
        "number", "application_name", "desired_running", "launch_pending", "display_number",
        "launch_parameters", "launch_request_id", "runtime_id", "instance_id", "vnc_host", "vnc_port",
        "endpoint_revision", "endpoint_ready", "last_error", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VncAccessGrant)
class VncAccessGrantAdmin(admin.ModelAdmin):
    list_display = (
        "workspace",
        "runtime_id",
        "user",
        "created_at",
        "expires_at",
        "revoked_at",
    )
    readonly_fields = (
        "token_digest",
        "workspace",
        "runtime_id",
        "endpoint_revision",
        "target_host",
        "target_port",
        "user",
        "created_at",
        "expires_at",
        "revoked_at",
    )
    search_fields = ("workspace__name", "runtime_id", "user__username")
