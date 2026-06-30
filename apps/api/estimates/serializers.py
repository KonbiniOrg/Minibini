from rest_framework import serializers
from apps.estimates.models import Estimate, EstimateLineItem
from apps.core.units import UnitsField
from apps.api.mixins import JobScopedCanManageMixin


class EstimateLineItemSourceSerializer(serializers.Serializer):
    """Serializer for EstimateLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()

    def get_description(self, obj):
        instance = obj.resolve()
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return instance.name
        return instance.description  # Material / Fee

    def get_computed_amount(self, obj):
        from decimal import Decimal
        instance = obj.resolve()
        return str(instance.compute_amount().quantize(Decimal('0.01')))


class EstimateLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    sources = EstimateLineItemSourceSerializer(many=True, read_only=True)
    adjustment_service_detail = serializers.SerializerMethodField()

    class Meta:
        model = EstimateLineItem
        fields = [
            'line_item_id', 'line_number', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'taxable_override', 'tax_rate_override',
            'adjustment_service', 'adjustment_target_categories',
            'adjustment_service_detail',
            'sources',
        ]
        read_only_fields = ['line_item_id']

    def get_adjustment_service_detail(self, obj):
        if obj.adjustment_service_id is None:
            return None
        svc = obj.adjustment_service
        return {
            'name': svc.name,
            'rate': str(svc.rate),
            'algorithm': svc.algorithm,
        }


class EstimateSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
    line_items = EstimateLineItemSerializer(
        source='estimatelineitem_set', many=True, read_only=True
    )
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    is_amended = serializers.SerializerMethodField()

    class Meta:
        model = Estimate
        fields = [
            'estimate_id', 'job', 'job_number', 'job_name',
            'estimate_number', 'version', 'status', 'is_amended',
            'parent', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items', 'can_manage',
        ]
        read_only_fields = [
            'estimate_id', 'estimate_number', 'version',
            'created_date', 'sent_date', 'closed_date',
        ]

    def get_is_amended(self, obj):
        """True when this estimate is the accepted base AND at least one
        ACCEPTED change order amends it. Purely derived — the stored `status`
        stays `accepted`; the UI renders "amended" off this flag. Only accepted
        COs count (they're the only ones in the agreement-of-record), and the
        accepted-status short-circuit keeps non-accepted estimates query-free."""
        from apps.estimates.models import ChangeOrder
        if obj.status != Estimate.STATUS_ACCEPTED:
            return False
        return ChangeOrder.objects.filter(
            estimate=obj, status=ChangeOrder.STATUS_ACCEPTED,
        ).exists()

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job_id else None

    def get_job_name(self, obj):
        return obj.job.name if obj.job_id else ''
