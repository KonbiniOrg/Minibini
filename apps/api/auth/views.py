from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .serializers import (
    LoginSerializer,
    UserSerializer,
    MeUpdateSerializer,
    PasswordChangeSerializer,
)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(
        request,
        username=serializer.validated_data['username'],
        password=serializer.validated_data['password'],
    )
    if user is None:
        return Response(
            {'detail': 'Invalid credentials.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    # An explicit logout clocks the worker out: close any active blep before the
    # session is cleared. (Session *expiry* has no server-side hook and is left
    # alone — bleps stay open until the worker logs out deliberately.)
    from apps.jobs.services import BlepService
    BlepService.close_user_open_bleps(request.user)
    logout(request)
    return Response({'detail': 'Logged out.'})


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_view(request):
    if request.method == 'PATCH':
        serializer = MeUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    serializer = PasswordChangeSerializer(
        data=request.data, context={'request': request}
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    update_session_auth_hash(request, request.user)
    return Response({'detail': 'Password changed.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def users_list(request):
    """Return active users for assignee dropdowns."""
    from apps.core.models import User
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    data = []
    for u in users:
        name = u.get_full_name() or u.username
        data.append({'id': u.pk, 'username': u.username, 'name': name})
    return Response(data)


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_stub(request):
    return Response(
        {'detail': 'Not yet implemented.', 'endpoint': 'POST /api/auth/refresh/'},
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )
