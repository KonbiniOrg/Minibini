from decimal import Decimal
from rest_framework import serializers
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.core.units import UnitsField
from apps.api.mixins import InvoiceRefMixin


class InventoryItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    qty_earmarked = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    qty_available = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    qty_on_order = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = InventoryItem
        fields = [
            'inventory_item_id', 'code', 'units', 'description',
            'purchase_price', 'selling_price',
            'qty_on_hand', 'qty_sold', 'qty_wasted',
            'qty_earmarked', 'qty_available', 'qty_on_order',
            'is_active', 'accounting_category',
        ]
        read_only_fields = [
            'inventory_item_id', 'qty_on_hand', 'qty_sold', 'qty_wasted',
        ]


class MaterialSerializer(InvoiceRefMixin, serializers.ModelSerializer):
    invoice_source_type = 'material'
    is_expense_bound = serializers.BooleanField(read_only=True)
    po_line_item_id = serializers.SerializerMethodField()
    po_id = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    po_status = serializers.SerializerMethodField()
    units = UnitsField()
    qty_on_order = serializers.SerializerMethodField()
    qty_on_hand = serializers.SerializerMethodField()
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False,
    )
    customer_supplied = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )
    invoice = serializers.SerializerMethodField()
    claimed = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'job', 'task',
            'description', 'quantity', 'unit_cost', 'sell_price',
            'inventory_item', 'accounting_category',
            'consumption_state', 'released_qty', 'cost_source',
            'is_expense_bound',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'units', 'qty_on_order', 'qty_on_hand',
            'propagate_to_pli', 'customer_supplied',
            'invoice',
            'claimed',
        ]
        read_only_fields = [
            'material_id', 'job', 'task',
            'consumption_state', 'released_qty', 'cost_source',
            'is_expense_bound',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'qty_on_order', 'qty_on_hand',
        ]

    def get_po_line_item_id(self, obj):
        return obj.po_line_item_id

    def get_po_id(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order_id if pol else None

    def get_po_number(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order.po_number if pol else None

    def get_po_status(self, obj):
        from apps.inventory.serializer_helpers import material_po_line_item
        pol = material_po_line_item(obj)
        return pol.purchase_order.status if pol else None

    def get_qty_on_order(self, obj):
        from apps.inventory.serializer_helpers import material_qty_on_order
        return material_qty_on_order(obj)

    def get_qty_on_hand(self, obj):
        from apps.inventory.serializer_helpers import material_qty_on_hand
        return material_qty_on_hand(obj)

    def get_claimed(self, obj):
        """True iff a non-superseded estimate on this job has claimed this material."""
        claims = self.context.get('estimate_claims') or frozenset()
        return ('material', obj.pk) in claims

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        if instance.inventory_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, validated_data, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(validated_data.keys()) - FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform Material: {sorted(disallowed)}',
                })
        # propagate_to_pli is handled separately by the view (Phase 4); strip it
        # before saving.
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)


class MaterialOpSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)


class StockOrderSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    po_id = serializers.IntegerField(required=False, allow_null=True)


class MaterialAssignTaskSerializer(serializers.Serializer):
    task = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.jobs.models', fromlist=['Task']).Task.objects.all(),
        allow_null=True,
    )


class EarmarkSerializer(serializers.ModelSerializer):
    """Read-only commitment report row: the earmark plus the item-level
    figures the Catalog Earmarks tab needs (shortfall is computed
    client-side from the three quantities)."""
    item_code = serializers.CharField(source='inventory_item.code', read_only=True)
    item_description = serializers.CharField(
        source='inventory_item.description', read_only=True)
    units = serializers.CharField(source='inventory_item.units', read_only=True)
    job_number = serializers.CharField(source='job.job_number', read_only=True)
    qty_on_hand = serializers.DecimalField(
        source='inventory_item.qty_on_hand',
        max_digits=10, decimal_places=2, read_only=True)
    qty_on_order = serializers.DecimalField(
        source='inventory_item.qty_on_order',
        max_digits=10, decimal_places=2, read_only=True)
    qty_earmarked_total = serializers.DecimalField(
        source='inventory_item.qty_earmarked',
        max_digits=10, decimal_places=2, read_only=True)
    pos = serializers.SerializerMethodField()

    class Meta:
        model = Earmark
        fields = [
            'earmark_id', 'inventory_item', 'item_code', 'item_description',
            'units', 'job', 'job_number', 'quantity', 'created_date',
            'qty_on_hand', 'qty_on_order', 'qty_earmarked_total', 'pos',
        ]

    def get_pos(self, obj):
        """Distinct non-cancelled POs with an outstanding line for this item."""
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
        lines = PurchaseOrderLineItem.objects.filter(
            inventory_item=obj.inventory_item,
        ).exclude(
            purchase_order__status=PurchaseOrder.STATUS_CANCELLED,
        ).select_related('purchase_order')
        seen, out = set(), []
        for li in lines:
            if li.qty - li.qty_received - li.qty_cancelled <= 0:
                continue
            po = li.purchase_order
            if po.pk in seen:
                continue
            seen.add(po.pk)
            out.append({'po_id': po.pk, 'po_number': po.po_number})
        return out
