from datetime import timedelta
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import (
    F, Sum, Value, DecimalField, DateTimeField, ExpressionWrapper,
)
from django.db.models.functions import Coalesce
from rest_framework import serializers as drf_serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService, InvoiceWizardService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from apps.api.permissions import CanManageFinancials, CanManageJobs
from .serializers import (
    InvoiceSerializer, InvoiceLineItemSerializer, InvoiceSummarySerializer,
    DEFAULT_INVOICE_NET_DAYS,
)


_MONEY = DecimalField(max_digits=12, decimal_places=2)

INVOICE_STATUS_PRESETS = {
    'open': [Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID],
    'paid': [Invoice.STATUS_PAID],
    'draft': [Invoice.STATUS_DRAFT],
    'cancelled': [Invoice.STATUS_CANCELLED],
}

INVOICE_ORDERING = {
    'due_date': F('due_date_anno').asc(nulls_last=True),
    '-due_date': F('due_date_anno').desc(nulls_last=True),
    '-balance': F('balance_anno').desc(nulls_last=True),
    '-total': F('total_anno').desc(nulls_last=True),
    'customer_name': F('customer_sort').asc(nulls_last=True),
    '-sent_date': F('sent_date').desc(nulls_last=True),
}


class InvoiceViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Invoice.objects.all().order_by('-created_date')
    serializer_class = InvoiceSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        if self.action == 'create':
            return [IsAuthenticated(), (CanManageJobs | CanManageFinancials)()]
        return [IsAuthenticated(), CanManageFinancials()]

    # Line item mixin config
    line_item_serializer_class = InvoiceLineItemSerializer
    line_item_parent_field = 'invoice'
    line_item_service_class = InvoiceService

    status_actions = {
        'cancel': {
            'service': InvoiceService.cancel,
            'requires_reason': True,
        },
    }

    def _summary_mode(self):
        """The financials A/R list opts into lightweight summary mode with
        ?summary=true. Without it, the list endpoint keeps its original
        contract (full serializer with line_items, all statuses) for
        pre-existing consumers like the Job overview (/api/invoices/?job=)."""
        return self.request.query_params.get('summary') in ('true', '1')

    def get_serializer_class(self):
        if self.action == 'list' and self._summary_mode():
            return InvoiceSummarySerializer
        return InvoiceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)

        if not (self.action == 'list' and self._summary_mode()):
            return qs

        # Summary (financials A/R) mode only: select_related to avoid N+1 from
        # InvoiceSummarySerializer
        qs = qs.select_related('job', 'job__contact', 'job__contact__business')

        qs = qs.annotate(
            total_anno=Coalesce(
                Sum(ExpressionWrapper(
                    F('invoicelineitem__qty') * F('invoicelineitem__price'),
                    output_field=_MONEY)),
                Value(0), output_field=_MONEY),
            amount_paid_anno=Coalesce(F('qbo_amount_paid'), Value(0),
                                      output_field=_MONEY),
            due_date_anno=ExpressionWrapper(
                F('sent_date') + timedelta(days=DEFAULT_INVOICE_NET_DAYS),
                output_field=DateTimeField()),
            customer_sort=Coalesce(
                F('job__contact__business__business_name'),
                F('job__contact__last_name'),
                Value('')),
        ).annotate(
            balance_anno=ExpressionWrapper(
                F('total_anno') - F('amount_paid_anno'), output_field=_MONEY),
        )

        status_param = self.request.query_params.get('status', 'open')
        if status_param != 'all':
            statuses = INVOICE_STATUS_PRESETS.get(status_param)
            if statuses is not None:
                qs = qs.filter(status__in=statuses)

        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(job__contact__business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(job__contact_id=contact)

        due_from = self.request.query_params.get('due_from')
        if due_from:
            qs = qs.filter(due_date_anno__date__gte=due_from)
        due_to = self.request.query_params.get('due_to')
        if due_to:
            qs = qs.filter(due_date_anno__date__lte=due_to)

        ordering = self.request.query_params.get('ordering', 'due_date')
        return qs.order_by(INVOICE_ORDERING.get(ordering,
                                                INVOICE_ORDERING['due_date']))

    def perform_create(self, serializer):
        job = serializer.validated_data.get('job')
        try:
            invoice = InvoiceWizardService.open_for_job(job)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            raise drf_serializers.ValidationError({'detail': msg})
        serializer.instance = invoice

    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        try:
            InvoiceService.discard_draft(invoice)
        except DjangoValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': 'Invoice discarded'})

    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool tree for the wizard."""
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        pool = InvoiceWizardService.get_source_pool(invoice)
        # Decimals need to be serialized as strings
        return Response(_serialize_pool(pool))

    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new line item from a list of atoms."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict
        invoice = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = InvoiceWizardService.add_atoms_to_new_line_item(invoice, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=201)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        atoms = request.data.get('atoms', [])
        try:
            InvoiceWizardService.add_atoms_to_line_item(line_item, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        line_item.refresh_from_db()
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=200)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        source_ids = request.data.get('source_ids', [])
        try:
            result = InvoiceWizardService.remove_atoms_from_line_item(
                line_item, source_ids,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': InvoiceLineItemSerializer(line_item).data,
        })

    @action(detail=True, methods=['get'], url_path='send-defaults')
    def send_defaults(self, request, pk=None):
        """Pre-populated values for the Send Email page."""
        from apps.invoicing.services import InvoiceEmailService
        invoice = self.get_object()
        return Response(InvoiceEmailService.get_email_defaults(invoice))

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """Send the invoice via the tracked outbound flow. Pushes to QBO
        if needed, attaches both QBO and Job Statement PDFs, transitions
        draft -> open on success. Multipart 'attachments' files append
        to the auto-attached PDFs."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        from apps.invoicing.services import InvoiceEmailService

        invoice = self.get_object()
        to = request.data.get('to', '').strip()
        if not to:
            return Response(
                {'to': ['Recipient email address is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        subject = request.data.get('subject', '')
        body = request.data.get('body', '')
        cc = [c.strip() for c in request.data.get('cc', '').split(',') if c.strip()]
        bcc = [b.strip() for b in request.data.get('bcc', '').split(',') if b.strip()]
        extra_attachments = []
        for uploaded in request.FILES.getlist('attachments'):
            extra_attachments.append((
                uploaded.name, uploaded.read(),
                uploaded.content_type or 'application/octet-stream',
            ))

        try:
            record = InvoiceEmailService.send_invoice(
                invoice,
                to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                extra_attachments=extra_attachments,
                user=request.user,
            )
        except DjangoValidationError as e:
            return Response(
                {'detail': e.messages if hasattr(e, 'messages') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({
            'email_record_id': record.email_record_id,
            'invoice_status': invoice.status,
            'qbo_id': invoice.qbo_id,
        })


def _serialize_pool(pool):
    """Convert Decimal values in the pool structure to strings for JSON."""
    from decimal import Decimal
    def _s(value):
        if isinstance(value, Decimal):
            return str(value)
        return value
    return {
        'tasks': [
            {
                'task_id': t['task_id'],
                'name': t['name'],
                'has_billable_atoms': t['has_billable_atoms'],
                'atoms': [
                    {k: _s(v) for k, v in atom.items()}
                    for atom in t['atoms']
                ],
            }
            for t in pool['tasks']
        ],
    }
