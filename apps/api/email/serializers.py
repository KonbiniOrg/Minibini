from rest_framework import serializers
from apps.core.models import EmailRecord, TempEmail


class TempEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TempEmail
        fields = [
            'subject', 'from_email', 'to_email', 'cc_email',
            'date_sent', 'is_read', 'is_starred', 'has_attachments',
        ]


class EmailRecordSerializer(serializers.ModelSerializer):
    temp_email = TempEmailSerializer(source='temp_data', read_only=True)

    class Meta:
        model = EmailRecord
        fields = ['email_record_id', 'message_id', 'job', 'created_at', 'temp_email']
