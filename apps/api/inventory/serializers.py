from decimal import Decimal
from rest_framework import serializers
from apps.inventory.models import PriceListItem, Material
from apps.core.units import UnitsField


class PriceListItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    qty_earmarked = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    qty_available = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PriceListItem
        fields = [
            'price_list_item_id', 'code', 'units', 'description',
            'purchase_price', 'selling_price',
            'qty_on_hand', 'qty_sold', 'qty_wasted',
            'qty_earmarked', 'qty_available',
            'is_active', 'is_inventoried', 'accounting_category',
        ]
        read_only_fields = [
            'price_list_item_id', 'qty_on_hand', 'qty_sold', 'qty_wasted',
        ]


class MaterialSerializer(serializers.ModelSerializer):
    is_expense_bound = serializers.BooleanField(read_only=True)
    price_list_item_is_inventoried = serializers.SerializerMethodField()
    po_line_item_id = serializers.SerializerMethodField()
    po_id = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    po_status = serializers.SerializerMethodField()
    units = UnitsField()
    qty_on_order = serializers.SerializerMethodField()
    qty_on_hand = serializers.SerializerMethodField()
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )

    class Meta:
        model = Material
        fields = [
            'material_id', 'job', 'task',
            'description', 'quantity', 'unit_cost', 'sell_price',
            'price_list_item', 'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'price_list_item_is_inventoried',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'units', 'qty_on_order', 'qty_on_hand',
            'propagate_to_pli',
        ]
        read_only_fields = [
            'material_id', 'job', 'task',
            'consumption_state', 'restocked_qty', 'is_expense_bound',
            'price_list_item_is_inventoried',
            'po_line_item_id', 'po_id', 'po_number', 'po_status',
            'qty_on_order', 'qty_on_hand',
        ]

    def get_price_list_item_is_inventoried(self, obj):
        return bool(obj.price_list_item and obj.price_list_item.is_inventoried)

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
        if obj.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
            return '0'
        if obj.po_line_item_id:
            return str(obj.po_line_item.qty_received)
        if obj.price_list_item_id and obj.price_list_item.is_inventoried:
            return str(obj.quantity)
        return '0'

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        if instance.price_list_item_id is not None:
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
