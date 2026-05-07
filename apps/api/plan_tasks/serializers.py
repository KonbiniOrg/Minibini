from rest_framework import serializers
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial


class PlanMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = fields


class PlanMaterialWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = ['plan_material_id']


class PlanTaskDetailSerializer(serializers.ModelSerializer):
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
            'plan_materials', 'est_worksheet',
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
        ws = obj.est_worksheet
        job = ws.job
        return {
            'est_worksheet_id': ws.pk,
            'status': ws.status,
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            },
        }
