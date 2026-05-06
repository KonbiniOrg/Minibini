from decimal import Decimal
from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial


class PlanMaterialSerializer(serializers.ModelSerializer):
    units = serializers.SerializerMethodField()

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'units',
        ]
        read_only_fields = fields

    def get_units(self, obj):
        return obj.price_list_item.units if obj.price_list_item_id else 'none'


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
    units = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'rate_scheme', 'active_modifiers', 'est_qty',
            'amount', 'units', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order', 'amount', 'units']

    def get_amount(self, obj):
        return str(obj.compute_amount().quantize(Decimal('0.01')))

    def get_units(self, obj):
        return obj.rate_scheme.unit_label if obj.rate_scheme_id else ''


class PlanMaterialAssignTaskSerializer(serializers.Serializer):
    plan_task = serializers.PrimaryKeyRelatedField(
        queryset=PlanTask.objects.all(), allow_null=True,
    )


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = PlanTaskSerializer(source='plan_tasks', many=True, read_only=True)
    taskless_materials = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'job_number', 'job_name',
            'template', 'estimate',
            'status', 'version', 'parent', 'created_date',
            'tasks', 'taskless_materials',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']

    def get_taskless_materials(self, obj):
        materials = PlanMaterial.objects.filter(
            est_worksheet=obj, plan_task__isnull=True,
        )
        return PlanMaterialSerializer(materials, many=True).data

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job_id else None

    def get_job_name(self, obj):
        return obj.job.name if obj.job_id else ''
