from rest_framework import serializers
from apps.core.models import HistoryEntry


class HistoryEntrySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = HistoryEntry
        fields = ['id', 'entry_type', 'object_type', 'object_id',
                  'user', 'username', 'timestamp', 'changes', 'text']
        read_only_fields = fields
