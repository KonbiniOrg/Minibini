from rest_framework import serializers

from apps.jobs.models import Task
from apps.inventory.models import Material
from apps.core.units import UnitsField


class MaterialSerializer(serializers.ModelSerializer):
    effective_qty = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    is_expense_bound = serializers.BooleanField(read_only=True)

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
            'consumption_state', 'restocked_qty', 'effective_qty',
            'is_expense_bound',
        ]
        read_only_fields = fields


class MaterialWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = ['material_id']


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

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'status',
            'blocked_reason', 'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name',
            'worker_queue', 'job',
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
