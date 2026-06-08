from rest_framework import serializers
from apps.core.models import HistoryEntry


class HistoryEntrySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    source_label = serializers.SerializerMethodField()
    source_link = serializers.SerializerMethodField()

    class Meta:
        model = HistoryEntry
        fields = ['id', 'entry_type', 'object_type', 'object_id',
                  'user', 'username', 'timestamp', 'changes', 'text',
                  'source_label', 'source_link']
        read_only_fields = fields

    def get_source_label(self, obj):
        labels = self.context.get('source_labels') or {}
        return labels.get((obj.object_type, obj.object_id))

    def get_source_link(self, obj):
        links = self.context.get('source_links') or {}
        return links.get((obj.object_type, obj.object_id))
