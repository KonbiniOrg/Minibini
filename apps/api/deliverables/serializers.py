from decimal import Decimal
from rest_framework import serializers
from apps.api.mixins import JobScopedCanManageMixin
from apps.deliverables.models import Deliverable, DeliverableSnapshot, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService


_TWO_PLACES = Decimal('0.01')


def _q(value):
    """Format a Decimal as a string with exactly two decimal places."""
    return str(Decimal(value).quantize(_TWO_PLACES))


class DeliverableSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
    qty_picked_up = serializers.SerializerMethodField()
    qty_prepped = serializers.SerializerMethodField()
    qty_remaining = serializers.SerializerMethodField()

    class Meta:
        model = Deliverable
        fields = [
            'id', 'job', 'description', 'qty_ordered', 'units', 'sort_order',
            'qty_picked_up', 'qty_prepped', 'qty_remaining',
            'can_manage', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'job', 'created_at', 'updated_at',
                            'qty_picked_up', 'qty_prepped', 'qty_remaining']

    def _fulfillment(self, obj):
        if not hasattr(obj, '_cached_fulfillment'):
            obj._cached_fulfillment = DeliverableService.compute_fulfillment(obj)
        return obj._cached_fulfillment

    def get_qty_picked_up(self, obj):
        return _q(self._fulfillment(obj)['qty_picked_up'])

    def get_qty_prepped(self, obj):
        return _q(self._fulfillment(obj)['qty_prepped'])

    def get_qty_remaining(self, obj):
        return _q(self._fulfillment(obj)['qty_remaining'])


class DeliverableSnapshotSerializer(serializers.ModelSerializer):
    qty_ordered = serializers.SerializerMethodField()

    class Meta:
        model = DeliverableSnapshot
        fields = ['id', 'description', 'qty_ordered', 'units', 'sort_order', 'source_deliverable']
        read_only_fields = fields

    def get_qty_ordered(self, obj):
        return _q(obj.qty_ordered)


class ShipmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentItem
        fields = ['id', 'shipment', 'deliverable', 'qty']
        read_only_fields = ['id', 'shipment']


class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'job', 'sequence', 'status', 'prepared_date', 'picked_up_date',
            'notes', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'job', 'sequence', 'status', 'prepared_date',
                            'picked_up_date', 'items', 'created_at', 'updated_at']
