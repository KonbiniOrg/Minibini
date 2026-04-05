from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Blep, Task
from apps.jobs.services.blep_service import BlepService, BlepPermissionError
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    """Top-level Blep (time entry) endpoints.

    List supports filters ?user=me|<id>, ?task=<id>, ?since=<iso>.
    Create/update/delete enforce ownership + 24h window or can_manage_time
    in the service layer.
    """
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Blep.objects.all().order_by('-start_time')
        user_param = self.request.query_params.get('user')
        task_param = self.request.query_params.get('task')
        since_param = self.request.query_params.get('since')
        if user_param:
            if user_param == 'me':
                qs = qs.filter(user=self.request.user)
            else:
                qs = qs.filter(user_id=user_param)
        if task_param:
            qs = qs.filter(task_id=task_param)
        if since_param:
            qs = qs.filter(start_time__gte=since_param)
        return qs

    def create(self, request, *args, **kwargs):
        data = request.data
        task_id = data.get('task')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        target_user_id = data.get('user')
        if not (task_id and start_time and end_time):
            return Response(
                {'detail': 'task, start_time, and end_time are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(start_time, str):
            start_time = parse_datetime(start_time)
        if isinstance(end_time, str):
            end_time = parse_datetime(end_time)
        if start_time is None or end_time is None:
            return Response(
                {'detail': 'start_time and end_time must be valid ISO datetimes.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            return Response({'task': ['Task not found.']},
                             status=status.HTTP_400_BAD_REQUEST)
        target_user = None
        if target_user_id is not None:
            from apps.core.models import User
            try:
                target_user = User.objects.get(pk=target_user_id)
            except User.DoesNotExist:
                return Response({'user': ['User not found.']},
                                 status=status.HTTP_400_BAD_REQUEST)
        try:
            blep = BlepService.create_historical(
                actor=request.user, task=task,
                start_time=start_time, end_time=end_time,
                target_user=target_user,
            )
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BlepSerializer(blep).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # Treat PUT the same as PATCH; we never do full-replacement updates.
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        blep = self.get_object()
        allowed = {'start_time', 'end_time'}
        fields = {}
        for k, v in request.data.items():
            if k not in allowed:
                continue
            if isinstance(v, str):
                parsed = parse_datetime(v)
                if parsed is None:
                    return Response(
                        {k: [f'Invalid datetime: {v}']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                v = parsed
            fields[k] = v
        try:
            BlepService.update(blep, request.user, **fields)
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        blep.refresh_from_db()
        return Response(BlepSerializer(blep).data)

    def destroy(self, request, *args, **kwargs):
        blep = self.get_object()
        try:
            BlepService.delete(blep, request.user)
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)
