from rest_framework import serializers
from apps.jobs.models import WorkOrder, Blep
from apps.api.worksheets.serializers import TaskSerializer, TaskBundleSerializer


class BlepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Blep
        fields = ['blep_id', 'user', 'task', 'start_time', 'end_time']
        read_only_fields = ['blep_id']


class WorkOrderSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = [
            'work_order_id', 'job', 'template', 'status',
            'tasks', 'bundles',
        ]
        read_only_fields = ['work_order_id']
