from rest_framework import serializers
from apps.core.models import User


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='pk', read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, obj):
        """Return list of custom permission codenames the user has."""
        return sorted(
            perm.split('.')[1]
            for perm in obj.get_all_permissions()
            if perm.startswith('core.can_')
        )


class MeUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile update. Deliberately omits username, password,
    and all privilege flags — see docs/designs/2026-04-10-user-self-service-design.md
    """
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
