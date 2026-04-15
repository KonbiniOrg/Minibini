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

    class Meta:
        model = Material
        fields = [
            'material_id', 'job', 'task',
            'description', 'quantity', 'unit_cost', 'sell_price',
            'price_list_item', 'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound',
        ]
        read_only_fields = [
            'material_id', 'job', 'task',
            'consumption_state', 'restocked_qty', 'is_expense_bound',
        ]

    def update(self, instance, validated_data):
        allowed = {'description'}
        disallowed = set(validated_data.keys()) - allowed
        if disallowed:
            raise serializers.ValidationError({
                k: 'read-only; use Restock/Draw-more for quantity, etc.'
                for k in disallowed
            })
        return super().update(instance, validated_data)


class MaterialOpSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
