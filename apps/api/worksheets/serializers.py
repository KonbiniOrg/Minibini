from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask, PlanBundle
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


class PlanTaskSerializer(serializers.ModelSerializer):
    units = UnitsField()
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order']


class PlanBundleSerializer(serializers.ModelSerializer):
    plan_tasks = PlanTaskSerializer(many=True, read_only=True)

    class Meta:
        model = PlanBundle
        fields = [
            'plan_bundle_id', 'name', 'accounting_category',
            'sort_order', 'plan_tasks',
        ]
        read_only_fields = ['plan_bundle_id', 'sort_order']


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = PlanTaskSerializer(source='plan_tasks', many=True, read_only=True)
    bundles = PlanBundleSerializer(source='plan_bundles', many=True, read_only=True)

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'template', 'estimate',
            'status', 'version', 'parent', 'created_date', 'tasks', 'bundles',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']
