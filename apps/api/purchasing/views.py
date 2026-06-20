from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import (
    F, Sum, Value, Case, When, DecimalField, ExpressionWrapper,
    OuterRef, Subquery,
)
from django.db.models.functions import Coalesce
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.purchasing.models import PurchaseOrder, Bill
from apps.purchasing.services import (
    PurchaseOrderService, PurchaseOrderEmailService,
    PurchaseOrderReceivingService, BillService, BillPaymentService,
)
from apps.core.services import ServiceError, NotFoundError
from apps.core.models import PurchasingHistory
from apps.core.history import record_history
from apps.api.mixins import StatusTransitionMixin, LineItemMixin, JSONDestroyMixin
from apps.api.permissions import CanManageFinancials
from apps.api.history.serializers import HistoryEntrySerializer
from .serializers import (
    PurchaseOrderSerializer, POLineItemSerializer,
    BillSerializer, BillSummarySerializer, BillLineItemSerializer,
    BillPaymentSerializer,
)

_BILL_MONEY = DecimalField(max_digits=12, decimal_places=2)

BILL_STATUS_PRESETS = {
    'open': [Bill.STATUS_RECEIVED, Bill.STATUS_PARTLY_PAID],
    'paid': [Bill.STATUS_PAID_IN_FULL],
    'draft': [Bill.STATUS_DRAFT],
    'cancelled': [Bill.STATUS_CANCELLED],
    'refunded': [Bill.STATUS_REFUNDED],
}

BILL_ORDERING = {
    'due_date': F('due_date').asc(nulls_last=True),
    '-due_date': F('due_date').desc(nulls_last=True),
    '-balance': F('balance_anno').desc(nulls_last=True),
    '-total': F('total_anno').desc(nulls_last=True),
    'vendor_name': F('business__business_name').asc(nulls_last=True),
    '-received_date': F('received_date').desc(nulls_last=True),
}


