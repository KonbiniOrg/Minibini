from rest_framework import serializers
from apps.core.models import User


class UserListSerializer(serializers.ModelSerializer):
    """Row shape for GET /api/users/."""
    id = serializers.IntegerField(source='pk', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'email', 'is_active', 'is_superuser',
        ]
        read_only_fields = fields


class UserDetailSerializer(serializers.ModelSerializer):
    """Row shape for GET /api/users/:id/."""
    id = serializers.IntegerField(source='pk', read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'is_superuser', 'permissions', 'date_joined',
        ]
        read_only_fields = fields

    def get_permissions(self, obj):
        """Return directly-granted atom codenames (groups not used)."""
        return sorted(
            obj.user_permissions.filter(
                codename__startswith='can_',
                content_type__app_label='core',
            ).values_list('codename', flat=True)
        )
