from decimal import Decimal, InvalidOperation
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
from apps.core.models import HistoryEntry
from apps.core.services import NotFoundError, ServiceError
from apps.estimates.models import WorkTemplate, Estimate, EstWorksheet, TaskTemplate
from apps.api.mixins import StatusTransitionMixin, JobTaskMixin
from apps.api.permissions import CanManageJobs
from apps.api.history.serializers import HistoryEntrySerializer
from apps.api.tasks.serializers import TaskSerializer
from .serializers import JobSerializer


class JobViewSet(StatusTransitionMixin, JobTaskMixin, viewsets.ModelViewSet):
    queryset = Job.objects.select_related('contact', 'template') \
        .prefetch_related(
            Prefetch('tasks', queryset=Task.objects.select_related('assignee').order_by('sort_order')),
            Prefetch('materials', queryset=Material.objects.select_related('price_list_item')),
            'template__templatetaskassociation_set__task_template',
            'template__bundles',
        ) \
        .all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'
    task_serializer_class = TaskSerializer

    def get_permissions(self):
        read_actions = ('list', 'retrieve', 'history', 'notes')
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
        job = self.get_object()
        from apps.invoicing.models import Invoice

        estimate_ids = list(Estimate.objects.filter(job=job).values_list('pk', flat=True))
        worksheet_ids = list(EstWorksheet.objects.filter(job=job).values_list('pk', flat=True))
        invoice_ids = list(Invoice.objects.filter(job=job).values_list('pk', flat=True))

        q = Q(object_type='job', object_id=job.pk)
        if estimate_ids:
            q |= Q(object_type='estimate', object_id__in=estimate_ids)
        if worksheet_ids:
            q |= Q(object_type='estworksheet', object_id__in=worksheet_ids)
        if invoice_ids:
            q |= Q(object_type='invoice', object_id__in=invoice_ids)

        entries = HistoryEntry.objects.filter(q).select_related('user')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
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
        entry = HistoryEntry.objects.create(
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
        except ValidationError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.refresh_from_db()
        return Response(self.get_serializer(job).data)

    @action(detail=True, methods=['post'], url_path='populate-from-estimate')
    def populate_from_estimate(self, request, pk=None):
        job = self.get_object()
        estimate_pk = request.data.get('estimate_id')
        if not estimate_pk:
            return Response(
                {'estimate_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            return Response(
                {'estimate_id': ['Estimate not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            JobService.populate_from_estimate(job, estimate)
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
            JobService.copy_from_worksheet(job.pk, ws.pk, template=ws.template)
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
                unit_cost=_Decimal(str(data.get('unit_cost', 0))),
                sell_price=_Decimal(str(data.get('sell_price', 0))),
                price_list_item=pli,
                accounting_category=ac,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MaterialSerializer(m).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='add-from-template')
    def add_from_template(self, request, pk=None):
        job = self.get_object()
        task_template_id = request.data.get('task_template_id')
        est_qty_raw = request.data.get('est_qty')

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
        task = template.generate_task(job, est_qty)
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
