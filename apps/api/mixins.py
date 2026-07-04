from django.core.exceptions import ValidationError
from apps.core.history import record_history
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.services import ServiceError, NotFoundError


class InvoiceRefMixin:
    """Adds a read-only ``invoice`` field — ``{'id', 'number'}`` or ``None`` — to
    an atom serializer (Task / Material / Expense).

    The single definition of "which invoice is this atom on" for the API layer.
    The claim map is supplied via serializer context under ``invoice_claims``,
    keyed by ``(source_type, pk)`` and built once per job/page upstream so there
    is no N+1. Subclasses set ``invoice_source_type``, declare
    ``invoice = serializers.SerializerMethodField()`` (DRF's metaclass only
    collects field declarations from the concrete serializer class, not a plain
    mixin), and include ``'invoice'`` in ``Meta.fields``.
    """
    invoice_source_type = None

    def get_invoice(self, obj):
        claims = self.context.get('invoice_claims') or {}
        ref = claims.get((self.invoice_source_type, obj.pk))
        if ref is None:
            return None
        return {'id': ref['invoice_id'], 'number': ref['invoice_number']}


class JSONDestroyMixin:
    """
    Override DRF's default destroy() to return 200 with a JSON body instead of
    the default 204 No Content. The SPA's `lib/api.js` wrapper assumes every
    response has a JSON content-type; a 204 returns no body and triggers a
    "Server error" path.

    Subclasses may set `destroy_response_message` to customize the body, or
    override destroy()/perform_destroy() entirely.
    """
    destroy_response_message = 'Deleted.'

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response({'message': self.destroy_response_message})


class ConfirmDeleteMixin:
    """
    Two-phase delete confirmation. First DELETE returns 200 with
    `{'confirm_required': True, 'impact': <dict>}`; DELETE ?confirm=true
    actually deletes.

    Subclasses implement:
      - `get_deletion_impact(obj) -> dict` — counts/flags shown to the user.
      - `perform_confirmed_destroy(obj) -> Response` — does the delete and
        returns the success/failure Response.
    """

    def get_deletion_impact(self, obj):
        raise NotImplementedError(
            f'{type(self).__name__}.get_deletion_impact must be implemented.'
        )

    def perform_confirmed_destroy(self, obj):
        raise NotImplementedError(
            f'{type(self).__name__}.perform_confirmed_destroy must be implemented.'
        )

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        confirm = request.query_params.get('confirm', '').lower() == 'true'
        if not confirm:
            return Response({
                'confirm_required': True,
                'impact': self.get_deletion_impact(obj),
            })
        return self.perform_confirmed_destroy(obj)


