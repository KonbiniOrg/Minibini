from rest_framework import serializers
from apps.inventory.models import PriceListItem
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
