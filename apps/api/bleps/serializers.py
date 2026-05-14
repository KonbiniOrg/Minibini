from rest_framework import serializers
from apps.jobs.models import Blep, Task
from apps.core.models import User


class BlepSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    task_name = serializers.CharField(source='task.name', read_only=True)
    job_id = serializers.IntegerField(source='task.job_id', read_only=True)
    job_number = serializers.CharField(source='task.job.job_number', read_only=True)
    job_name = serializers.CharField(source='task.job.name', read_only=True)
    # task/start_time/end_time are nullable on the model but required when
    # creating via the API; user is optional (interpreted as target_user).
    # On partial updates DRF relaxes `required` automatically.
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.all())
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True,
    )

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
