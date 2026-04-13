from rest_framework import serializers
from apps.jobs.models import Job


class JobSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['job_id', 'job_number', 'name', 'status']


class JobSerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'contact', 'contact_name', 'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
        ]
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date']

    def get_contact_name(self, obj):
        return f"{obj.contact.first_name} {obj.contact.last_name}"
