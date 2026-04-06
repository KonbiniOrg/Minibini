from rest_framework import serializers
from apps.jobs.models import WorkOrder, Task
from apps.core.units import UnitsField


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None


class WorkOrderSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True, default=None)

    class Meta:
        model = WorkOrder
        fields = [
            'work_order_id', 'job', 'template', 'template_name', 'status',
            'tasks',
        ]
        read_only_fields = ['work_order_id']
