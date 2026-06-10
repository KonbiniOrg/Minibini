from rest_framework import serializers


class HistoryEntrySerializer(serializers.Serializer):
    """Model-agnostic: serializes JobHistory / CrmHistory / PurchasingHistory
    rows (they share a schema), so one serializer covers every history feed."""
    id = serializers.IntegerField(read_only=True)
    entry_type = serializers.CharField(read_only=True)
    object_type = serializers.CharField(read_only=True)
    object_id = serializers.IntegerField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source='user.username', read_only=True, default=None)
    timestamp = serializers.DateTimeField(read_only=True)
    changes = serializers.JSONField(read_only=True)
    text = serializers.CharField(read_only=True)
    source_label = serializers.SerializerMethodField()
    source_link = serializers.SerializerMethodField()

    def get_source_label(self, obj):
        labels = self.context.get('source_labels') or {}
        return labels.get((obj.object_type, obj.object_id))

    def get_source_link(self, obj):
        links = self.context.get('source_links') or {}
        return links.get((obj.object_type, obj.object_id))
