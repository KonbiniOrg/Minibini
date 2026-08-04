from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery, Sum, DecimalField, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Task
from apps.inventory.models import Material, Earmark
from apps.inventory.services import MaterialService
from apps.core.services import NotFoundError, ServiceError
from apps.api.mixins import JobScopedPermissionMixin
from apps.api.permissions import CanManageJobOrPM

_inv_earmarked_subq = Coalesce(
    Subquery(
        Earmark.objects.filter(inventory_item_id=OuterRef('inventory_item_id'))
        .values('inventory_item_id')
        .annotate(total=Sum('quantity'))
        .values('total')
    ),
    Value(Decimal('0.00')),
    output_field=DecimalField(max_digits=10, decimal_places=2),
)


class TaskViewSet(JobScopedPermissionMixin, RetrieveModelMixin, viewsets.GenericViewSet):
    """Flat task endpoints — lifecycle actions, materials, subtasks.

    These operations only need the task id; they live at
    /api/tasks/{task_id}/... (tasks are job-scoped via Task.job).

    Any authenticated user can drive task lifecycle (start, complete,
    block, unblock, cancel) and their own time tracking (start-work,
    stop-work). These are worker operations, not manager-only — cancel
    opened to all workers 2026-07-12 (plan C2: same principal set as
    delete; it is the exit from a task that can no longer be deleted).
    """
    queryset = Task.objects.all()
    lookup_field = 'pk'
    job_object_path = 'job'
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from apps.api.tasks.serializers import TaskDetailSerializer
        return TaskDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        # Pass the job's invoice-claim map so the task's `invoice` field
        # populates (the task view page shows an INVOICED indicator).
        from apps.invoicing.claims import InvoiceClaimService
        task = self.get_object()
        serializer = self.get_serializer(
            task,
            context={**self.get_serializer_context(),
                     'invoice_claims': InvoiceClaimService.claims_for_job(task.job)},
        )
        return Response(serializer.data)

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
            from apps.invoicing.claims import InvoiceClaimService
            materials = Material.objects.filter(task=task).select_related(
                'inventory_item'
            ).annotate(_inv_earmarked=_inv_earmarked_subq)
            serializer = MaterialSerializer(
                materials, many=True,
                context={'invoice_claims': InvoiceClaimService.claims_for_job(task.job)},
            )
            return Response(serializer.data)

        err = self._check_task_mutable(task)
        if err:
            return err
        serializer = MaterialWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        create_data = {k: v for k, v in serializer.validated_data.items()
                       if k != 'propagate_to_pli'}
        mat = MaterialService.create_on_job(
            job=task.job, task=task, **create_data
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
            MaterialService.remove(material)
            return Response({'message': 'Material deleted.'})

        # PATCH — only metadata fields allowed; quantity changes go through
        # /api/materials/{id}/draw-more/ or /api/materials/{id}/restock/.
        QUANTITY_FIELDS = {'quantity', 'released_qty'}
        disallowed = QUANTITY_FIELDS.intersection(request.data.keys())
        if disallowed:
            return Response(
                {'detail': 'Quantity changes must use draw-more or restock actions on /api/materials/{id}/.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = MaterialWriteSerializer(material, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        propagate = fields.pop('propagate_to_pli', False)
        material = MaterialService.update_fields(
            material, propagate_to_pli=propagate, **fields)
        return Response(MaterialSerializer(material).data)

    # --- Subtask CRUD ---

    @action(detail=True, methods=['get', 'post'], url_path='subtasks', url_name='subtasks')
    def subtasks(self, request, pk=None):
        from apps.api.tasks.serializers import TaskSerializer
        task = self.get_object()
        if request.method == 'GET':
            from apps.invoicing.claims import InvoiceClaimService
            children = Task.objects.filter(parent_task=task).order_by('sort_order')
            serializer = TaskSerializer(
                children, many=True,
                context={**self.get_serializer_context(),
                         'invoice_claims': InvoiceClaimService.claims_for_job(task.job)},
            )
            return Response(serializer.data)

        err = self._check_task_mutable(task)
        if err:
            return err
        # Validate the input via the serializer, but CREATE through
        # TaskService.create_direct — the single gate that enforces the
        # on-hold, superseded-scheme, depth, and assignee guards and fires
        # mark_work_reopened (plan A2/B1). Never serializer.save() here.
        from apps.jobs.services import TaskService
        from apps.jobs.models import SchemeInactiveError
        # accounting_category is required=False now (task-owned-money Phase
        # 3, Task 2) — no pre-fill needed to satisfy a required check.
        raw_keys = set(request.data.keys())
        serializer = TaskSerializer(
            data=request.data,
            context={**self.get_serializer_context(), 'job': task.job,
                      'raw_input_keys': raw_keys},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # A permitted caller (already verified by the serializer's
        # MONEY_FIELDS gate) may override the preset's stamped AC —
        # including clearing it to null — by naming the key explicitly; an
        # omitted key rides the stamp untouched. Mirrors JobTaskMixin.tasks.
        money_overrides = {}
        if 'accounting_category' in data:
            money_overrides['accounting_category'] = data['accounting_category']
        try:
            new_task = TaskService.create_direct(
                task.job,
                name=data.get('name', ''),
                rate_scheme_id=data['rate_scheme'].pk if data.get('rate_scheme') else None,
                active_modifiers=data.get('active_modifiers') or [],
                est_qty=data.get('est_qty'),
                est_worker_time=data.get('est_worker_time'),
                actual_qty=data.get('actual_qty'),
                description=data.get('description', ''),
                assignee_id=data['assignee'].pk if data.get('assignee') else None,
                parent_task_id=task.pk,
                qty_scales_with_parent=data.get('qty_scales_with_parent'),
                **money_overrides,
            )
        except SchemeInactiveError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        out = TaskSerializer(new_task, context=self.get_serializer_context())
        return Response(out.data, status=status.HTTP_201_CREATED)

    # --- Deliverables bridge (spec §9 rule 7) ---

    @action(detail=True, methods=['post'], url_path='add-as-deliverable',
            url_name='add-as-deliverable',
            permission_classes=[IsAuthenticated, CanManageJobOrPM])
    def add_as_deliverable(self, request, pk=None):
        """Copy this task into a Deliverable on its job: name -> description,
        est_qty -> qty_ordered, unit_label -> units, linked via
        Deliverable.source_task (provenance only — no sync, no computation
        through it). Same permission as deliverable creation today
        (CanManageJobOrPM — see DeliverableViewSet.get_permissions).

        Rejected when the task already has a linked deliverable (the
        `sourced_deliverables` reverse accessor), when it's a SUBTASK (a
        structure exports from its PARENT only — the parent already
        represents the billed unit), or when it has no est_qty to copy."""
        from apps.deliverables.services import DeliverableService
        from apps.api.deliverables.serializers import DeliverableSerializer
        task = self.get_object()
        if task.parent_task_id is not None:
            return Response(
                {'detail': 'A subtask cannot be added as a deliverable — '
                           'structures export from their parent task.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if task.sourced_deliverables.exists():
            return Response(
                {'detail': 'This task is already linked to a deliverable.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if task.est_qty is None:
            return Response(
                {'detail': 'Task has no quantity — set est_qty before '
                           'adding it as a deliverable.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        deliverable = DeliverableService.create(
            job_id=task.job_id,
            description=task.name,
            qty_ordered=task.est_qty,
            units=task.unit_label,
            source_task=task,
        )
        return Response(
            DeliverableSerializer(
                deliverable, context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        from decimal import Decimal, InvalidOperation
        from apps.jobs.services import (
            TaskLifecycleService, TaskActualQtyRequired, TaskTimeRequired,
        )
        task = self._get_task_or_404(pk)
        raw_qty = request.data.get('add_qty') if request.data else None
        add_qty = None
        if raw_qty is not None and raw_qty != '':
            try:
                add_qty = Decimal(str(raw_qty))
            except (InvalidOperation, ValueError):
                return Response(
                    {'detail': 'Invalid quantity.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            TaskLifecycleService.complete_task(task.pk, add_qty=add_qty)
        except TaskActualQtyRequired as e:
            return Response({
                'needs_actual_qty': True,
                'unit_label': e.unit_label,
                'current_qty': (
                    str(e.current_qty) if e.current_qty is not None else None
                ),
            })
        except TaskTimeRequired:
            return Response({'needs_time_logged': True})
        return Response({'status': Task.STATUS_COMPLETE})

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        reason = request.data.get('reason', '').strip() if request.data else ''
        result = TaskLifecycleService.block_task(
            task.pk, reason=reason, user=request.user,
            prior_qty_handled=bool(request.data.get('prior_qty_handled')),
        )
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
        TaskLifecycleService.unblock_task(task.pk)
        return Response({'status': Task.STATUS_IN_PROGRESS})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        result = TaskLifecycleService.cancel_task(
            task.pk, user=request.user,
            prior_qty_handled=bool(request.data.get('prior_qty_handled')),
        )
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({'status': Task.STATUS_CANCELLED})

    def _resolve_on_behalf_of(self, request):
        """Return (user_or_None, error_response_or_None) for the optional
        `on_behalf_of` user id in the request body."""
        obo_id = request.data.get('on_behalf_of')
        if not obo_id:
            return None, None
        from django.contrib.auth import get_user_model
        target = get_user_model().objects.filter(pk=obo_id).first()
        if target is None:
            return None, Response(
                {'detail': 'Unknown user.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        return target, None

    @action(detail=True, methods=['post'], url_path='start-work')
    def start_work(self, request, pk=None):
        from apps.jobs.services import TaskLifecycleService, BlepPermissionError
        task = self._get_task_or_404(pk)
        on_behalf_of, err = self._resolve_on_behalf_of(request)
        if err:
            return err
        try:
            result = TaskLifecycleService.start_work(
                task.pk, request.user, action=request.data.get('action'),
                on_behalf_of=on_behalf_of,
                prior_qty_handled=bool(request.data.get('prior_qty_handled')),
            )
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({'status': 'ok', 'blep_id': result['blep'].blep_id})

    @action(detail=True, methods=['post'], url_path='stop-work')
    def stop_work(self, request, pk=None):
        from decimal import Decimal, InvalidOperation
        from apps.jobs.services import TaskLifecycleService, BlepPermissionError
        task = self._get_task_or_404(pk)
        on_behalf_of, err = self._resolve_on_behalf_of(request)
        if err:
            return err
        raw_qty = request.data.get('add_qty') if request.data else None
        add_qty = None
        if raw_qty is not None and raw_qty != '':
            try:
                add_qty = Decimal(str(raw_qty))
            except (InvalidOperation, ValueError):
                return Response(
                    {'detail': 'Invalid quantity.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        try:
            result = TaskLifecycleService.stop_work(
                task.pk, request.user, on_behalf_of=on_behalf_of,
                prior_qty_handled=bool(request.data.get('prior_qty_handled')),
                add_qty=add_qty,
            )
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        # Settle-first: own stop on an entered-qty task with an open session
        # returns the conflict (nothing mutated — the session keeps running);
        # the SPA prompts and re-posts with prior_qty_handled (+ add_qty).
        if isinstance(result, dict) and 'conflict' in result:
            return Response(result)
        return Response({'status': 'ok'})

    @action(detail=True, methods=['post'], url_path='cancel-work')
    def cancel_work(self, request, pk=None):
        """Cancel (delete + undo) the requesting user's under-the-minimum blep
        on this task. Own-blep only — no on_behalf_of."""
        from apps.jobs.services import TaskLifecycleService
        task = self._get_task_or_404(pk)
        TaskLifecycleService.cancel_work(task.pk, request.user)
        return Response({'status': 'ok'})

    @action(detail=True, methods=['post'], url_path='actual-qty/add',
            permission_classes=[IsAuthenticated])
    def actual_qty_add(self, request, pk=None):
        """Apply a signed increment to the task's running actual qty.

        Open to any authenticated worker — the entry surfaces (session
        prompt, task-detail add field) are worker gestures. Every write
        is an add; there is no replace endpoint."""
        task = self.get_object()
        qty = request.data.get('actual_qty')
        if qty is None:
            return Response({'actual_qty': ['Required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.services import TaskLifecycleService
        task = TaskLifecycleService.add_actual_qty(task.pk, qty)
        return Response({'actual_qty': str(task.actual_qty)})



