from django.contrib import admin
from .models import Host, InventoryScan
@admin.register(Host)
class HostAdmin(admin.ModelAdmin):
    list_display = ("label","provider","instance_id","region","last_received","token_revoked")
    fields = ("label","token_revoked")
    def has_delete_permission(self, request, obj=None): return False
    def has_add_permission(self, request): return False
admin.site.register(InventoryScan)
