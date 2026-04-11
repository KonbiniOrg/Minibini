from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.models import User
from apps.api.permissions import CanManageConfig


class UserViewSet(viewsets.ModelViewSet):
    """Owner-side user administration."""

    queryset = User.objects.all().order_by('-is_active', 'username')
    lookup_field = 'pk'
    pagination_class = None  # small lists, no pagination needed

    def get_permissions(self):
        return [IsAuthenticated(), CanManageConfig()]

    def get_serializer_class(self):
        # Populated in later tasks
        from rest_framework import serializers

        class _Placeholder(serializers.Serializer):
            pass
        return _Placeholder
