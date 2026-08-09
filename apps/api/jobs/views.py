from decimal import Decimal, InvalidOperation
from apps.core.history import record_history
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q, OuterRef, Subquery, Sum, DecimalField, Value
from django.db.models import Prefetch
from django.db.models.functions import Coalesce
from apps.jobs.models import Job, Task, SchemeInactiveError
from apps.inventory.models import Material, Earmark
from apps.jobs.services import JobService, TaskService
from apps.core.services import NotFoundError, ServiceError
from apps.estimates.models import WorkTemplate, Estimate, ServiceItem
from apps.api.mixins import StatusTransitionMixin, JobTaskMixin, JSONDestroyMixin, JobScopedPermissionMixin
from apps.api.permissions import CanManageJobs, CanManageJobOrPM
from apps.api.history.serializers import HistoryEntrySerializer
from apps.api.tasks.serializers import TaskSerializer
from .serializers import JobSerializer


class JobViewSet(JobScopedPermissionMixin, JSONDestroyMixin, StatusTransitionMixin, JobTaskMixin, viewsets.ModelViewSet):
    job_object_path = 'self'
    queryset = Job.objects.select_related('contact') \
        .prefetch_related(
            Prefetch(
                'tasks',
                queryset=Task.objects.select_related(
                    'assignee', 'source_scheme', 'accounting_category',
                ).prefetch_related('blep_set').order_by('sort_order'),
            ),
            Prefetch(
                'materials',
                queryset=Material.objects.select_related(
                    'inventory_item', 'po_line_item__purchase_order',
                ).annotate(
                    _inv_earmarked=Coalesce(
                        Subquery(
                            Earmark.objects.filter(inventory_item_id=OuterRef('inventory_item_id'))
                            .values('inventory_item_id')
                            .annotate(total=Sum('quantity'))
                            .values('total')
                        ),
                        Value(Decimal('0.00')),
                        output_field=DecimalField(max_digits=10, decimal_places=2),
                    )
                ),
            ),
        ) \
        .all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'
    task_serializer_class = TaskSerializer
    destroy_response_message = 'Job deleted.'

    def destroy(self, request, *args, **kwargs):
        """Hard delete is for unworked jobs only; everything else cancels.

        The cascade would destroy bleps wholesale — recorded work is never
        deleted by a document action (deletion doctrine, Rule 1 at job scale).
        """
        job = self.get_object()
        JobService.assert_job_deletable(job)
        return super().destroy(request, *args, **kwargs)

    def get_permissions(self):
        read_actions = ('list', 'retrieve', 'history', 'notes', 'agreement', 'overview')
        # add-from-template and create_material are IsAuthenticated only (workers
        # can add tasks/materials). task_detail (GET/PATCH/DELETE of a task) is
        # also open: any authenticated user may edit/delete a task. Delete stays
        # guarded by TaskService (in_progress/complete or has Bleps -> 400).
        authenticated_only_actions = ('add_from_template', 'create_material', 'task_detail')
        if self.action in read_actions or self.action in authenticated_only_actions:
            return [IsAuthenticated()]
        if self.action == 'tasks':
            # GET (list) and POST (add a task) are open to any authenticated
            # user — anyone may add a task to a job. task_detail (edit /
            # delete) is likewise open (listed above); the C1 editability
            # matrix in TaskService.update_task and the delete guards in
            # TaskService.delete_task decide. Marking all the job's work
            # complete stays manager-or-PM via the CanManageJobOrPM
            # fall-through below.
            return [IsAuthenticated()]
        if self.action == 'start_invoice_wizard':
            from apps.api.permissions import CanManageFinancials
            return [IsAuthenticated(), (CanManageJobs | CanManageFinancials)()]
        return [IsAuthenticated(), CanManageJobOrPM()]

    def get_queryset(self):
        qs = super().get_queryset()
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        project_manager = self.request.query_params.get('project_manager')
        if project_manager:
            qs = qs.filter(project_manager_id=project_manager)
        # ?open=true — exclude dead jobs (completed / cancelled / rejected).
        # Pickers that attach new work or spend (PO lines) pass it; work_complete
        # stays included (still billable/adjustable until fully completed).
        open_param = self.request.query_params.get('open')
        if open_param is not None and open_param.lower() in ('true', '1', 'yes'):
            qs = qs.exclude(status__in=[
                Job.STATUS_COMPLETED, Job.STATUS_CANCELLED, Job.STATUS_REJECTED,
            ])
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(job_number__icontains=search)
                | Q(name__icontains=search)
                | Q(contact__first_name__icontains=search)
                | Q(contact__last_name__icontains=search)
                | Q(contact__business__business_name__icontains=search)
            )
        return qs

    status_actions = {
        'complete': {'service': lambda pk: JobService.update_job(pk, status=Job.STATUS_COMPLETED)},
        'cancel': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status=Job.STATUS_CANCELLED),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status=Job.STATUS_DRAFT),
            'requires_reason': True,
        },
        # on_hold is a flag, not a status — hold/release toggle it. The
        # reason lands on hold_reason (and, via the mixin, an audit note).
        'hold': {
            'service': lambda pk, reason=None: JobService.hold_job(pk, reason),
            'requires_reason': True,
        },
        'release': {
            'service': lambda pk, reason=None: JobService.release_job(pk),
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = JobService.create_job(**data)
        serializer.instance = job

    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        job = JobService.update_job(self.get_object().pk, **serializer.validated_data)
        serializer.instance = job

    @action(detail=True, methods=['post'], url_path='start-invoice-wizard')
    def start_invoice_wizard(self, request, pk=None):
        """Get or create the draft invoice for this job and return its id."""
        from apps.invoicing.services import InvoiceWizardService
        job = self.get_object()
        invoice = InvoiceWizardService.open_for_job(job)
        return Response({'invoice_id': invoice.pk})

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        from apps.api.jobs.history import build_job_history
        job = self.get_object()
        entries, labels, links = build_job_history(job)
        ctx = {'source_labels': labels, 'source_links': links}
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True, context=ctx)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True, context=ctx)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='notes', url_name='notes')
    def notes(self, request, pk=None):
        obj = self.get_object()
        text = request.data.get('text', '').strip()
        if not text:
            return Response(
                {'text': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = record_history(
            entry_type='note',
            object_type='job',
            object_id=obj.pk,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # --- Phase C2: population / copy actions ---

    @action(detail=True, methods=['post'], url_path='work-complete', url_name='work-complete')
    def work_complete(self, request, pk=None):
        job = self.get_object()
        # B4: with anything not final, mutate nothing and answer with the
        # blocker list (the SPA's "Check Complete" modal). No-mutation +
        # structured-response follows the settle-first conflict precedent.
        blockers = JobService.work_complete_blockers(job)
        if blockers:
            return Response({'blockers': blockers})
        try:
            # Walk approved → in_progress → work_complete if needed.
            if job.status == Job.STATUS_APPROVED:
                job = JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)
            job = JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate(self, request, pk=None):
        """Copy this Job into a new one. Body: {contact_id, path:'approved'|'estimate'}."""
        from apps.contacts.models import Contact
        source_job = self.get_object()
        path = request.data.get('path')
        if path not in ('approved', 'estimate'):
            return Response(
                {'path': ["Must be 'approved' or 'estimate'."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        contact_id = request.data.get('contact_id')
        if not contact_id:
            return Response(
                {'contact_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            contact = Contact.objects.get(pk=contact_id)
        except (Contact.DoesNotExist, ValueError, TypeError):
            # ValueError/TypeError: a non-numeric contact_id would otherwise 500.
            return Response(
                {'contact_id': ['Contact not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_job = JobService.duplicate_job(
            source_job, contact=contact, path=path)
        return Response({'job_id': new_job.pk}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='populate-from-template')
    def populate_from_template(self, request, pk=None):
        job = self.get_object()
        template_pk = request.data.get('template_id')
        if not template_pk:
            return Response(
                {'template_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = WorkTemplate.objects.get(pk=template_pk)
        except WorkTemplate.DoesNotExist:
            return Response(
                {'template_id': ['Template not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            JobService.populate_from_template(job, template)
        except SchemeInactiveError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=['post'], url_path='reorder-tasks')
    def reorder_tasks(self, request, pk=None):
        job = self.get_object()
        task_id = request.data.get('task_id')
        direction = request.data.get('direction')
        if not task_id:
            return Response(
                {'task_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if direction not in ('up', 'down'):
            return Response(
                {'direction': ['Must be "up" or "down".']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Verify the task belongs to this job
        try:
            Task.objects.get(pk=task_id, job=job)
        except Task.DoesNotExist:
            return Response(
                {'task_id': ['Task not found on this job.']},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            TaskService.reorder_tasks(task_id, direction)
        except NotFoundError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'status': 'ok'})

    @action(detail=True, methods=['post'], url_path='materials',
            permission_classes=[IsAuthenticated])
    def create_material(self, request, pk=None):
        from decimal import Decimal as _Decimal
        from apps.inventory.services import MaterialService
        from apps.inventory.models import InventoryItem
        from apps.core.models import AccountingCategory
        from apps.api.inventory.serializers import MaterialSerializer
        job = self.get_object()
        data = request.data
        pli = None
        if data.get('inventory_item'):
            pli = InventoryItem.objects.get(pk=data['inventory_item'])
        ac = None
        if data.get('accounting_category'):
            ac = AccountingCategory.objects.get(pk=data['accounting_category'])
        customer_supplied = data.get('customer_supplied')
        if isinstance(customer_supplied, str):
            customer_supplied = customer_supplied.lower() in ('true', '1', 'yes')
        m = MaterialService.create_on_job(
            job=job, task=None,
            description=data.get('description', ''),
            quantity=_Decimal(str(data.get('quantity', 0))),
            units=data.get('units', 'none'),
            unit_cost=_Decimal(str(data.get('unit_cost', 0))),
            sell_price=_Decimal(str(data.get('sell_price', 0))),
            inventory_item=pli,
            accounting_category=ac,
            customer_supplied=bool(customer_supplied),
        )
        return Response(MaterialSerializer(m).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='agreement', url_name='agreement')
    def agreement(self, request, pk=None):
        """Return the effective agreement for the job: accepted estimate lines with
        each accepted ChangeOrder's deltas applied. Decimals serialized as strings."""
        from decimal import Decimal
        from apps.estimates.agreement import compose_agreement
        job = self.get_object()
        result = compose_agreement(job)

        def _s(v):
            if isinstance(v, Decimal):
                return str(v)
            return v

        serialized_lines = [
            {k: _s(val) for k, val in line.items()}
            for line in result['lines']
        ]
        return Response({
            'lines': serialized_lines,
            'grand_total': str(result['grand_total']),
        })

    @action(detail=True, methods=['get'], url_path='overview', url_name='overview')
    def overview(self, request, pk=None):
        """Aggregate read for the job overview page: due-date countdown,
        labor/materials spend split, and task-progress aggregates. See
        apps.jobs.overview.JobOverviewService."""
        from django.utils import timezone as django_timezone
        from apps.jobs.overview import JobOverviewService
        from apps.schedule.services import load_shop_envelope
        job = self.get_object()
        result = JobOverviewService.summary(
            job,
            today=django_timezone.localdate(),
            envelope=load_shop_envelope(),
        )
        return Response(result)

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        job = self.get_object()
        service_item_id = request.data.get('service_item_id')
        est_qty_raw = request.data.get('est_qty')
        name = request.data.get('name') or None
        description = request.data.get('description')  # None means "not provided"
        active_modifiers = request.data.get('active_modifiers')  # None means use template default
        est_worker_time = request.data.get('est_worker_time') or None

        # Task 12b: this action is IsAuthenticated-only (any worker may stamp
        # a template onto the job), but `active_modifiers` overrides the
        # template's price-affecting defaults — money-equivalent to Task 8's
        # MONEY_FIELDS gate on direct task create/edit. Gate on the RAW key's
        # presence (even `[]`), exactly like TaskSerializer.validate();
        # reuse the same permission evaluation (CanManageJobOrPM or
        # can_manage_financials) rather than reinventing it. Omitted key ->
        # the template's default_active_modifiers ride the stamp, unchanged.
        if 'active_modifiers' in request.data:
            if not (request.user.has_perm('core.can_manage_financials')
                    or JobService.user_can_manage(request.user, job)):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    'Only a manager, the project manager, or financials may '
                    'set active_modifiers.'
                )

        if not service_item_id:
            return Response(
                {'service_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = ServiceItem.objects.get(pk=service_item_id)
        except ServiceItem.DoesNotExist:
            return Response(
                {'service_item_id': ['Task template not found.']},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            est_qty = Decimal(str(est_qty_raw)) if est_qty_raw is not None else Decimal('1')
        except (InvalidOperation, ValueError):
            return Response(
                {'est_qty': ['Invalid decimal value.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            task = template.generate_task(
                job, est_qty,
                name=name,
                description=description,
                active_modifiers=active_modifiers,
                est_worker_time=est_worker_time,
            )
        except SchemeInactiveError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
