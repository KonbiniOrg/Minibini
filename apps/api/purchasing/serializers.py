from decimal import Decimal
from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem
from apps.core.units import UnitsField


class PurchaseOrderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = ['po_id', 'po_number', 'status', 'created_date']


class BillSummarySerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    def get_contact_name(self, obj):
        return obj.contact.name if obj.contact else None

    def get_vendor_name(self, obj):
        return obj.business.business_name if obj.business else None

    def get_po_number(self, obj):
        return obj.purchase_order.po_number if obj.purchase_order else None

    def get_total(self, obj):
        val = getattr(obj, 'total_anno', None)
        if val is not None:
            return str(Decimal(val).quantize(Decimal('0.01')))
        return '0.00'

    def get_balance(self, obj):
        # Prefer the SQL annotation (it backs DB-side sorting by balance); the
        # annotation is built from Bill.ZERO_BALANCE_STATUSES, the same rule as
        # the model's balance property used as a fallback here.
        val = getattr(obj, 'balance_anno', None)
        if val is not None:
            return str(Decimal(val).quantize(Decimal('0.01')))
        return str(obj.balance)

    class Meta:
        model = Bill
        fields = ['bill_id', 'status', 'vendor_invoice_number', 'created_date',
                  'due_date', 'received_date', 'contact_name', 'vendor_name',
                  'po_number', 'purchase_order', 'total', 'balance']


class POLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    received_by_name = serializers.SerializerMethodField()
    effective_job_id = serializers.SerializerMethodField()
    effective_job_number = serializers.SerializerMethodField()
    material = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'effective_job_id', 'effective_job_number', 'material',
            'accounting_category', 'taxable_override', 'tax_rate_override',
            'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
        ]
        read_only_fields = [
            'line_item_id', 'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
            'effective_job_id', 'effective_job_number', 'material',
        ]

    def get_received_by_name(self, obj):
        if obj.received_by:
            return obj.received_by.get_full_name() or obj.received_by.username
        return None

    def _material(self, obj):
        return obj.linked_material

    def get_effective_job_id(self, obj):
        mat = self._material(obj)
        return mat.job_id if mat else None

    def get_effective_job_number(self, obj):
        mat = self._material(obj)
        return mat.job.job_number if mat else None

    def get_material(self, obj):
        mat = self._material(obj)
        if mat is None:
            return None
        return {
            'material_id': mat.pk,
            'description': mat.description,
            'quantity': str(mat.quantity),
            'consumption_state': mat.consumption_state,
            'job_id': mat.job_id,
            'job_number': mat.job.job_number,
        }



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
            'line_item_id', 'line_number', 'task', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class BillSerializer(serializers.ModelSerializer):
    line_items = BillLineItemSerializer(
        source='billlineitem_set', many=True, read_only=True
    )
    po_number = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            'bill_id', 'purchase_order', 'po_number',
            'vendor_invoice_number', 'business', 'vendor_name', 'contact',
            'status', 'created_date', 'due_date', 'received_date',
            'paid_date', 'cancelled_date', 'line_items', 'balance',
            'qbo_id', 'qbo_payment_status',
        ]
        read_only_fields = [
            'bill_id', 'status', 'created_date', 'received_date',
            'paid_date', 'cancelled_date', 'qbo_id', 'qbo_payment_status',
        ]

    def get_po_number(self, obj):
        return obj.purchase_order.po_number if obj.purchase_order else None

    def get_vendor_name(self, obj):
        return obj.business.business_name if obj.business else None

    def get_balance(self, obj):
        return str(obj.balance)
