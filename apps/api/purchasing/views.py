from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.purchasing.models import PurchaseOrder, Bill
from apps.purchasing.services import (
    PurchaseOrderService, PurchaseOrderEmailService,
    PurchaseOrderReceivingService, BillService,
)
from apps.core.services import ServiceError
from apps.core.models import HistoryEntry
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from apps.api.permissions import CanManageFinancials
from apps.api.history.serializers import HistoryEntrySerializer
from .serializers import (
    PurchaseOrderSerializer, POLineItemSerializer,
    BillSerializer, BillLineItemSerializer,
)


class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().prefetch_related(
        'purchaseorderlineitem_set__task__job',
        'purchaseorderlineitem_set__job',
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
            qs = qs.filter(purchaseorderlineitem__job=job).distinct()
        po_status = self.request.query_params.get('status')
        if po_status:
            qs = qs.filter(status=po_status)
        return qs

    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'
    line_item_service_class = PurchaseOrderService

    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, PurchaseOrder.STATUS_ISSUED),
        },
        'cancel': {
            'service': lambda pk, reason=None: PurchaseOrderService.cancel_po(pk),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = PurchaseOrderService.create_po(**data)
        serializer.instance = po

    def perform_update(self, serializer):
        po = PurchaseOrderService.update_po(self.get_object().pk, **serializer.validated_data)
        serializer.instance = po

    @action(detail=True, methods=['get'], url_path='history', url_name='history')
    def history(self, request, pk=None):
        po = self.get_object()
        entries = HistoryEntry.objects.filter(
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
        """Send a PO to the vendor via email with PDF attachment."""
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

        try:
            po = PurchaseOrderEmailService.send_po(
                po, to=to, subject=subject, body=body,
                user=request.user,
            )
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
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
        entry = HistoryEntry.objects.create(
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
        """Cancel a line item that won't be shipped."""
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        if not line_item_id:
            return Response(
                {'line_item_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            po = PurchaseOrderReceivingService.cancel_line_item(
                po, line_item_id, request.user, note=note,
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


class BillViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Bill.objects.all().order_by('-created_date')
    serializer_class = BillSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
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
        return qs

    line_item_serializer_class = BillLineItemSerializer
    line_item_parent_field = 'bill'
    line_item_service_class = BillService

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: BillService.update_status(pk, Bill.STATUS_CANCELLED),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = data.get('purchase_order')
        if po:
            bill = BillService.create_bill_from_po(po.pk if hasattr(po, 'pk') else po)
        else:
            bill = BillService.create_bill(**data)
        serializer.instance = bill

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