class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().prefetch_related(
        'purchaseorderlineitem_set__task__job',
        'bills',
    ).order_by('-created_date')
    serializer_class = PurchaseOrderSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in (
            'list', 'retrieve', 'history', 'notes', 'send_defaults',
            'receive', 'receive_all', 'receipts', 'cancel_line_item', 'reverse_receipt',
        ):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    def get_queryset(self):
        qs = super().get_queryset()
        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        job = self.request.query_params.get('job')
        if job:
            from apps.inventory.models import Material
            line_ids = Material.objects.filter(
                job=job, po_line_item__isnull=False,
            ).values_list('po_line_item_id', flat=True)
            qs = qs.filter(purchaseorderlineitem__in=line_ids).distinct()
        po_status = self.request.query_params.get('status')
        if po_status:
            qs = qs.filter(status=po_status)
        return qs

    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'
    line_item_service_class = PurchaseOrderService

    # Note: 'cancel' and 'destroy' are explicitly overridden below to accept
    # `sever_decisions`, so we only register 'issue' here.
    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, PurchaseOrder.STATUS_ISSUED),
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = PurchaseOrderService.create_po(**data)
        serializer.instance = po

    def perform_update(self, serializer):
        po = PurchaseOrderService.update_po(self.get_object().pk, **serializer.validated_data)
        serializer.instance = po

    def destroy(self, request, *args, **kwargs):
        """Delete a draft PO. Accepts `sever_decisions` in body for lines
        with pending linked Materials."""
        po = self.get_object()
        sever_decisions = request.data.get('sever_decisions') if request.data else None
        try:
            PurchaseOrderService.delete_po(po.pk, sever_decisions=sever_decisions)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response({'message': f'PO {po.po_number} deleted.'})

    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        """Line-item list (GET) / create (POST). POST accepts transient job, material_id."""
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        service = self.line_item_service_class
        data = request.data.copy()
        pli_id = data.get('inventory_item')
        has_manual_fields = data.get('description') or data.get('price')
        job = data.pop('job', None)
        material_id = data.pop('material_id', None)
        # Strip `task` — reserved field; ignored by this feature
        data.pop('task', None)

        try:
            if pli_id and not has_manual_fields:
                qty = data.get('qty', 0)
                item = service.add_line_item_from_pli(
                    parent.pk, pli_id, qty, job=job, material_id=material_id,
                )
            else:
                if job is not None:
                    data['job'] = job
                if material_id is not None:
                    data['material_id'] = material_id
                item = service.add_line_item(parent.pk, **data)
        except (DjangoValidationError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        """Line-item PATCH/DELETE. PATCH dispatches to change_line_job if payload
        has only 'job' (and optional 'sever_decision')."""
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)
        service = self.line_item_service_class

        if request.method == 'DELETE':
            try:
                service.delete_line_item(item.pk)
            except (DjangoValidationError, NotFoundError) as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'message': 'Line item deleted.'})

        data = request.data.copy()
        job_keys = {'job', 'sever_decision'}
        is_job_only = set(data.keys()).issubset(job_keys) and 'job' in data
        try:
            if is_job_only:
                service.change_line_job(
                    item.pk, data.get('job'), sever_decision=data.get('sever_decision'),
                )
                item.refresh_from_db()
            else:
                # Strip transient/job-routing fields before generic update
                data.pop('job', None)
                data.pop('sever_decision', None)
                data.pop('material_id', None)
                item = service.update_line_item(item.pk, **data)
        except (DjangoValidationError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='cancel', url_name='cancel')
    def cancel(self, request, pk=None):
        """Cancel an issued PO. Accepts `reason` (optional, audit) and
        `sever_decisions` ({line_item_id: 'keep'|'delete'})."""
        reason = request.data.get('reason', '').strip() if request.data else ''
        if not reason:
            return Response(
                {'reason': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sever_decisions = request.data.get('sever_decisions')
        try:
            po = PurchaseOrderService.cancel_po(pk, sever_decisions=sever_decisions)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Audit history entry mirroring StatusTransitionMixin behaviour
        from apps.core.history import get_history_context
        obj_type = po.__class__.__name__.lower()
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
                object_id=po.pk,
                user=request.user if hasattr(request, 'user') and request.user.is_authenticated else None,
                text=reason,
            )

        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        po = self.get_object()
        entries = PurchasingHistory.objects.filter(
            object_type='purchaseorder', object_id=po.pk
        ).select_related('user')
        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = HistoryEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = HistoryEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='send-defaults', url_name='send-defaults')
    def send_defaults(self, request, pk=None):
        """Get pre-populated email fields for sending a PO."""
        po = self.get_object()
        defaults = PurchaseOrderEmailService.get_email_defaults(po)
        return Response(defaults)

    @action(detail=True, methods=['post'], url_path='send', url_name='send')
    def send(self, request, pk=None):
        """Send a PO to the vendor via email with PDF attachment.
        Accepts to/subject/body plus optional cc/bcc (comma-separated)
        and multipart 'attachments' uploads beyond the auto-attached PDF."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        po = self.get_object()
        to = request.data.get('to', '').strip()
        subject = request.data.get('subject', '').strip()
        body = request.data.get('body', '').strip()

        if not to:
            return Response(
                {'to': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not subject:
            return Response(
                {'subject': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cc = [c.strip() for c in request.data.get('cc', '').split(',') if c.strip()]
        bcc = [b.strip() for b in request.data.get('bcc', '').split(',') if b.strip()]
        extra_attachments = []
        for uploaded in request.FILES.getlist('attachments'):
            extra_attachments.append((
                uploaded.name, uploaded.read(),
                uploaded.content_type or 'application/octet-stream',
            ))

        try:
            po = PurchaseOrderEmailService.send_po(
                po, to=to, subject=subject, body=body,
                cc=cc, bcc=bcc, extra_attachments=extra_attachments,
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

        serializer = self.get_serializer(po)
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
            object_type='purchaseorder',
            object_id=obj.pk,
            user=request.user,
            text=text,
        )
        serializer = HistoryEntrySerializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='receive', url_name='receive')
    def receive(self, request, pk=None):
        """Record receipt of specific line items."""
        po = self.get_object()
        items = request.data.get('items', [])
        if not items:
            return Response(
                {'items': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.receive_items(
                po, items, request.user,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='receive-all', url_name='receive-all')
    def receive_all(self, request, pk=None):
        """Receive all remaining items at full quantity."""
        po = self.get_object()
        try:
            po = PurchaseOrderReceivingService.receive_all(po, request.user)
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='cancel-line-item', url_name='cancel-line-item')
    def cancel_line_item(self, request, pk=None):
        """Cancel a line item that won't be shipped. Accepts optional
        `sever_decision` for lines with pending linked Materials."""
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        sever_decision = request.data.get('sever_decision')
        if not line_item_id:
            return Response(
                {'line_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.cancel_line_item(
                po, line_item_id, request.user, note=note,
                sever_decision=sever_decision,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reverse-receipt', url_name='reverse-receipt')
    def reverse_receipt(self, request, pk=None):
        """Reverse all received quantity on a line item."""
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        if not line_item_id:
            return Response(
                {'line_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.reverse_receipt(
                po, line_item_id, request.user, note=note,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = self.get_serializer(po)
        return Response(serializer.data)


class BillViewSet(JSONDestroyMixin, StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Bill.objects.all().order_by('-created_date')
    serializer_class = BillSerializer
    lookup_field = 'pk'
    destroy_response_message = 'Bill deleted.'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]

    def _summary_mode(self):
        """The financials A/P list opts into lightweight summary mode with
        ?summary=true. Without it, the list endpoint keeps its original
        contract (full serializer with line_items, all statuses) for
        pre-existing consumers (Business/Contact detail bill panels, the
        email-associate-bill picker)."""
        return self.request.query_params.get('summary') in ('true', '1')

    def get_serializer_class(self):
        if self.action == 'list' and self._summary_mode():
            return BillSummarySerializer
        return BillSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Filters that apply to all actions (preserve existing business/contact)
        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        purchase_order = self.request.query_params.get('purchase_order')
        if purchase_order:
            qs = qs.filter(purchase_order_id=purchase_order)

        if self.action == 'list' and not self._summary_mode():
            # Non-summary list: BillSerializer reads obj.purchase_order,
            # obj.purchase_order.bills (sibling bills) and each sibling's
            # billlineitem_set (for bill.total), obj.purchase_order's own line
            # items (for po_total / is_fully_billed), plus the bill's own
            # payments and line items.  Prefetch all of these so serializing N
            # bills does not fire per-row queries.
            #
            # Important: billpayment_set / billlineitem_set are only prefetched
            # for the list action because prefetch caches become stale when the
            # payment or line-item actions mutate those relations on the same
            # in-memory Bill instance (causing recompute_payment_status to read
            # the pre-mutation cached set and produce a wrong status).
            return qs.select_related('purchase_order', 'business', 'contact').prefetch_related(
                'purchase_order__bills__billlineitem_set',
                'purchase_order__purchaseorderlineitem_set',
                'billpayment_set',
                'billlineitem_set',
            )

        if not self._summary_mode():
            # Non-list, non-summary (retrieve, payments, line_items, etc.):
            # apply select_related for the PO / billing hints but do NOT
            # prefetch billpayment_set / billlineitem_set so that mutation
            # actions always read fresh data from the DB.
            return qs.select_related('purchase_order', 'business', 'contact').prefetch_related(
                'purchase_order__bills__billlineitem_set',
                'purchase_order__purchaseorderlineitem_set',
            )

        # Summary (financials A/P) mode only: select_related to avoid N+1 from
        # BillSummarySerializer
        qs = qs.select_related('business', 'contact', 'purchase_order')

        # List-only: annotations, status presets, due-date range, ordering.
        # Use a subquery for paid_anno to avoid fan-out when a bill has both
        # multiple line items and multiple payments (two different reverse
        # relations in the same queryset multiply rows in MySQL).
        from apps.purchasing.models import BillPayment
        paid_subquery = Coalesce(
            Subquery(
                BillPayment.objects.filter(bill=OuterRef('pk'))
                .values('bill')
                .annotate(s=Sum('amount'))
                .values('s')[:1],
                output_field=_BILL_MONEY,
            ),
            Value(0), output_field=_BILL_MONEY,
        )
        qs = qs.annotate(
            total_anno=Coalesce(
                Sum(ExpressionWrapper(
                    F('billlineitem__qty') * F('billlineitem__price'),
                    output_field=_BILL_MONEY)),
                Value(0), output_field=_BILL_MONEY),
            paid_anno=paid_subquery,
        ).annotate(
            balance_anno=Case(
                When(
                    status__in=[
                        Bill.STATUS_PAID_IN_FULL,
                        Bill.STATUS_CANCELLED,
                        Bill.STATUS_REFUNDED,
                    ],
                    then=Value(0, output_field=_BILL_MONEY),
                ),
                default=ExpressionWrapper(
                    F('total_anno') - F('paid_anno'), output_field=_BILL_MONEY),
                output_field=_BILL_MONEY,
            ),
        )

        status_param = self.request.query_params.get('status', 'open')
        if status_param != 'all':
            statuses = BILL_STATUS_PRESETS.get(status_param)
            if statuses is not None:
                qs = qs.filter(status__in=statuses)

        due_from = self.request.query_params.get('due_from')
        if due_from:
            qs = qs.filter(due_date__date__gte=due_from)
        due_to = self.request.query_params.get('due_to')
        if due_to:
            qs = qs.filter(due_date__date__lte=due_to)

        ordering = self.request.query_params.get('ordering', 'due_date')
        return qs.order_by(BILL_ORDERING.get(ordering, BILL_ORDERING['due_date']))

    line_item_serializer_class = BillLineItemSerializer
    line_item_parent_field = 'bill'
    line_item_service_class = BillService

    # No partly_paid action: that status will be driven by QBO bill payment sync (deferred).
    status_actions = {
        'receive': {
            'service': lambda pk, reason=None: BillService.update_status(
                pk, Bill.STATUS_RECEIVED),
        },
        'cancel': {
            'service': lambda pk, reason=None: BillService.update_status(
                pk, Bill.STATUS_CANCELLED),
            'requires_reason': True,
        },
    }

    def perform_update(self, serializer):
        try:
            bill = BillService.update_bill(
                serializer.instance.pk, **serializer.validated_data)
        except DjangoValidationError as e:
            detail = e.message_dict if hasattr(e, 'message_dict') else e.messages
            raise DRFValidationError(detail)
        except NotFoundError as e:
            raise NotFound(detail=str(e))
        serializer.instance = bill

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = data.get('purchase_order')
        if po:
            bill = BillService.create_bill_from_po(po.pk if hasattr(po, 'pk') else po)
        else:
            bill = BillService.create_bill(**data)
        serializer.instance = bill

    @action(detail=True, methods=['post'], url_path='payments', url_name='payments')
    def payments(self, request, pk=None):
        bill = self.get_object()
        data = request.data
        try:
            payment = BillPaymentService.record_payment(
                bill,
                amount=data.get('amount'),
                payment_date=data.get('payment_date'),
                method=data.get('method'),
                reference=data.get('reference', ''),
                user=request.user,
            )
        except DjangoValidationError as e:
            return Response({'detail': e.messages if hasattr(e, 'messages') else str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(BillPaymentSerializer(payment).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='payments/(?P<payment_id>[0-9]+)', url_name='payment-detail')
    def payment_detail(self, request, pk=None, payment_id=None):
        self.get_object()  # permission + existence check on the bill
        try:
            if request.method == 'DELETE':
                BillPaymentService.delete_payment(int(payment_id))
                return Response({'message': 'Payment deleted.'})
            payment = BillPaymentService.update_payment(int(payment_id), **request.data)
        except DjangoValidationError as e:
            return Response({'detail': e.messages if hasattr(e, 'messages') else str(e)},
                            status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as e:
            return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(BillPaymentSerializer(payment).data)

    @action(detail=True, methods=['post'], url_path='send-to-qbo')
    def send_to_qbo(self, request, pk=None):
        """Push this bill to QBO."""
        bill = self.get_object()
        try:
            from apps.qbo.services import QBOBillSyncService
            qbo_id = QBOBillSyncService.push_bill(bill)
            return Response({'qbo_id': qbo_id, 'status': 'synced'})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
