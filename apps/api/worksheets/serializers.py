from decimal import Decimal
from rest_framework import serializers
from apps.estimates.models import EstWorksheet
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
    """Writable serializer for PlanMaterial; used by worksheet plan-materials endpoint."""
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'plan_task', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
        ]
        read_only_fields = ['plan_material_id']


class PlanTaskSerializer(serializers.ModelSerializer):
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    amount = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'rate_scheme', 'active_modifiers', 'est_qty',
            'amount', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order', 'amount']

    def get_amount(self, obj):
        return str(obj.compute_amount().quantize(Decimal('0.01')))


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = PlanTaskSerializer(source='plan_tasks', many=True, read_only=True)

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'template', 'estimate',
            'status', 'version', 'parent', 'created_date', 'tasks',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']
