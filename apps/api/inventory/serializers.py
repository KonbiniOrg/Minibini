from decimal import Decimal
from rest_framework import serializers
from apps.inventory.models import InventoryItem, Material
from apps.core.units import UnitsField
from apps.api.mixins import InvoiceRefMixin


class InventoryItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    qty_earmarked = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    qty_available = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = InventoryItem
        fields = [
            'inventory_item_id', 'code', 'units', 'description',
            'purchase_price', 'selling_price',
            'qty_on_hand', 'qty_sold', 'qty_wasted',
            'qty_earmarked', 'qty_available',
            'is_active', 'is_catalog', 'accounting_category',
        ]
        read_only_fields = [
            'inventory_item_id', 'qty_on_hand', 'qty_sold', 'qty_wasted',
        ]


class MaterialSerializer(InvoiceRefMixin, serializers.ModelSerializer):
    invoice_source_type = 'material'
    is_expense_bound = serializers.BooleanField(read_only=True)
    inventory_item_is_catalog = serializers.SerializerMethodField()
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
    invoice = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'job', 'task',
            'description', 'quantity', 'unit_cost', 'sell_price',
            'inventory_item', 'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'inventory_item_is_catalog',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'units', 'qty_on_order', 'qty_on_hand',
            'propagate_to_pli',
            'invoice',
        ]
        read_only_fields = [
            'material_id', 'job', 'task',
            'consumption_state', 'restocked_qty', 'is_expense_bound',
            'inventory_item_is_catalog',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'qty_on_order', 'qty_on_hand',
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # Freeform (no-PLI) actual materials get their cost from a document
        # (Expense/PO), never typed manually. (PLI-linked materials are exempt.)
        instance = getattr(self, 'instance', None)
        has_pli = attrs.get(
            'inventory_item', getattr(instance, 'inventory_item', None),
        ) is not None
        if 'unit_cost' in attrs and not has_pli:
            uc = attrs.get('unit_cost')
            if uc and uc != Decimal('0.00'):
                raise serializers.ValidationError({
                    'unit_cost': 'A freeform material’s cost comes from a linked '
                                 'expense or PO, not manual entry.'
                })
        return attrs

    def get_inventory_item_is_catalog(self, obj):
        return bool(obj.inventory_item and obj.inventory_item.is_catalog)

    def get_po_line_item_id(self, obj):
        return obj.po_line_item_id

    def get_po_id(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order_id
        return None

    def get_po_number(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order.po_number
        return None

    def get_po_status(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order.status
        return None

    def get_qty_on_order(self, obj):
        if not obj.po_line_item_id:
            return '0'
        pol = obj.po_line_item
        outstanding = pol.qty - pol.qty_received - pol.qty_cancelled
        return str(max(outstanding, Decimal('0')))

    def get_qty_on_hand(self, obj):
        from apps.inventory.serializer_helpers import material_qty_on_hand
        return material_qty_on_hand(obj)

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


class MaterialAssignTaskSerializer(serializers.Serializer):
    task = serializers.PrimaryKeyRelatedField(
        queryset=__import__('apps.jobs.models', fromlist=['Task']).Task.objects.all(),
        allow_null=True,
    )
