from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.services import ServiceError, NotFoundError


class StatusTransitionMixin:
    """
    Mixin that auto-registers action endpoints from a status_actions dict.

    Subclasses declare:
        status_actions = {
            'complete': {'service': SomeService.complete},
            'cancel': {'service': SomeService.cancel, 'requires_reason': True},
        }

    Each entry becomes a POST action on the viewset.
    If requires_reason is True, validates that 'reason' is in the request body.
    The service callable receives (pk) or (pk, reason=reason).
    """
    status_actions = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for action_name, config in cls.status_actions.items():
            cls._register_status_action(action_name, config)

    @classmethod
    def _register_status_action(cls, action_name, config):
        service_fn = config['service']
        requires_reason = config.get('requires_reason', False)

        def make_action(svc, needs_reason):
            def action_fn(self, request, pk=None):
                if needs_reason:
                    reason = request.data.get('reason', '').strip()
                    if not reason:
                        return Response(
                            {'reason': ['This field is required.']},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                try:
                    kwargs = {}
                    if needs_reason:
                        kwargs['reason'] = request.data['reason']
                    svc(pk, **kwargs)
                except NotFoundError:
                    return Response(
                        {'detail': 'Not found.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                except ServiceError as e:
                    return Response(
                        {'detail': str(e)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                instance = self.get_object()

                if needs_reason:
                    from apps.core.history import get_history_context
                    reason = request.data['reason']
                    obj_type = instance.__class__.__name__.lower()
                    attached = False
                    ctx = get_history_context()
                    if ctx:
                        for entry in reversed(ctx.pending):
                            if (entry.get('object_type') == obj_type
                                    and entry.get('entry_type') == 'audit'):
                                entry['text'] = reason
                                attached = True
                                break
                    if not attached:
                        from apps.core.models import HistoryEntry
                        HistoryEntry.objects.create(
                            entry_type='audit',
                            object_type=obj_type,
                            object_id=instance.pk,
                            user=request.user if hasattr(request, 'user') and request.user.is_authenticated else None,
                            text=reason,
                        )

                serializer = self.get_serializer(instance)
                return Response(serializer.data)
            return action_fn

        fn = make_action(service_fn, requires_reason)
        # Set __name__ BEFORE @action so DRF's mapping uses the correct name
        fn.__name__ = action_name
        fn.__qualname__ = f'{cls.__name__}.{action_name}'
        decorated = action(detail=True, methods=['post'], url_path=action_name, url_name=action_name)(fn)
        setattr(cls, action_name, decorated)


class LineItemMixin:
    """
    Adds line-item CRUD actions to a document viewset.

    Subclasses declare:
        line_item_serializer_class = SomeLineItemSerializer
        line_item_parent_field = 'estimate'  # FK name on line item model
    """
    line_item_serializer_class = None
    line_item_parent_field = None

    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        serializer = self.line_item_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.line_item_parent_field: parent})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)

        if request.method == 'DELETE':
            from apps.core.services import LineItemService
            LineItemService.delete_line_item_with_renumber(item)
            return Response({'message': 'Line item deleted.'})

        serializer = self.line_item_serializer_class(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='line-items/reorder', url_name='line-items-reorder')
    def reorder_line_items(self, request, pk=None):
        parent = self.get_object()
        item_ids = request.data.get('item_ids', [])
        if not item_ids:
            return Response(
                {'item_ids': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        items_qs = self._get_line_items_qs(parent)
        for position, item_id in enumerate(item_ids, start=1):
            items_qs.filter(pk=item_id).update(line_number=position)
        items = items_qs.order_by('line_number')
        serializer = self.line_item_serializer_class(items, many=True)
        return Response(serializer.data)

    def _get_line_items_qs(self, parent):
        model = self.line_item_serializer_class.Meta.model
        return model.objects.filter(
            **{self.line_item_parent_field: parent}
        ).order_by('line_number')

    def _get_line_item_or_404(self, parent, item_id):
        model = self.line_item_serializer_class.Meta.model
        try:
            return model.objects.get(
                pk=item_id,
                **{self.line_item_parent_field: parent}
            )
        except model.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()


class PlanTaskBundleMixin:
    """
    Adds plan-task and plan-bundle CRUD actions to the EstWorksheet viewset.

    Works against PlanTask and PlanBundle (worksheet-side models).

    Subclasses declare:
        plan_task_serializer_class = SomePlanTaskSerializer
        plan_bundle_serializer_class = SomePlanBundleSerializer
    """
    plan_task_serializer_class = None
    plan_bundle_serializer_class = None

    @action(detail=True, methods=['get', 'post'], url_path='tasks', url_name='tasks')
    def tasks(self, request, pk=None):
        worksheet = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import PlanTask
            tasks = PlanTask.objects.filter(est_worksheet=worksheet).order_by('sort_order')
            serializer = self.plan_task_serializer_class(tasks, many=True)
            return Response(serializer.data)

        serializer = self.plan_task_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(est_worksheet=worksheet)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='tasks/(?P<task_id>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_id=None):
        worksheet = self.get_object()
        task = self._get_plan_task_or_404(worksheet, task_id)

        if request.method == 'DELETE':
            task.delete()
            return Response({'message': 'Task deleted.'})

        serializer = self.plan_task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'post'], url_path='bundles', url_name='bundles')
    def bundles(self, request, pk=None):
        worksheet = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import PlanBundle
            bundles = PlanBundle.objects.filter(est_worksheet=worksheet).order_by('sort_order')
            serializer = self.plan_bundle_serializer_class(bundles, many=True)
            return Response(serializer.data)

        serializer = self.plan_bundle_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(est_worksheet=worksheet)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='bundles/(?P<bundle_id>[0-9]+)', url_name='bundle-detail')
    def bundle_detail(self, request, pk=None, bundle_id=None):
        worksheet = self.get_object()
        bundle = self._get_plan_bundle_or_404(worksheet, bundle_id)

        if request.method == 'DELETE':
            from apps.jobs.models import PlanTask
            PlanTask.objects.filter(bundle=bundle).update(
                bundle=None, mapping_strategy='direct'
            )
            bundle.delete()
            return Response({'message': 'Bundle deleted.'})

        serializer = self.plan_bundle_serializer_class(bundle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/add-tasks', url_name='bundle-add-tasks')
    def add_tasks_to_bundle(self, request, pk=None, bundle_id=None):
        worksheet = self.get_object()
        bundle = self._get_plan_bundle_or_404(worksheet, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import PlanTask
        PlanTask.objects.filter(pk__in=task_ids, est_worksheet=worksheet).update(
            bundle=bundle, mapping_strategy='bundle'
        )
        serializer = self.plan_bundle_serializer_class(bundle)
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/remove-tasks', url_name='bundle-remove-tasks')
    def remove_tasks_from_bundle(self, request, pk=None, bundle_id=None):
        worksheet = self.get_object()
        bundle = self._get_plan_bundle_or_404(worksheet, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import PlanTask
        PlanTask.objects.filter(pk__in=task_ids, bundle=bundle).update(
            bundle=None, mapping_strategy='direct'
        )
        serializer = self.plan_bundle_serializer_class(bundle)
        return Response(serializer.data)

    def _get_plan_task_or_404(self, worksheet, task_id):
        from apps.jobs.models import PlanTask
        try:
            return PlanTask.objects.get(pk=task_id, est_worksheet=worksheet)
        except PlanTask.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

    def _get_plan_bundle_or_404(self, worksheet, bundle_id):
        from apps.jobs.models import PlanBundle
        try:
            return PlanBundle.objects.get(pk=bundle_id, est_worksheet=worksheet)
        except PlanBundle.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()


class WorkOrderTaskMixin:
    """
    Adds task CRUD actions to the WorkOrder viewset.

    Works against Task (work-order-side model). No bundles — RealBundle
    does not exist after the 2026-04-05 model split.

    Subclasses declare:
        task_serializer_class = SomeTaskSerializer
    """
    task_serializer_class = None

    @action(detail=True, methods=['get', 'post'], url_path='tasks', url_name='tasks')
    def tasks(self, request, pk=None):
        work_order = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import Task
            tasks = Task.objects.filter(work_order=work_order).order_by('sort_order')
            serializer = self.task_serializer_class(tasks, many=True)
            return Response(serializer.data)

        serializer = self.task_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(work_order=work_order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='tasks/(?P<task_id>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_id=None):
        work_order = self.get_object()
        task = self._get_task_or_404(work_order, task_id)

        if request.method == 'DELETE':
            from apps.jobs.models import Task, Blep
            non_deletable = (Task.STATUS_IN_PROGRESS, Task.STATUS_COMPLETE)
            if task.status in non_deletable:
                return Response(
                    {'detail': f'Cannot delete a {task.status} task. Cancel it instead.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if Blep.objects.filter(task=task).exists():
                return Response(
                    {'detail': 'Cannot delete a task that has time entries. Cancel it instead.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            was_blocked = task.status == Task.STATUS_BLOCKED
            wo = task.work_order
            task.delete()
            if was_blocked:
                from apps.jobs.models import WorkOrder
                if wo.status == WorkOrder.STATUS_BLOCKED:
                    still_blocked = Task.objects.filter(
                        work_order=wo, status=Task.STATUS_BLOCKED,
                    ).exists()
                    if not still_blocked:
                        from apps.jobs.services import WorkOrderService
                        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_INCOMPLETE)
            return Response({'message': 'Task deleted.'})

        serializer = self.task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def _get_task_or_404(self, work_order, task_id):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_id, work_order=work_order)
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()
