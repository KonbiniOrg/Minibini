from rest_framework import serializers
from apps.core.models import Shift, User


class ShiftSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(),
                                              required=False, allow_null=True)

    class Meta:
        model = Shift
        fields = ['shift_id', 'user', 'user_name', 'start_time', 'end_time', 'is_open']
        read_only_fields = ['shift_id', 'user_name', 'is_open']

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


from apps.core.models import ShiftChangeRequest
from apps.jobs.models import BlepChangeRequest


class _BaseChangeRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()

    def get_requester_name(self, obj):
        return obj.requester.get_full_name() or obj.requester.username

    common_fields = ['request_id', 'requester', 'requester_name', 'requested_start',
                     'requested_end', 'reason', 'status', 'has_known_conflict',
                     'reviewer', 'reviewed_at', 'review_note', 'created_at']
    common_read_only = ['request_id', 'requester', 'requester_name', 'status',
                        'has_known_conflict', 'reviewer', 'reviewed_at', 'review_note',
                        'created_at']


class ShiftChangeRequestSerializer(_BaseChangeRequestSerializer):
    class Meta:
        model = ShiftChangeRequest
        fields = _BaseChangeRequestSerializer.common_fields + ['shift']
        read_only_fields = _BaseChangeRequestSerializer.common_read_only


class BlepChangeRequestSerializer(_BaseChangeRequestSerializer):
    task_name = serializers.CharField(source='task.name', read_only=True)

    class Meta:
        model = BlepChangeRequest
        fields = _BaseChangeRequestSerializer.common_fields + ['blep', 'task', 'task_name']
        read_only_fields = _BaseChangeRequestSerializer.common_read_only

    def validate(self, attrs):
        if attrs.get('blep') is None and attrs.get('task') is None:
            raise serializers.ValidationError(
                {'task': 'A task is required to record a missing time entry.'})
        return attrs