class QBORetrySyncMixin:
    """Shared retry-sync action: dispatch to a service retry that may return
    None (delete branch) and shape the response uniformly."""
    retry_deleted_message = 'Deleted.'

    def retry_service_call(self, obj, request):
        raise NotImplementedError

    @action(detail=True, methods=['post'], url_path='retry-sync', url_name='retry-sync')
    def retry_sync(self, request, pk=None):
        obj = self.get_object()
        try:
            result = self.retry_service_call(obj, request)
        except ValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        if result is None:
            return Response({'message': self.retry_deleted_message})
        obj.refresh_from_db()
        return Response(self.get_serializer(obj).data)


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
    The service callable receives (pk) or (pk, reason=reason). It may raise
    NotFoundError (-> 404) or ServiceError / Django ValidationError (-> 400).
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
                except ValidationError as e:
                    detail = e.message_dict if hasattr(e, 'message_dict') else e.messages
                    return Response(
                        {'detail': detail},
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
                        record_history(
                            entry_type='audit',
                            object_type=obj_type,
                            object_id=instance.pk,
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
        pli_id = data.get('inventory_item')
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
        qs = model.objects.filter(
            **{self.line_item_parent_field: parent}
        ).order_by('line_number')
        # Estimate/invoice lines serialize adjustment_service details and
        # target categories per row — fetch them up front (no-ops for the
        # line-item models without adjustment fields).
        field_names = {f.name for f in model._meta.get_fields()}
        if 'adjustment_service' in field_names:
            qs = qs.select_related('adjustment_service')
        if 'adjustment_target_categories' in field_names:
            qs = qs.prefetch_related('adjustment_target_categories')
        return qs

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


class JobTaskMixin:
    """
    Adds task CRUD actions to the Job viewset. Works against Task.

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

        from apps.jobs.services import TaskService
        from apps.jobs.models import RateScheme
        data = request.data
        try:
            task = TaskService.create_direct(
                job,
                name=data.get('name', ''),
                rate_scheme_id=data.get('rate_scheme'),
                active_modifiers=data.get('active_modifiers') or [],
                est_qty=data.get('est_qty'),
                est_worker_time=data.get('est_worker_time'),
                actual_qty=data.get('actual_qty'),
                description=data.get('description', ''),
                parent_task_id=data.get('parent_task'),
                assignee_id=data.get('assignee'),
            )
        except RateScheme.DoesNotExist:
            return Response(
                {'detail': {'rate_scheme': 'RateScheme not found.'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as e:
            detail = e.message_dict if hasattr(e, 'message_dict') else (
                e.message if hasattr(e, 'message') else str(e)
            )
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.task_serializer_class(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'patch', 'delete'],
            url_path='tasks/(?P<task_pk>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_pk=None):
        job = self.get_object()
        task = self._get_task_or_404(job, task_pk)

        if request.method == 'GET':
            serializer = self.task_serializer_class(task)
            return Response(serializer.data)

        if request.method == 'DELETE':
            from apps.jobs.services import TaskService as _TaskService
            try:
                _TaskService.delete_task(task.pk)
            except ValidationError as e:
                return Response(
                    {'detail': e.message if hasattr(e, 'message') else str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({'message': 'Task deleted.'})

        # Validate request data via the serializer, then delegate the actual
        # write to TaskService.update_task so the on_hold guard fires.
        serializer = self.task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from apps.jobs.services import TaskService
        try:
            task = TaskService.update_task(task.pk, **serializer.validated_data)
        except ValidationError as e:
            detail = e.message_dict if hasattr(e, 'message_dict') else (
                e.message if hasattr(e, 'message') else str(e)
            )
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.task_serializer_class(task)
        return Response(serializer.data)

    def _get_task_or_404(self, job, task_pk):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_pk, job=job)
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()


class JobScopedPermissionMixin:
    """Resolve a viewset's target Job for CanManageJobOrPM.

    Configure per viewset:
      - job_object_path: attribute chain instance -> Job ('self' for JobViewSet,
        'job', 'estimate.job', 'change_order.job', ...).
      - job_create_field: request.data key naming the parent Job on create.
      - job_url_kwarg: URL kwarg holding the job id (job-nested routes).
    """
    job_object_path = 'job'
    job_create_field = None
    job_url_kwarg = None

    def get_object_job(self, obj):
        if self.job_object_path == 'self':
            return obj
        target = obj
        for part in self.job_object_path.split('.'):
            target = getattr(target, part, None)
            if target is None:
                return None
        return target

    def get_permission_target_job(self, request):
        from apps.jobs.models import Job
        if self.job_url_kwarg and self.kwargs.get(self.job_url_kwarg):
            return Job.objects.filter(pk=self.kwargs[self.job_url_kwarg]).first()
        lookup = self.lookup_url_kwarg or self.lookup_field
        if self.kwargs.get(lookup) is not None:
            model = self.get_queryset().model
            obj = model._default_manager.filter(pk=self.kwargs[lookup]).first()
            if obj is not None:
                return self.get_object_job(obj)
        if self.job_create_field:
            jid = request.data.get(self.job_create_field)
            if jid:
                return Job.objects.filter(pk=jid).first()
        return None


class JobScopedCanManageMixin(serializers.Serializer):
    """Adds read-only `can_manage` = JobService.user_can_manage(request.user,
    <job>). Set `can_manage_job_path` to the chain instance -> Job ('self',
    'job', 'estimate.job', ...). Returns False when there's no request in
    context (e.g. nested serialization without context)."""
    can_manage = serializers.SerializerMethodField()
    can_manage_job_path = 'job'

    def get_can_manage(self, obj):
        from apps.jobs.services import JobService
        request = self.context.get('request')
        if request is None:
            return False
        job = obj
        if self.can_manage_job_path != 'self':
            for part in self.can_manage_job_path.split('.'):
                job = getattr(job, part, None)
                if job is None:
                    return False
        # Resolve the can_manage_jobs atom once per request (cached on the
        # request) so list serialization doesn't re-query auth_permission per
        # row. Atom holders manage every job; otherwise fall back to the
        # per-job PM check, which reads the already-loaded project_manager_id.
        user = request.user
        if not (user and user.is_authenticated):
            return False
        cache_attr = '_can_manage_jobs_atom'
        if not hasattr(request, cache_attr):
            setattr(request, cache_attr,
                    JobService.user_holds_manage_jobs_atom(user))
        if getattr(request, cache_attr):
            return True
        # Atom resolved above; remaining check is the per-job PM match, which
        # reads the already-loaded project_manager_id (no query).
        return job is not None and job.project_manager_id == user.id
