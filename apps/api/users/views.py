from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import User
from apps.api.permissions import CanManageConfig
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    PasswordResetSerializer,
    PermissionsUpdateSerializer,
)
from .services import UserAdminService


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
        if self.action in ('update', 'partial_update'):
            return UserUpdateSerializer
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

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance.refresh_from_db()
        return Response(UserDetailSerializer(instance).data)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Users cannot be hard-deleted. Use deactivate instead.')

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        target = self.get_object()
        UserAdminService.deactivate_user(request.user, target)
        return Response(UserDetailSerializer(target).data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        target = self.get_object()
        UserAdminService.activate_user(request.user, target)
        return Response(UserDetailSerializer(target).data)

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        target = self.get_object()
        serializer = PasswordResetSerializer(
            data=request.data, context={'target': target}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password reset.'})

    @action(detail=True, methods=['put'], url_path='permissions')
    def permissions(self, request, pk=None):
        target = self.get_object()
        serializer = PermissionsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserAdminService.set_permissions(
            request.user, target, serializer.validated_data['permissions']
        )
        target.refresh_from_db()
        return Response(UserDetailSerializer(target).data)
