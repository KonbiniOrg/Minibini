from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.permissions import CanManageJobs
from apps.jobs.models import Task


class TaskViewSet(viewsets.GenericViewSet):
    """Flat task endpoints — lifecycle actions and blep listing.

    These operations only need the task id; they were previously nested
    under /api/work-orders/{wo_pk}/tasks/{task_id}/... via TaskLifecycleMixin.
    """
    queryset = Task.objects.all()
    lookup_field = 'pk'

    def get_permissions(self):
        read_actions = ('bleps',)
        if self.action in read_actions:
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def _get_task_or_404(self, pk):
        try:
            return Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFound()

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            result = TaskLifecycleService.start_task(task.pk, request.user)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': Task.STATUS_IN_PROGRESS, 'blep_id': result['blep'].blep_id})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            TaskLifecycleService.complete_task(task.pk)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': Task.STATUS_COMPLETE})

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            result = TaskLifecycleService.block_task(task.pk)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({'status': Task.STATUS_BLOCKED})

    @action(detail=True, methods=['post'])
    def unblock(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            TaskLifecycleService.unblock_task(task.pk)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': Task.STATUS_IN_PROGRESS})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            TaskLifecycleService.cancel_task(task.pk)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': Task.STATUS_CANCELLED})

    @action(detail=True, methods=['post'], url_path='start-work')
    def start_work(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            result = TaskLifecycleService.start_work(
                task.pk, request.user, action=request.data.get('action')
            )
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({'status': 'ok', 'blep_id': result['blep'].blep_id})

    @action(detail=True, methods=['post'], url_path='stop-work')
    def stop_work(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        try:
            TaskLifecycleService.stop_work(task.pk, request.user)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'status': 'ok'})

    @action(detail=True, methods=['get'])
    def bleps(self, request, pk=None):
        from apps.jobs.models import Blep
        from apps.api.work_orders.serializers import BlepSerializer
        task = self._get_task_or_404(pk)
        bleps = Blep.objects.filter(task=task)
        serializer = BlepSerializer(bleps, many=True)
        return Response(serializer.data)
