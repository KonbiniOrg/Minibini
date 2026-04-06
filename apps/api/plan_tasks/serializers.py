from rest_framework import serializers
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial
from apps.core.units import UnitsField


class PlanMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = fields


class PlanTaskDetailSerializer(serializers.ModelSerializer):
    units = UnitsField()
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    est_worksheet = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle',
            'plan_materials', 'est_worksheet',
        ]
        read_only_fields = fields

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
