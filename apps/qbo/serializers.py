from rest_framework import serializers

from apps.qbo.models import QBOSyncLog


class QBOSyncLogSerializer(serializers.ModelSerializer):
    """Read-only row for the Settings → QBO Log table."""
    triggered_by_name = serializers.SerializerMethodField()

    class Meta:
        model = QBOSyncLog
        fields = [
            'id', 'entity_type', 'entity_id', 'qbo_entity_type', 'qbo_entity_id',
            'action', 'status', 'error_message', 'synced_at', 'triggered_by_name',
        ]
        read_only_fields = fields

    def get_triggered_by_name(self, obj):
        user = obj.triggered_by
        if user is None:
            return None
        return user.get_full_name() or user.username
