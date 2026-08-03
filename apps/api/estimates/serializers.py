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

    def _resolve_or_none(self, obj):
        # A dangling row (atom deleted out from under the claim — pre-purge
        # data, or a race) must render as null, never 500 the list endpoint.
        from django.core.exceptions import ObjectDoesNotExist
        try:
            return obj.resolve()
        except ObjectDoesNotExist:
            return None

    def get_description(self, obj):
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        from apps.jobs.models import Task
        if isinstance(instance, Task):
            return instance.name
        return instance.description  # Material / Fee

    def get_computed_amount(self, obj):
        from decimal import Decimal
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        # Estimate line items project the ESTIMATE quote (est_qty), not actuals.
        # A Task bills actuals via compute_amount() — $0 until it's worked — so the
        # estimate must use compute_estimate_amount() instead; Material / Fee have
        # only compute_amount() (no est/actual split) and fall through.
        amount_fn = getattr(instance, 'compute_estimate_amount', instance.compute_amount)
        return str(amount_fn().quantize(Decimal('0.01')))


class EstimateLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    sources = EstimateLineItemSourceSerializer(many=True, read_only=True)
    adjustment_service_detail = serializers.SerializerMethodField()
    service_item_detail = serializers.SerializerMethodField()

    class Meta:
        model = EstimateLineItem
        fields = [
            'line_item_id', 'line_number', 'inventory_item', 'service_item', 'freeform_kind',
            'qty', 'units', 'description', 'price',
            'accounting_category',
            'adjustment_service', 'adjustment_target_categories',
            'adjustment_service_detail', 'service_item_detail',
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

    def get_service_item_detail(self, obj):
        if obj.service_item_id is None:
            return None
        si = obj.service_item
        return {'template_id': si.template_id, 'name': si.template_name}


class EstimateSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
    line_items = EstimateLineItemSerializer(
        source='estimatelineitem_set', many=True, read_only=True
    )
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    is_amended = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()

    class Meta:
        model = Estimate
        fields = [
            'estimate_id', 'job', 'job_number', 'job_name',
            'estimate_number', 'version', 'status', 'is_amended',
            'parent', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items', 'can_manage', 'total',
        ]
        read_only_fields = [
            'estimate_id', 'estimate_number', 'version',
            'created_date', 'sent_date', 'closed_date',
        ]

    def get_is_amended(self, obj):
        # Derived "amended" flag — see Estimate.is_amended() for the rule (the
        # single source of truth shared with the board pipeline payload).
        return obj.is_amended()

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job_id else None

    def get_job_name(self, obj):
        return obj.job.name if obj.job_id else ''

    def get_total(self, obj):
        # Authoritative document total: summed line qty*price, the same figure
        # the PDF (apps/estimates/pdf.py) and financials._estimated use. The
        # job-overview Scope block consumes this rather than recomputing on the
        # client (adjustment/percentage lines make client qty*price fragile).
        from decimal import Decimal
        total = sum(
            (li.qty * li.price for li in obj.estimatelineitem_set.all()),
            Decimal('0'),
        )
        return str(total.quantize(Decimal('0.01')))
