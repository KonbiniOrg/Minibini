from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from apps.core.models import User


def _user_permission_codenames(user):
    """Return directly-granted atom codenames (groups not used)."""
    return sorted(
        user.user_permissions.filter(
            codename__startswith='can_',
            content_type__app_label='core',
        ).values_list('codename', flat=True)
    )


class UserListSerializer(serializers.ModelSerializer):
    """Row shape for GET /api/users/."""
    id = serializers.IntegerField(source='pk', read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'email', 'is_active', 'is_superuser', 'permissions',
        ]
        read_only_fields = fields

    def get_permissions(self, obj):
        return _user_permission_codenames(obj)


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
        return _user_permission_codenames(obj)


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


class UserUpdateSerializer(serializers.ModelSerializer):
    """Input shape for PATCH /api/users/:id/. Profile fields only.

    Fields allowlist is the privilege-escalation guard — password, flags,
    groups, and permissions are handled via dedicated endpoints.
    """
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']


class PasswordResetSerializer(serializers.Serializer):
    """Input shape for POST /api/users/:id/reset-password/.

    Pure Serializer (not ModelSerializer) — it's a pure input validator
    that calls set_password in save(), not a model-backed CRUD serializer.
    """
    password = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    def validate_password(self, value):
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

    def save(self, **kwargs):
        target = self.context['target']
        target.set_password(self.validated_data['password'])
        target.save(update_fields=['password'])
        return target


# Derive the known atom codenames from the User model's declared permissions.
_KNOWN_ATOMS = {codename for codename, _name in User._meta.permissions}


class PermissionsUpdateSerializer(serializers.Serializer):
    """Input shape for PUT /api/users/:id/permissions/."""
    permissions = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )

    def validate_permissions(self, value):
        unknown = [c for c in value if c not in _KNOWN_ATOMS]
        if unknown:
            raise serializers.ValidationError(
                f'Unknown permission codename(s): {", ".join(sorted(unknown))}'
            )
        return value
