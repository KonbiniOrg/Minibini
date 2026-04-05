from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Task


class TaskViewSet(RetrieveModelMixin, viewsets.GenericViewSet):
    """Flat task endpoints — lifecycle actions.

    These operations only need the task id; they were previously nested
    under /api/work-orders/{wo_pk}/tasks/{task_id}/... via TaskLifecycleMixin.

    Any authenticated user can drive task lifecycle (start, complete,
    block, unblock, cancel) and their own time tracking (start-work,
    stop-work). These are worker operations, not manager-only.
    """
    queryset = Task.objects.all()
    lookup_field = 'pk'
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from apps.api.tasks.serializers import TaskDetailSerializer
        return TaskDetailSerializer

    def _get_task_or_404(self, pk):
        try:
            return Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFound()

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

