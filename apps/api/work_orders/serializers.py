from rest_framework import serializers
from apps.jobs.models import WorkOrder, Blep, Task, TaskBundle
from apps.core.units import UnitsField


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle', 'parent_task', 'assignee',
            'assignee_name', 'worker_queue',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None


class TaskBundleSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)

    class Meta:
        model = TaskBundle
        fields = [
            'id', 'name', 'description', 'accounting_category',
            'sort_order', 'tasks',
        ]
        read_only_fields = ['id', 'sort_order']


class BlepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Blep
        fields = ['blep_id', 'user', 'task', 'start_time', 'end_time']
        read_only_fields = ['blep_id']


class WorkOrderSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True, default=None)

    class Meta:
        model = WorkOrder
        fields = [
            'work_order_id', 'job', 'template', 'template_name', 'status',
            'tasks', 'bundles',
        ]
        read_only_fields = ['work_order_id']
