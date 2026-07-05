from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Blep
from apps.jobs.services import BlepService, BlepPermissionError
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    """Top-level Blep (time entry) endpoints.

    List supports filters ?user=me|<id>, ?task=<id>, ?since=<iso>.
    Create/update/delete enforce ownership + 30h window or can_manage_time
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
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        try:
            blep = BlepService.create_historical(
                actor=request.user,
                task=validated['task'],
                start_time=validated['start_time'],
                end_time=validated['end_time'],
                target_user=validated.get('user'),
            )
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(BlepSerializer(blep).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # Treat PUT the same as PATCH; we never do full-replacement updates.
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        blep = self.get_object()
        allowed = {'start_time', 'end_time', 'user'}
        fields = {}
        for k, v in request.data.items():
            if k not in allowed:
                continue
            if k == 'user':
                # Resolve user id to User instance for BlepService.update
                from apps.core.models import User
                try:
                    fields['user'] = User.objects.get(pk=v)
                except User.DoesNotExist:
                    return Response(
                        {'user': ['User not found.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
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
        blep.refresh_from_db()
        return Response(BlepSerializer(blep).data)

    def destroy(self, request, *args, **kwargs):
        blep = self.get_object()
        try:
            BlepService.delete(blep, request.user)
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response({'message': 'Time entry deleted.'})
