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
