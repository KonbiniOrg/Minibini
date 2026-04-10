from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.core.models import HistoryEntry
from apps.api.mixins import StatusTransitionMixin
from apps.api.permissions import CanManageJobs
from apps.api.history.serializers import HistoryEntrySerializer
from .serializers import JobSerializer


class JobViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
    queryset = Job.objects.all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes'):
            return [IsAuthenticated()]
        if self.action == 'start_invoice_wizard':
            from apps.api.permissions import CanManageFinancials
            return [IsAuthenticated(), CanManageFinancials()]
        return [IsAuthenticated(), CanManageJobs()]

    def get_queryset(self):
        qs = super().get_queryset()
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
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
        from django.core.exceptions import ValidationError
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
        from apps.estimates.models import Estimate, EstWorksheet
        from apps.jobs.models import WorkOrder
        from apps.invoicing.models import Invoice

        estimate_ids = list(Estimate.objects.filter(job=job).values_list('pk', flat=True))
        worksheet_ids = list(EstWorksheet.objects.filter(job=job).values_list('pk', flat=True))
        wo_ids = list(WorkOrder.objects.filter(job=job).values_list('pk', flat=True))
        invoice_ids = list(Invoice.objects.filter(job=job).values_list('pk', flat=True))

        q = Q(object_type='job', object_id=job.pk)
        if estimate_ids:
            q |= Q(object_type='estimate', object_id__in=estimate_ids)
        if worksheet_ids:
            q |= Q(object_type='estworksheet', object_id__in=worksheet_ids)
        if wo_ids:
            q |= Q(object_type='workorder', object_id__in=wo_ids)
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
