from rest_framework import serializers
from apps.estimates.models import Estimate, EstimateLineItem
from apps.core.units import UnitsField


class EstimateLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = EstimateLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class EstimateSerializer(serializers.ModelSerializer):
    line_items = EstimateLineItemSerializer(
        source='estimatelineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Estimate
        fields = [
            'estimate_id', 'job', 'estimate_number', 'version', 'status',
            'parent', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items',
        ]
        read_only_fields = [
            'estimate_id', 'estimate_number', 'version',
            'created_date', 'sent_date', 'closed_date',
        ]
