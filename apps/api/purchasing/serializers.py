from decimal import Decimal
from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Business
from apps.core.units import UnitsField


class PurchaseOrderSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrder
        fields = ['po_id', 'po_number', 'status', 'created_date']


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
            'final_price', 'invoice_only',
        ]
        read_only_fields = [
            'line_item_id', 'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
            'effective_job_id', 'effective_job_number', 'material',
            # `final_price` and `invoice_only` are reconciliation-owned
            # (task-owned-money Phase 5, spec §7 rule 3) — the sanctioned
            # write path is PurchaseOrderService.reconcile(), not a bare
            # line create/update. `task` stays writable (spec §7 rule 1).
            'final_price', 'invoice_only',
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
    po_total = serializers.SerializerMethodField()
    awaiting_reconciliation = serializers.SerializerMethodField()
    variance = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'business_name', 'contact', 'contact_name',
            'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items', 'po_total',
            'bill_total', 'vendor_invoice_ref', 'reconciled', 'reconciled_date',
            'awaiting_reconciliation', 'variance',
        ]
        read_only_fields = [
            'po_id', 'po_number', 'created_date',
            # Reconciliation fields are written only via the `reconcile`
            # action (PurchaseOrderService.reconcile) — not a bare PATCH.
            'bill_total', 'vendor_invoice_ref', 'reconciled', 'reconciled_date',
        ]

    def get_contact_name(self, obj):
        if obj.contact:
            return f"{obj.contact.first_name} {obj.contact.last_name}"
        return None

    def get_po_total(self, obj):
        return str(obj.po_total.quantize(Decimal('0.01')))

    def get_awaiting_reconciliation(self, obj):
        return obj.is_awaiting_reconciliation

    def get_variance(self, obj):
        variance = obj.variance
        if variance is None:
            return None
        return str(variance.quantize(Decimal('0.01')))
