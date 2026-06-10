from decimal import Decimal, InvalidOperation
from apps.core.history import record_history
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models import Prefetch
from apps.jobs.models import Job, Task
from apps.inventory.models import Material
from apps.jobs.services import JobService, TaskService
from apps.core.services import NotFoundError, ServiceError, SchemeSupersededError
from apps.estimates.models import WorkTemplate, Estimate, EstWorksheet, TaskTemplate
from apps.api.mixins import StatusTransitionMixin, JobTaskMixin, JSONDestroyMixin
from apps.api.permissions import CanManageJobs
from apps.api.history.serializers import HistoryEntrySerializer
from apps.api.tasks.serializers import TaskSerializer
from .serializers import JobSerializer


class JobViewSet(JSONDestroyMixin, StatusTransitionMixin, JobTaskMixin, viewsets.ModelViewSet):
    queryset = Job.objects.select_related('contact') \
        .prefetch_related(
            Prefetch(
                'tasks',
                queryset=Task.objects.select_related(
                    'assignee', 'rate_scheme', 'source_plan_task',
                ).prefetch_related('blep_set').order_by('sort_order'),
            ),
            Prefetch(
                'materials',
                queryset=Material.objects.select_related(
                    'price_list_item', 'po_line_item__purchase_order',
                ),
            ),
        ) \
        .all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'
    task_serializer_class = TaskSerializer
    destroy_response_message = 'Job deleted.'

    def get_permissions(self):
        read_actions = ('list', 'retrieve', 'history', 'notes', 'agreement')
        # add-from-template and create_material are IsAuthenticated only (workers can add tasks/materials)
        authenticated_only_actions = ('add_from_template', 'create_material')
        if self.action in read_actions or self.action in authenticated_only_actions:
            return [IsAuthenticated()]
        if self.action == 'tasks':
            # GET open to any authenticated user; POST requires can_manage_jobs
            if self.request.method == 'GET':
                return [IsAuthenticated()]
            return [IsAuthenticated(), CanManageJobs()]
        if self.action == 'start_invoice_wizard':
            from apps.api.permissions import CanManageFinancials
            return [IsAuthenticated(), (CanManageJobs | CanManageFinancials)()]
        return [IsAuthenticated(), CanManageJobs()]

    def get_queryset(self):
        qs = super().get_queryset()
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        project_manager = self.request.query_params.get('project_manager')
        if project_manager:
            qs = qs.filter(project_manager_id=project_manager)
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
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = JobService.create_job(**data)
        serializer.instance = job

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except ValidationError as e:
            msg = '; '.join(e.messages) if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)

    def perform_update(self, serializer):
        job = JobService.update_job(self.get_object().pk, **serializer.validated_data)
        serializer.instance = job

    @action(detail=True, methods=['post'], url_path='start-invoice-wizard')
    def start_invoice_wizard(self, request, pk=None):
        """Get or create the draft invoice for this job and return its id."""
        from apps.invoicing.services import InvoiceWizardService
        job = self.get_object()
        try:
            invoice = InvoiceWizardService.open_for_job(job)
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
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
            user=request.user,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # --- Phase C2: population / copy actions ---

    @action(detail=True, methods=['post'], url_path='work-complete', url_name='work-complete')
    def work_complete(self, request, pk=None):
        job = self.get_object()
        try:
            # Walk approved → in_progress → work_complete if needed.
            if job.status == Job.STATUS_APPROVED:
                job = JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)
            job = JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)
        except ValidationError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        try:
            new_job = JobService.duplicate_job(
                source_job, contact=contact, path=path)
        except ValidationError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        except SchemeSupersededError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=['post'], url_path='copy-from-worksheet')
    def copy_from_worksheet(self, request, pk=None):
        job = self.get_object()
        worksheet_pk = request.data.get('worksheet_id')
        if not worksheet_pk:
            return Response(
                {'worksheet_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            return Response(
                {'worksheet_id': ['Worksheet not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            JobService.copy_from_worksheet(job.pk, ws.pk)
        except (ValidationError, NotFoundError) as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        except (ValidationError, NotFoundError) as e:
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
        from apps.inventory.models import PriceListItem
        from apps.core.models import AccountingCategory
        from apps.api.inventory.serializers import MaterialSerializer
        job = self.get_object()
        data = request.data
        pli = None
        if data.get('price_list_item'):
            pli = PriceListItem.objects.get(pk=data['price_list_item'])
        ac = None
        if data.get('accounting_category'):
            ac = AccountingCategory.objects.get(pk=data['accounting_category'])
        try:
            m = MaterialService.create_on_job(
                job=job, task=None,
                description=data.get('description', ''),
                quantity=_Decimal(str(data.get('quantity', 0))),
                units=data.get('units', 'none'),
                unit_cost=_Decimal(str(data.get('unit_cost', 0))),
                sell_price=_Decimal(str(data.get('sell_price', 0))),
                price_list_item=pli,
                accounting_category=ac,
            )
        except ValidationError as e:
            # Surface field-level errors as {field: [messages]} so the SPA
            # can format each line; fall back to a flat detail otherwise.
            if hasattr(e, 'message_dict'):
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
            return Response({'detail': '; '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
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

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        job = self.get_object()
        task_template_id = request.data.get('task_template_id')
        est_qty_raw = request.data.get('est_qty')
        name = request.data.get('name') or None
        description = request.data.get('description')  # None means "not provided"
        active_modifiers = request.data.get('active_modifiers')  # None means use template default
        est_worker_time = request.data.get('est_worker_time') or None

        if not task_template_id:
            return Response(
                {'task_template_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            template = TaskTemplate.objects.get(pk=task_template_id)
        except TaskTemplate.DoesNotExist:
            return Response(
                {'task_template_id': ['Task template not found.']},
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
        except SchemeSupersededError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
