from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import User
from apps.api.permissions import CanManageConfig
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    """Owner-side user administration."""

    queryset = User.objects.all().order_by('-is_active', 'username')
    lookup_field = 'pk'
    pagination_class = None

    def get_permissions(self):
        return [IsAuthenticated(), CanManageConfig()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        if self.action == 'create':
            return UserCreateSerializer
        return UserListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Return the detail shape, not the create-input shape
        return Response(
            UserDetailSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )
