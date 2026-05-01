from rest_framework import serializers

from apps.jobs.models import Task, TaskCharge
from apps.inventory.models import Material
from apps.core.units import UnitsField


class MaterialSerializer(serializers.ModelSerializer):
    is_expense_bound = serializers.BooleanField(read_only=True)
    price_list_item_is_inventoried = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'price_list_item_is_inventoried',
        ]
        read_only_fields = fields

    def get_price_list_item_is_inventoried(self, obj):
        return bool(obj.price_list_item and obj.price_list_item.is_inventoried)


class MaterialWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = ['material_id']


class TaskChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskCharge
        fields = [
            'task_charge_id', 'rate_scheme', 'active_modifiers', 'actuals',
        ]
        read_only_fields = ['task_charge_id']


class TaskChargeReadSerializer(serializers.ModelSerializer):
    """Nested read-only representation for task detail."""
    scheme_name = serializers.CharField(source='rate_scheme.name', read_only=True)
    scheme_algorithm = serializers.CharField(source='rate_scheme.algorithm', read_only=True)
    scheme_unit_label = serializers.CharField(source='rate_scheme.unit_label', read_only=True)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()

    class Meta:
        model = TaskCharge
        fields = [
            'task_charge_id', 'rate_scheme', 'active_modifiers', 'actuals',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
        ]
        read_only_fields = fields

    def get_effective_rate(self, obj):
        return str(obj.effective_rate())

    def get_computed_charge(self, obj):
        try:
            return str(obj.compute())
        except Exception:
            return None


class TaskSerializer(serializers.ModelSerializer):
    """Serializer for tasks nested under /api/jobs/{id}/tasks/."""
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason', 'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None


class TaskDetailSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()
    job = serializers.SerializerMethodField()
    charge = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'status',
            'blocked_reason', 'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name',
            'worker_queue', 'job', 'charge',
        ]
        read_only_fields = fields

    def get_assignee_name(self, obj):
        if obj.assignee:
            return obj.assignee.get_full_name() or obj.assignee.username
        return None

    def get_job(self, obj):
        job = obj.job
        return {
            'id': job.pk,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
        }

    def get_charge(self, obj):
        try:
            charge = obj.charge
        except TaskCharge.DoesNotExist:
            return None
        return TaskChargeReadSerializer(charge).data
