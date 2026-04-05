from rest_framework import serializers

from apps.jobs.models import Task
from apps.core.units import UnitsField


class TaskDetailSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()
    work_order = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'status',
            'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name',
            'worker_queue', 'work_order',
        ]
        read_only_fields = fields

    def get_assignee_name(self, obj):
        if obj.assignee:
            return obj.assignee.get_full_name() or obj.assignee.username
        return None

    def get_work_order(self, obj):
        wo = obj.work_order
        job = wo.job
        return {
            'id': wo.pk,
            'status': wo.status,
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            },
        }
