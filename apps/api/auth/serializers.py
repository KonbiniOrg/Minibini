from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
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
    # null = "uses the shop default" (the schedule_week_envelope config key).
    schedule_envelope = serializers.JSONField(read_only=True)
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


class ScheduleEnvelopeSerializer(serializers.Serializer):
    """Validates a {"schedule_envelope": {...}|null} body. Null resets the
    user to the shop default. The per-day interval rules live in
    apps.schedule.calendar_arithmetic.validate_week_envelope."""
    schedule_envelope = serializers.JSONField(allow_null=True, required=True)

    def validate_schedule_envelope(self, value):
        if value is None:
            return None
        from apps.schedule.calendar_arithmetic import validate_week_envelope
        messages = validate_week_envelope(value)
        if messages:
            raise serializers.ValidationError(messages)
        return value


class PasswordChangeSerializer(serializers.Serializer):
    """Self-service password change. Requires the current password; runs
    the new password through Django's configured AUTH_PASSWORD_VALIDATORS.
    """
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        user = self.context['request'].user
        try:
            django_validate_password(value, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('new_password_confirm'):
            raise serializers.ValidationError(
                {'new_password_confirm': ['Passwords do not match.']}
            )
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user
