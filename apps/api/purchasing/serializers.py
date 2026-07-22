from decimal import Decimal
from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem, BillPayment
from apps.contacts.models import Business
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
        val = getattr(obj, 'balance_anno', None)
        if val is not None:
            return str(Decimal(val).quantize(Decimal('0.01')))
        return '0.00'

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
            'accounting_category',
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
    billed_total = serializers.SerializerMethodField()
    po_total = serializers.SerializerMethodField()
    is_fully_billed = serializers.ReadOnlyField()
    bills = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'business_name', 'contact', 'contact_name',
            'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items',
            'billed_total', 'po_total', 'is_fully_billed', 'bills',
        ]
        read_only_fields = ['po_id', 'po_number', 'created_date']

    def get_contact_name(self, obj):
        if obj.contact:
            return f"{obj.contact.first_name} {obj.contact.last_name}"
        return None

    def get_bills(self, obj):
        return [
            {'bill_id': b.bill_id,
             'vendor_invoice_number': b.vendor_invoice_number,
             'status': b.status}
            for b in obj.bills.all()
        ]

    def get_billed_total(self, obj):
        return str(obj.billed_total.quantize(Decimal('0.01')))

    def get_po_total(self, obj):
        return str(obj.po_total.quantize(Decimal('0.01')))


class BillLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = BillLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'accounting_category',
        ]
        read_only_fields = ['line_item_id']


class BillPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillPayment
        fields = ['payment_id', 'amount', 'payment_date', 'reference',
                  'payment_account_id', 'created_by', 'created_date',
                  'qbo_id', 'qbo_sync_status', 'qbo_sync_error', 'cleared_date']
        read_only_fields = ['payment_id', 'created_by', 'created_date',
                            'qbo_id', 'qbo_sync_status', 'qbo_sync_error', 'cleared_date']


class BillSerializer(serializers.ModelSerializer):
    line_items = BillLineItemSerializer(
        source='billlineitem_set', many=True, read_only=True
    )
    payments = BillPaymentSerializer(
        source='billpayment_set', many=True, read_only=True
    )
    # Vendor is optional at the API layer: when a purchase_order is supplied the
    # vendor is derived from it (create_bill_from_po). validate() enforces that a
    # create has one source or the other.
    business = serializers.PrimaryKeyRelatedField(
        queryset=Business.objects.all(), required=False, allow_null=True)
    po_number = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    po_billing = serializers.SerializerMethodField()

    def validate(self, attrs):
        if self.instance is None and not attrs.get('purchase_order') and not attrs.get('business'):
            raise serializers.ValidationError(
                {'business': 'A vendor business or a purchase order is required.'})
        return attrs

    class Meta:
        model = Bill
        fields = [
            'bill_id', 'purchase_order', 'po_number',
            'vendor_invoice_number', 'business', 'vendor_name', 'contact',
            'status', 'created_date', 'due_date', 'received_date',
            'paid_date', 'cancelled_date', 'line_items', 'payments',
            'amount_paid', 'balance', 'qbo_id', 'qbo_payment_status',
            'po_billing',
        ]
        read_only_fields = [
            'bill_id', 'status', 'created_date', 'received_date',
            'paid_date', 'cancelled_date', 'qbo_id', 'qbo_payment_status',
        ]

    def get_po_number(self, obj):
        return obj.purchase_order.po_number if obj.purchase_order else None

    def get_vendor_name(self, obj):
        return obj.business.business_name if obj.business else None

    def get_amount_paid(self, obj):
        return str(obj.amount_paid.quantize(Decimal('0.01')))

    def get_balance(self, obj):
        return str(obj.balance.quantize(Decimal('0.01')))

    def get_po_billing(self, obj):
        if not obj.purchase_order_id:
            return None
        po = obj.purchase_order
        # Use the prefetch cache (all() hits it; exclude()/filter() do not).
        # Filter in Python so that serializing a list of bills uses the
        # prefetched purchase_order__bills__billlineitem_set data rather than
        # firing per-row DB queries.
        all_bills = list(po.bills.all())
        other_bills = [
            b for b in all_bills
            if b.status != Bill.STATUS_CANCELLED and b.pk != obj.pk
        ]
        active_bills = [
            b for b in all_bills
            if b.status != Bill.STATUS_CANCELLED
        ]
        # po_total: sum PO line items from the prefetch cache
        # (purchaseorderlineitem_set prefetched by the viewset).
        po_line_items = list(po.purchaseorderlineitem_set.all())
        po_total = sum((li.total_amount for li in po_line_items), Decimal('0.00'))
        billed_total = sum((b.total for b in active_bills), Decimal('0.00'))
        po_fully_billed = po_total > 0 and billed_total >= po_total
        return {
            'other_bills': [
                {
                    'bill_id': b.pk,
                    'vendor_invoice_number': b.vendor_invoice_number,
                    'status': b.status,
                    'total': str(b.total.quantize(Decimal('0.01'))),
                }
                for b in other_bills
            ],
            'po_fully_billed': po_fully_billed,
        }
