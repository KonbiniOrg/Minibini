from rest_framework import serializers
from apps.jobs.models import Job


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'contact', 'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
        ]
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date']
