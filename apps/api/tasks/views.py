from django.core.exceptions import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Task
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.core.services import NotFoundError, ServiceError


class TaskViewSet(RetrieveModelMixin, viewsets.GenericViewSet):
    """Flat task endpoints — lifecycle actions, materials, subtasks.

    These operations only need the task id; they live at
    /api/tasks/{task_id}/... (tasks are job-scoped via Task.job).

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

    TERMINAL_STATUSES = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)

    def _get_task_or_404(self, pk):
        try:
            return Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFound()

    def _check_task_mutable(self, task):
        """Return a 400 Response if the task is in a terminal status, else None."""
        if task.status in self.TERMINAL_STATUSES:
            return Response(
                {'detail': f'Cannot modify a {task.status} task.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    # --- Material CRUD ---

    @action(detail=True, methods=['get', 'post'], url_path='materials', url_name='materials')
    def materials(self, request, pk=None):
        from apps.api.tasks.serializers import MaterialSerializer, MaterialWriteSerializer
        task = self.get_object()
        if request.method == 'GET':
            materials = Material.objects.filter(task=task).select_related('price_list_item')
            serializer = MaterialSerializer(materials, many=True)
            return Response(serializer.data)

        err = self._check_task_mutable(task)
        if err:
            return err
        serializer = MaterialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mat = MaterialService.create_on_job(
            job=task.job, task=task, **serializer.validated_data
        )
        return Response(
            MaterialSerializer(mat).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch', 'delete'],
            url_path='materials/(?P<mid>[0-9]+)', url_name='material-detail')
    def material_detail(self, request, pk=None, mid=None):
        from apps.api.tasks.serializers import MaterialSerializer, MaterialWriteSerializer
        task = self.get_object()
        err = self._check_task_mutable(task)
        if err:
            return err
        try:
            material = Material.objects.get(pk=mid, task=task)
        except Material.DoesNotExist:
            raise NotFound()

        if request.method == 'DELETE':
            from django.core.exceptions import ValidationError as DjangoValidationError
            if material.consumption_state == Material.CONSUMPTION_STATE_PENDING:
                # Pending materials may have earmarks; restock fully to unwind them.
                qty = material.quantity
                if qty > 0:
                    try:
                        MaterialService.restock(material, qty)
                    except DjangoValidationError as e:
                        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    material.delete()
            else:
                # NA-state material: no earmark/inventory accounting; safe to delete directly.
                material.delete()
            return Response({'message': 'Material deleted.'})

        # PATCH — only metadata fields allowed; quantity changes go through
        # /api/materials/{id}/draw-more/ or /api/materials/{id}/restock/.
        QUANTITY_FIELDS = {'quantity', 'restocked_qty'}
        disallowed = QUANTITY_FIELDS.intersection(request.data.keys())
        if disallowed:
            return Response(
                {'detail': 'Quantity changes must use draw-more or restock actions on /api/materials/{id}/.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = MaterialWriteSerializer(material, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(material, field, value)
        material.save()
        return Response(MaterialSerializer(material).data)

    # --- Subtask CRUD ---

    @action(detail=True, methods=['get', 'post'], url_path='subtasks', url_name='subtasks')
    def subtasks(self, request, pk=None):
        from apps.api.tasks.serializers import TaskSerializer
        task = self.get_object()
        if request.method == 'GET':
            children = Task.objects.filter(parent_task=task).order_by('sort_order')
            serializer = TaskSerializer(children, many=True)
            return Response(serializer.data)

        err = self._check_task_mutable(task)
        if err:
            return err
        serializer = TaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(parent_task=task, job=task.job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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
        reason = request.data.get('reason', '').strip() if request.data else ''
        try:
            result = TaskLifecycleService.block_task(task.pk, reason=reason)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({
            'status': Task.STATUS_BLOCKED,
            'blocked_reason': reason,
        })

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



