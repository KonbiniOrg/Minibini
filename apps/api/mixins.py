from django.core.exceptions import ValidationError
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
                reason = request.data.get('reason', '').strip() if request.data else ''
                if needs_reason and not reason:
                    return Response(
                        {'reason': ['This field is required.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    kwargs = {}
                    if needs_reason:
                        kwargs['reason'] = reason
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

                if reason:
                    from apps.core.history import get_history_context
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
        line_item_service_class = SomeService  # must have add_line_item, add_line_item_from_pli,
                                               # update_line_item, delete_line_item,
                                               # reorder_line_items
    """
    line_item_serializer_class = None
    line_item_parent_field = None
    line_item_service_class = None

    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        service = self.line_item_service_class
        data = request.data.copy()
        pli_id = data.get('price_list_item')
        has_manual_fields = data.get('description') or data.get('price')

        try:
            if pli_id and not has_manual_fields:
                qty = data.get('qty', 0)
                item = service.add_line_item_from_pli(parent.pk, pli_id, qty)
            else:
                item = service.add_line_item(parent.pk, **data)
        except (ValidationError, NotFoundError) as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)
        service = self.line_item_service_class

        if request.method == 'DELETE':
            try:
                service.delete_line_item(item.pk)
            except (ValidationError, Exception) as e:
                return Response(
                    {'detail': str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({'message': 'Line item deleted.'})

        try:
            item = service.update_line_item(item.pk, **request.data)
        except (ValidationError, NotFoundError) as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.line_item_serializer_class(item)
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
        service = self.line_item_service_class
        try:
            service.reorder_line_items(parent.pk, item_ids)
        except (ValidationError, NotFoundError) as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        items = self._get_line_items_qs(parent)
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


class JobTaskMixin:
    """
    Adds task CRUD actions to the Job viewset.

    Works against Task (now belongs directly to Job after the 2026-04-12
    WorkOrder removal). No bundles on the job side.

    Subclasses declare:
        task_serializer_class = SomeTaskSerializer
    """
    task_serializer_class = None

    @action(detail=True, methods=['get', 'post'], url_path='tasks', url_name='tasks')
    def tasks(self, request, pk=None):
        job = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import Task
            tasks = Task.objects.filter(job=job).order_by('sort_order')
            serializer = self.task_serializer_class(tasks, many=True)
            return Response(serializer.data)

        serializer = self.task_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(job=job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='tasks/(?P<task_pk>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_pk=None):
        job = self.get_object()
        task = self._get_task_or_404(job, task_pk)

        if request.method == 'DELETE':
            from django.core.exceptions import ValidationError
            from apps.jobs.services import TaskService
            try:
                TaskService.delete_task(task.pk)
            except ValidationError as e:
                return Response(
                    {'detail': e.message if hasattr(e, 'message') else str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({'message': 'Task deleted.'})

        serializer = self.task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def _get_task_or_404(self, job, task_pk):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_pk, job=job)
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()
