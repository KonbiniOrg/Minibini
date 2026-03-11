from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem


class POLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price', 'job',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items = POLineItemSerializer(
        source='purchaseorderlineitem_set', many=True, read_only=True
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'contact', 'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items',
        ]
        read_only_fields = ['po_id', 'po_number', 'created_date']


class BillLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class BillSerializer(serializers.ModelSerializer):
    line_items = BillLineItemSerializer(
        source='billlineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Bill
        fields = [
            'bill_id', 'purchase_order', 'vendor_invoice_number',
            'business', 'contact', 'bill_number', 'status',
            'created_date', 'received_date', 'cancelled_date', 'line_items',
        ]
        read_only_fields = ['bill_id', 'bill_number', 'created_date']
