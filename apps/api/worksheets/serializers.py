from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask, PlanBundle
from apps.core.units import UnitsField


class PlanTaskSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle',
        ]
        read_only_fields = ['plan_task_id', 'sort_order']


class PlanBundleSerializer(serializers.ModelSerializer):
    plan_tasks = PlanTaskSerializer(many=True, read_only=True)

    class Meta:
        model = PlanBundle
        fields = [
            'plan_bundle_id', 'name', 'description', 'accounting_category',
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
