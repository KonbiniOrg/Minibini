from rest_framework import serializers
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial
from apps.core.models import AccountingCategory
from apps.core.units import UnitsField
from apps.api.mixins import JobScopedCanManageMixin


class PlanMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category',
        ]
        read_only_fields = fields


class PlanMaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False,
    )
    accounting_category = serializers.PrimaryKeyRelatedField(
        queryset=AccountingCategory.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'inventory_item',
            'accounting_category', 'propagate_to_pli',
        ]
        read_only_fields = ['plan_material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED,
            PLAN_MATERIAL_FREEFORM_ALLOWED,
        )
        # plan_task is not a field here (plan_task is the parent resource);
        # just apply the standard PLI allowlist check.
        if instance.inventory_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, validated_data, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(validated_data.keys()) - PLAN_MATERIAL_FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform PlanMaterial: {sorted(disallowed)}',
                })
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)


class PlanTaskDetailSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'est_worksheet.job'
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    est_worksheet = serializers.SerializerMethodField()
    scheme_name = serializers.CharField(source='rate_scheme.name', read_only=True, default=None)
    scheme_algorithm = serializers.CharField(source='rate_scheme.algorithm', read_only=True, default=None)
    scheme_unit_label = serializers.CharField(source='rate_scheme.unit_label', read_only=True, default=None)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'rate_scheme', 'active_modifiers', 'est_qty', 'est_worker_time',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
            'plan_materials', 'est_worksheet', 'can_manage',
        ]
        read_only_fields = fields

    def get_effective_rate(self, obj):
        rate = obj.effective_rate() if obj.rate_scheme_id else None
        return str(rate) if rate is not None else None

    def get_computed_charge(self, obj):
        try:
            return str(obj.compute_amount())
        except Exception:
            return None

    def get_est_worksheet(self, obj):
        from apps.estimates.services import WorksheetService
        ws = obj.est_worksheet
        job = ws.job
        return {
            'est_worksheet_id': ws.pk,
            'editable': WorksheetService.is_editable(ws),
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            },
        }
