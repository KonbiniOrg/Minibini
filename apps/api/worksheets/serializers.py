from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Task, TaskBundle


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'units', 'rate', 'est_qty', 'line_item_type',
            'mapping_strategy', 'bundle', 'parent_task', 'assignee',
            'assignee_name',
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
            'id', 'name', 'description', 'line_item_type',
            'sort_order', 'tasks',
        ]
        read_only_fields = ['id', 'sort_order']


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'template', 'estimate',
            'status', 'version', 'parent', 'created_date', 'tasks', 'bundles',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']
