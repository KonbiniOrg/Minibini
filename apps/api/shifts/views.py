from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import Shift, User
from apps.core.services import ShiftService
from .serializers import ShiftSerializer


def _resolve_target(request):
    """Clock self by default; managers may target ?user / body 'user'."""
    uid = request.data.get('user') or request.query_params.get('user')
    if uid and str(uid) != str(request.user.id):
        if not (request.user.is_superuser or request.user.has_perm('core.can_manage_time')):
            return None, Response({'detail': 'Not permitted to clock another user.'},
                                  status=status.HTTP_403_FORBIDDEN)
        try:
            return User.objects.get(pk=uid), None
        except User.DoesNotExist:
            return None, Response({'detail': 'User not found.'},
                                  status=status.HTTP_404_NOT_FOUND)
    return request.user, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clock_in(request):
    target, err = _resolve_target(request)
    if err:
        return err
    try:
        shift = ShiftService.clock_in(target)
    except DjangoValidationError as e:
        return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clock_out(request):
    target, err = _resolve_target(request)
    if err:
        return err
    try:
        shift = ShiftService.clock_out(target)
    except DjangoValidationError as e:
        return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ShiftSerializer(shift).data)


class ShiftViewSet(viewsets.ModelViewSet):
    """List/retrieve/patch shifts. ?user=me|<id>, ?since=<iso>."""
    serializer_class = ShiftSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Shift.objects.all().select_related('user')
        u = self.request.query_params.get('user')
        since = self.request.query_params.get('since')
        if u == 'me':
            qs = qs.filter(user=self.request.user)
        elif u:
            qs = qs.filter(user_id=u)
        if since:
            # A '+HH:MM' tz offset arrives URL-decoded to a space; restore it
            # before parsing so the filter doesn't choke on an invalid format.
            parsed = parse_datetime(since) or parse_datetime(since.replace(' ', '+'))
            if parsed is not None:
                qs = qs.filter(start_time__gte=parsed)
        return qs

    @action(detail=False, methods=['get'], url_path='active')
    def active(self, request):
        shift = ShiftService.open_shift_for(request.user)
        return Response({'shift': ShiftSerializer(shift).data if shift else None})

    def update(self, request, *args, **kwargs):
        shift = self.get_object()
        partial = kwargs.get('partial', False)
        ser = self.get_serializer(shift, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        try:
            ShiftService.update(shift, actor=request.user,
                                start_time=v.get('start_time', shift.start_time),
                                end_time=v.get('end_time', shift.end_time))
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ShiftSerializer(shift).data)

    def destroy(self, request, *args, **kwargs):
        shift = self.get_object()
        if not (request.user.is_superuser or request.user.has_perm('core.can_manage_time')):
            return Response({'detail': 'Not permitted.'}, status=status.HTTP_403_FORBIDDEN)
        shift.delete()
        return Response({'message': 'Shift deleted.'})
