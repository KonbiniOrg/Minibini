from rest_framework import serializers
from apps.jobs.models import Blep


class BlepSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    task_name = serializers.CharField(source='task.name', read_only=True)
    job_id = serializers.IntegerField(source='task.job_id', read_only=True)
    job_number = serializers.CharField(source='task.job.job_number', read_only=True)
    job_name = serializers.CharField(source='task.job.name', read_only=True)

    class Meta:
        model = Blep
        fields = [
            'blep_id', 'user', 'user_name',
            'task', 'task_name',
            'job_id', 'job_number', 'job_name',
            'start_time', 'end_time',
        ]
        read_only_fields = ['blep_id', 'user_name', 'task_name',
                             'job_id', 'job_number', 'job_name']

    def get_user_name(self, obj):
        if obj.user is None:
            return None
        return obj.user.get_full_name() or obj.user.username
