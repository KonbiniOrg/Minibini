from datetime import timedelta
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import (
    Exists, F, OuterRef, Sum, Value, DecimalField, DateTimeField,
    ExpressionWrapper,
)
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
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
    # select_related('job'): display_number and job_number both read the job.
    queryset = Invoice.objects.select_related('job').order_by('-created_date')
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

    def perform_update(self, serializer):
        # `job` is create-only (set via open_for_job); an invoice never moves
        # between jobs — claims against another job's atoms would be
        # incoherent. Silently create-only, like other immutable-on-edit fields.
        serializer.validated_data.pop('job', None)
        serializer.save()

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

    def get_serializer_context(self):
        # Resolved once per request (memoized on the view instance) and
        # handed down to every InvoiceLineItemSerializer row via context
        # (nested `line_items` field inherits the root serializer's
        # context automatically) — mirrors AccountingCategoryViewSet's
        # is_fallback wiring (apps/api/templates_config/views.py,
        # commit de071827). used_fallback_ac reads this key.
        context = super().get_serializer_context()
        context['fallback_category_id'] = self._fallback_category_id()
        return context

    def _fallback_category_id(self):
        if not hasattr(self, '_cached_fallback_category_id'):
            from apps.api.templates_config.serializers import (
                _resolve_fallback_category_id,
            )
            self._cached_fallback_category_id = _resolve_fallback_category_id()
        return self._cached_fallback_category_id

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)

        if not (self.action == 'list' and self._summary_mode()):
            # Detail/list (non-summary) path: prefetch line items' sources,
            # accounting_category, and a CO ref's own change_order so
            # InvoiceSerializer.get_is_deposit / the per-line agreement_ref's
            # co_number don't N+1 across invoicelineitem_set.
            return qs.prefetch_related(
                'invoicelineitem_set__sources',
                'invoicelineitem_set__accounting_category',
                'invoicelineitem_set__agreement_co_line__change_order',
            )

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

        deposit_line = (
            InvoiceLineItem.objects
            .filter(invoice=OuterRef('pk'),
                    accounting_category__is_deposit=True)
            .exclude(sources__source_type=InvoiceLineItemSource.SOURCE_DEPOSIT)
        )
        qs = qs.annotate(has_deposit=Exists(deposit_line))

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
        seed = self.request.data.get('seed', True)
        serializer.instance = InvoiceWizardService.open_for_job(job, seed=seed)

    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        InvoiceService.discard_draft(invoice)
        return Response({'message': 'Invoice discarded'})

    @action(detail=True, methods=['post'], url_path='send-all-atoms')
    def send_all_atoms(self, request, pk=None):
        """Project every available atom onto the invoice, one line per atom
        (the wizard's one-click "send all"). Unlike apply-everything
        (seed_all_atoms), this composes with existing lines."""
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        created = InvoiceWizardService.send_all_atoms(invoice)
        return Response({'created': created}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool tree for the wizard."""
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        pool = InvoiceWizardService.get_source_pool(invoice)
        # Decimals need to be serialized as strings
        return Response(_serialize_pool(pool))

    @action(detail=True, methods=['post'], url_path='line-items-from-service')
    def line_items_from_service(self, request, pk=None):
        """Ad-hoc service billing line (no Task, no atoms)."""
        from apps.core.services import NotFoundError
        invoice = self.get_object()
        try:
            line_item = InvoiceService.add_line_item_from_service(
                invoice.pk,
                request.data.get('service_item'),
                request.data.get('qty'),
            )
        except NotFoundError as e:
            return Response({'detail': str(e)},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = InvoiceLineItemSerializer(
            line_item, context=self.get_serializer_context())
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new line item from a list of atoms."""
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict
        invoice = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = InvoiceWizardService.add_atoms_to_new_line_item(invoice, atoms)
        except ClaimConflict as e:
            return Response(
                {'detail': 'Some of these atoms are already claimed by another invoice.',
                 'code': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        serializer = InvoiceLineItemSerializer(
            line_item, context=self.get_serializer_context())
        return Response(serializer.data, status=201)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'detail': 'Line item not found'}, status=404)

        atoms = request.data.get('atoms', [])
        try:
            InvoiceWizardService.add_atoms_to_line_item(line_item, atoms)
        except ClaimConflict as e:
            return Response(
                {'detail': 'Some of these atoms are already claimed by another invoice.',
                 'code': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )

        line_item.refresh_from_db()
        serializer = InvoiceLineItemSerializer(
            line_item, context=self.get_serializer_context())
        return Response(serializer.data, status=200)

    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'detail': 'Line item not found'}, status=404)

        source_ids = request.data.get('source_ids', [])
        result = InvoiceWizardService.remove_atoms_from_line_item(
            line_item, source_ids,
        )

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': InvoiceLineItemSerializer(
                line_item, context=self.get_serializer_context()).data,
        })

    @action(detail=True, methods=['post'], url_path='apply-everything')
    def apply_everything(self, request, pk=None):
        """Seed all available atoms onto a fresh draft invoice, one line per atom.

        Requires the invoice to be draft with no existing line items.
        Already-claimed and not-billable atoms are skipped automatically.
        Returns 200 with ``{'created': N}`` on success, 400 on ValidationError.
        """
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        created = InvoiceWizardService.seed_all_atoms(invoice)
        return Response({'created': created}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='copy-from-estimate')
    def copy_from_estimate(self, request, pk=None):
        """Copy the job's accepted estimate agreement onto a fresh draft invoice.

        Creates one InvoiceLineItem per agreement line, including adjustment lines
        (which carry adjustment_service so the agreement panel sees them as
        already_added). Only available when the invoice is draft, has no lines, and
        is the first/only non-cancelled invoice for the job.

        Returns 200 with ``{'created': N}`` on success, 400 on ValidationError.
        """
        from apps.invoicing.services import InvoiceService
        invoice = self.get_object()
        created = InvoiceService.copy_from_estimate(invoice)
        return Response({'created': created}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='adjustment-lines')
    def adjustment_lines(self, request, pk=None):
        """Add a percentage-adjustment line item to a draft invoice.

        Body: ``adjustment_service`` (RateScheme PK, must be PERCENTAGE),
        ``target_category_ids`` (list of AccountingCategory PKs; empty = all).
        Returns 201 with the serialized line item.
        Returns 400 when the invoice is not draft or the service is not PERCENTAGE.
        """
        from apps.invoicing.services import InvoiceService
        invoice = self.get_object()
        line = InvoiceService.add_adjustment_line(
            invoice,
            adjustment_service_id=request.data['adjustment_service'],
            target_category_ids=request.data.get('target_category_ids') or [],
        )
        return Response(
            InvoiceLineItemSerializer(line, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='agreement-adjustments')
    def agreement_adjustments(self, request, pk=None):
        """Return the adjustment lines from the job's accepted estimate agreement,
        annotated with whether this invoice already has a line for each one.

        Returns ``{'adjustments': [{adjustment_service_id, description, percent,
        target_category_ids, already_added}, ...]}``.
        Already_added is True when this invoice already has an InvoiceLineItem
        with that adjustment_service.
        """
        from apps.estimates.agreement import compose_agreement
        from apps.invoicing.models import InvoiceLineItem
        invoice = self.get_object()
        agreement = compose_agreement(invoice.job)
        existing = set(
            InvoiceLineItem.objects
            .filter(invoice=invoice, adjustment_service__isnull=False)
            .values_list('adjustment_service_id', flat=True)
        )
        out = [
            {
                'adjustment_service_id': l['adjustment_service_id'],
                'description': l['description'],
                'percent': l['percent'],
                'target_category_ids': l['target_category_ids'],
                'already_added': l['adjustment_service_id'] in existing,
            }
            for l in agreement['lines'] if l.get('is_adjustment')
        ]
        return Response({'adjustments': out})

    @action(detail=True, methods=['get'], url_path='remaining-agreement-lines')
    def remaining_agreement_lines(self, request, pk=None):
        """List agreement lines not yet on any live invoice for this job —
        feeds the restore picker."""
        invoice = self.get_object()
        lines = InvoiceService.remaining_agreement_lines(invoice.job)
        return Response({'lines': [_serialize_agreement_line(l) for l in lines]})

    @action(detail=True, methods=['post'], url_path='restore-line')
    def restore_line(self, request, pk=None):
        """Re-add a single agreement line to this draft. Body:
        {estimate_line_id} or {co_line_id} (exactly one). Returns 201 with
        the serialized new line item."""
        invoice = self.get_object()
        line = InvoiceService.restore_agreement_line(
            invoice,
            estimate_line_id=request.data.get('estimate_line_id'),
            co_line_id=request.data.get('co_line_id'),
        )
        serializer = InvoiceLineItemSerializer(
            line, context=self.get_serializer_context())
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='send-defaults')
    def send_defaults(self, request, pk=None):
        """Pre-populated values for the Send Email page."""
        from apps.invoicing.services import InvoiceEmailService
        invoice = self.get_object()
        return Response(InvoiceEmailService.get_email_defaults(invoice, user=request.user))

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """Send the invoice via the tracked outbound flow. Pushes to QBO
        if needed, attaches both QBO and Job Statement PDFs, transitions
        draft -> open on success. Multipart 'attachments' files append
        to the auto-attached PDFs."""
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
            )
        except DjangoValidationError:
            # plain validation errors render via the contract handler
            raise
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


def _serialize_agreement_line(line):
    """Convert Decimal values in a compose_agreement line dict to strings
    for JSON — used by the remaining-agreement-lines restore-picker feed."""
    from decimal import Decimal
    return {
        k: (str(v) if isinstance(v, Decimal) else v)
        for k, v in line.items()
    }


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
