from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
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


class UserCreateSerializer(serializers.ModelSerializer):
    """Input shape for POST /api/users/."""
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'password', 'password_confirm',
        ]

    def validate_password(self, value):
        # Can't pass the user here because it doesn't exist yet.
        try:
            django_validate_password(value, user=None)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError(
                {'password_confirm': ['Passwords do not match.']}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user
