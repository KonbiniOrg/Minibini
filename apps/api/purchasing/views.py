from rest_framework import viewsets
from apps.purchasing.models import PurchaseOrder, Bill
from apps.purchasing.services import PurchaseOrderService, BillService
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import (
    PurchaseOrderSerializer, POLineItemSerializer,
    BillSerializer, BillLineItemSerializer,
)


class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().order_by('-created_date')
    serializer_class = PurchaseOrderSerializer
    lookup_field = 'pk'

    def get_queryset(self):
        qs = super().get_queryset()
        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)
        return qs

    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'

    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, 'issued'),
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


class BillViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Bill.objects.all().order_by('-created_date')
    serializer_class = BillSerializer
    lookup_field = 'pk'

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

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: BillService.update_status(pk, 'cancelled'),
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
