from rest_framework import serializers
from apps.jobs.models import Job
from apps.estimates.models import WorkTemplate


class JobSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['job_id', 'job_number', 'name', 'status']


class JobSerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkTemplate.objects.all(),
        source='template',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'contact', 'contact_name', 'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
            'tasks', 'template', 'template_id',
        ]
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date']

    def get_contact_name(self, obj):
        return f"{obj.contact.first_name} {obj.contact.last_name}"

    def get_tasks(self, obj):
        from apps.api.tasks.serializers import TaskSerializer
        # Use .all() so prefetch_related cache is hit when configured.
        # The viewset prefetches tasks already ordered by sort_order.
        tasks = obj.tasks.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'tasks' not in obj._prefetched_objects_cache:
            tasks = tasks.order_by('sort_order')
        return TaskSerializer(tasks, many=True).data

    def get_template(self, obj):
        if obj.template_id is None:
            return None
        from apps.api.templates_config.serializers import WorkTemplateSerializer
        return WorkTemplateSerializer(obj.template).data
