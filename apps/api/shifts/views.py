from collections import defaultdict
from datetime import datetime, time
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import Shift, User, ShiftChangeRequest
from apps.jobs.models import BlepChangeRequest
from apps.core.services import ShiftService, TimeChangeRequestService
from apps.api.permissions import CanManageTime, CanManageTimeOrFinancials
from .serializers import (ShiftSerializer, ShiftChangeRequestSerializer,
                          BlepChangeRequestSerializer)


def _resolve_target(request):
    """Clock self by default; managers may target ?user / body 'user'."""
    uid = request.data.get('user') or request.query_params.get('user')
    if uid and str(uid) != str(request.user.id):
        if not (request.user.has_perm('core.can_manage_time')):
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
        if not (request.user.has_perm('core.can_manage_time')):
            return Response({'detail': 'Not permitted.'}, status=status.HTTP_403_FORBIDDEN)
        shift.delete()
        return Response({'message': 'Shift deleted.'})


class _ChangeRequestViewSet(viewsets.ModelViewSet):
    """Common behaviour for shift/blep change requests."""

    def get_permissions(self):
        if self.action in ('approve', 'deny'):
            return [IsAuthenticated(), CanManageTime()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = self.queryset_model.objects.all().select_related('requester')
        status_p = self.request.query_params.get('status')
        mine = self.request.query_params.get('mine')
        if status_p:
            qs = qs.filter(status=status_p)
        if mine == 'true':
            qs = qs.filter(requester=self.request.user)
        elif not (self.request.user.has_perm('core.can_manage_time')):
            qs = qs.filter(requester=self.request.user)
        return qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = ser.validated_data.get('shift') or ser.validated_data.get('blep')
        if target is not None and target.user_id != request.user.id \
                and not (request.user.has_perm('core.can_manage_time')):
            return Response(
                {'detail': 'You can only request changes to your own time records.'},
                status=status.HTTP_403_FORBIDDEN)
        instance = self.queryset_model(requester=request.user, **ser.validated_data)
        try:
            TimeChangeRequestService.submit(instance)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        try:
            TimeChangeRequestService.approve(self.get_object(), reviewer=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=['post'])
    def deny(self, request, pk=None):
        note = (request.data or {}).get('note', '')
        try:
            TimeChangeRequestService.deny(self.get_object(), reviewer=request.user, note=note)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(self.get_object()).data)


class ShiftChangeRequestViewSet(_ChangeRequestViewSet):
    queryset_model = ShiftChangeRequest
    serializer_class = ShiftChangeRequestSerializer


class BlepChangeRequestViewSet(_ChangeRequestViewSet):
    queryset_model = BlepChangeRequest
    serializer_class = BlepChangeRequestSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageTimeOrFinancials])
def shift_report(request):
    start_s = request.query_params.get('start')
    end_s = request.query_params.get('end')
    if not start_s or not end_s:
        return Response({'detail': 'start and end (YYYY-MM-DD) are required.'},
                        status=status.HTTP_400_BAD_REQUEST)
    tz = dj_tz.get_current_timezone()
    start_dt = dj_tz.make_aware(datetime.combine(datetime.fromisoformat(start_s).date(), time.min), tz)
    end_dt = dj_tz.make_aware(datetime.combine(datetime.fromisoformat(end_s).date(), time.max), tz)

    qs = (Shift.objects.filter(start_time__gte=start_dt, start_time__lte=end_dt)
          .select_related('user').order_by('user__username', 'start_time'))
    if request.query_params.get('user'):
        qs = qs.filter(user_id=request.query_params['user'])

    workers = defaultdict(lambda: {'user_id': None, 'name': '', 'days': defaultdict(list),
                                   'total_minutes': 0})
    for s in qs:
        w = workers[s.user_id]
        w['user_id'] = s.user_id
        w['name'] = s.user.get_full_name() or s.user.username
        local_start = dj_tz.localtime(s.start_time)
        end = s.end_time or dj_tz.now()
        minutes = max(0, int((end - s.start_time).total_seconds() // 60))
        w['days'][local_start.date().isoformat()].append({
            'shift_id': s.shift_id,
            'start': s.start_time.isoformat(),
            'end': s.end_time.isoformat() if s.end_time else None,
            'minutes': minutes,
            'open': s.end_time is None,
        })
        w['total_minutes'] += minutes

    result = []
    for w in workers.values():
        result.append({
            'user_id': w['user_id'], 'name': w['name'], 'total_minutes': w['total_minutes'],
            'days': [{'date': d, 'shifts': shifts} for d, shifts in sorted(w['days'].items())],
        })
    return Response({'start': start_s, 'end': end_s, 'workers': result})
