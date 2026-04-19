from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem
from apps.core.units import UnitsField


class PurchaseOrderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = ['po_id', 'po_number', 'status', 'created_date']


class BillSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Bill
        fields = ['bill_id', 'bill_number', 'status', 'vendor_invoice_number', 'created_date']


class POLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    received_by_name = serializers.SerializerMethodField()
    effective_job_id = serializers.SerializerMethodField()
    effective_job_number = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price', 'job',
            'effective_job_id', 'effective_job_number',
            'accounting_category', 'taxable_override', 'tax_rate_override',
            'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
        ]
        read_only_fields = [
            'line_item_id', 'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
            'effective_job_id', 'effective_job_number',
        ]

    def get_received_by_name(self, obj):
        if obj.received_by:
            return obj.received_by.get_full_name() or obj.received_by.username
        return None

    def _effective_job(self, obj):
        if obj.job_id:
            return obj.job
        if obj.task_id and obj.task.job_id:
            return obj.task.job
        return None

    def get_effective_job_id(self, obj):
        job = self._effective_job(obj)
        return job.pk if job else None

    def get_effective_job_number(self, obj):
        job = self._effective_job(obj)
        return job.job_number if job else None



class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items = POLineItemSerializer(
        source='purchaseorderlineitem_set', many=True, read_only=True
    )
    business_name = serializers.CharField(source='business.business_name', read_only=True)
    contact_name = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'business_name', 'contact', 'contact_name',
            'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items',
        ]
        read_only_fields = ['po_id', 'po_number', 'created_date']

    def get_contact_name(self, obj):
        if obj.contact:
            return f"{obj.contact.first_name} {obj.contact.last_name}"
        return None


class BillLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = BillLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'taxable_override', 'tax_rate_override',
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
            'qbo_id', 'qbo_payment_status',
        ]
        read_only_fields = ['bill_id', 'bill_number', 'created_date', 'qbo_id', 'qbo_payment_status']
