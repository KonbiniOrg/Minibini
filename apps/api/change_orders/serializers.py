from rest_framework import serializers

from apps.api.mixins import JobScopedCanManageMixin
from apps.core.units import UnitsField
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem


class ChangeOrderLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    service_item_detail = serializers.SerializerMethodField()

    class Meta:
        model = ChangeOrderLineItem
        fields = [
            'line_item_id', 'line_number',
            'action', 'target_line_item',
            'description', 'qty', 'units', 'price',
            'accounting_category',
            'inventory_item', 'service_item', 'service_item_detail', 'is_material',
        ]
        read_only_fields = ['line_item_id', 'service_item_detail']

    def get_service_item_detail(self, obj):
        if obj.service_item_id is None:
            return None
        return {
            'template_id': obj.service_item.template_id,
            'name': obj.service_item.template_name,
        }


class ChangeOrderSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'

    line_items = ChangeOrderLineItemSerializer(
        source='changeorderlineitem_set', many=True, read_only=True
    )
    total = serializers.SerializerMethodField()

    class Meta:
        model = ChangeOrder
        fields = [
            'change_order_id', 'job', 'estimate',
            'change_order_number', 'version', 'parent',
            'status', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items', 'can_manage', 'total',
        ]
        read_only_fields = [
            'change_order_id', 'change_order_number', 'version',
            'estimate', 'created_date', 'sent_date', 'closed_date',
        ]

    def get_total(self, obj):
        # Authoritative CO delta: proposed − prior against the base estimate,
        # from compose_change_order_diff (the same figure the CO PDF and
        # portal diff use). NOT qty*price of the CO's own add/remove/replace
        # lines — a remove subtracts, a replace swaps. The job-overview Scope
        # block adds this delta onto the frozen estimate total.
        from decimal import Decimal
        from apps.estimates.agreement import compose_change_order_diff
        diff = compose_change_order_diff(obj)
        return str(diff['diff_total'].quantize(Decimal('0.01')))
