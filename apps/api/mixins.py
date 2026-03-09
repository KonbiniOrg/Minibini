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

        @action(detail=True, methods=['post'], url_path=action_name, url_name=action_name)
        def action_view(self, request, pk=None):
            if requires_reason:
                reason = request.data.get('reason', '').strip()
                if not reason:
                    return Response(
                        {'reason': ['This field is required.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            try:
                kwargs = {}
                if requires_reason:
                    kwargs['reason'] = request.data['reason']
                service_fn(pk, **kwargs)
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
            serializer = self.get_serializer(instance)
            return Response(serializer.data)

        action_view.__name__ = action_name
        action_view.__qualname__ = f'{cls.__name__}.{action_name}'
        setattr(cls, action_name, action_view)


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
            return Response(status=status.HTTP_204_NO_CONTENT)

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


class TaskBundleMixin:
    """
    Adds task and bundle CRUD actions to a container viewset (EstWorksheet, WorkOrder).

    Subclasses declare:
        task_serializer_class = SomeTaskSerializer
        bundle_serializer_class = SomeBundleSerializer
        container_field = 'est_worksheet'  # FK name on Task/TaskBundle
    """
    task_serializer_class = None
    bundle_serializer_class = None
    container_field = None

    @action(detail=True, methods=['get', 'post'], url_path='tasks', url_name='tasks')
    def tasks(self, request, pk=None):
        container = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import Task
            tasks = Task.objects.filter(**{self.container_field: container}).order_by('sort_order')
            serializer = self.task_serializer_class(tasks, many=True)
            return Response(serializer.data)

        serializer = self.task_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.container_field: container})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='tasks/(?P<task_id>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_id=None):
        container = self.get_object()
        task = self._get_task_or_404(container, task_id)

        if request.method == 'DELETE':
            task.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'post'], url_path='bundles', url_name='bundles')
    def bundles(self, request, pk=None):
        container = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import TaskBundle
            bundles = TaskBundle.objects.filter(**{self.container_field: container}).order_by('sort_order')
            serializer = self.bundle_serializer_class(bundles, many=True)
            return Response(serializer.data)

        serializer = self.bundle_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.container_field: container})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='bundles/(?P<bundle_id>[0-9]+)', url_name='bundle-detail')
    def bundle_detail(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)

        if request.method == 'DELETE':
            from apps.jobs.models import Task
            Task.objects.filter(bundle=bundle).update(
                bundle=None, mapping_strategy='direct'
            )
            bundle.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.bundle_serializer_class(bundle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/add-tasks', url_name='bundle-add-tasks')
    def add_tasks_to_bundle(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import Task
        Task.objects.filter(pk__in=task_ids, **{self.container_field: container}).update(
            bundle=bundle, mapping_strategy='bundle'
        )
        serializer = self.bundle_serializer_class(bundle)
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/remove-tasks', url_name='bundle-remove-tasks')
    def remove_tasks_from_bundle(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import Task
        Task.objects.filter(pk__in=task_ids, bundle=bundle).update(
            bundle=None, mapping_strategy='direct'
        )
        serializer = self.bundle_serializer_class(bundle)
        return Response(serializer.data)

    def _get_task_or_404(self, container, task_id):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_id, **{self.container_field: container})
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

    def _get_bundle_or_404(self, container, bundle_id):
        from apps.jobs.models import TaskBundle
        try:
            return TaskBundle.objects.get(pk=bundle_id, **{self.container_field: container})
        except TaskBundle.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()
