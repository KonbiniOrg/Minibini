from django.contrib import admin
from .models import QBOConnection, QBOSyncLog


@admin.register(QBOConnection)
class QBOConnectionAdmin(admin.ModelAdmin):
    list_display = ['realm_id', 'is_active', 'connected_at', 'last_sync_at']
    readonly_fields = ['access_token', 'refresh_token']


@admin.register(QBOSyncLog)
class QBOSyncLogAdmin(admin.ModelAdmin):
    list_display = ['entity_type', 'entity_id', 'qbo_entity_type', 'action', 'status', 'synced_at']
    list_filter = ['entity_type', 'action', 'status']
    ordering = ['-synced_at']
