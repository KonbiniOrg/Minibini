import re

from rest_framework import serializers

from apps.core.models import EmailRecord, TempEmail
from apps.core.email_utils import strip_quoted_reply


SNIPPET_MAX_CHARS = 80
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\s+')


def _build_snippet(temp):
    """Pipeline from spec §5.1: choose a text source, strip the quoted reply,
    collapse whitespace, truncate to 80 chars with ellipsis."""
    if not temp:
        return ''
    if temp.text_body:
        source = temp.text_body
    elif temp.html_body:
        source = _HTML_TAG_RE.sub('', temp.html_body)
    else:
        return ''
    cleaned = strip_quoted_reply(source)
    flattened = _WHITESPACE_RE.sub(' ', cleaned).strip()
    if len(flattened) > SNIPPET_MAX_CHARS:
        return flattened[: SNIPPET_MAX_CHARS - 1].rstrip() + '…'
    return flattened


class TempEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TempEmail
        fields = [
            'subject', 'from_email', 'to_email', 'cc_email',
            'date_sent', 'is_read', 'is_starred', 'has_attachments',
        ]


class EmailRecordSerializer(serializers.ModelSerializer):
    temp_email = TempEmailSerializer(source='temp_data', read_only=True)
    job_number = serializers.CharField(source='job.job_number', read_only=True, default=None)
    po_number = serializers.CharField(source='purchase_order.po_number', read_only=True, default=None)
    direction = serializers.SerializerMethodField()
    display_address = serializers.SerializerMethodField()
    snippet = serializers.SerializerMethodField()

    class Meta:
        model = EmailRecord
        fields = [
            'email_record_id', 'message_id',
            'job', 'job_number',
            'purchase_order', 'po_number',
            'created_at', 'temp_email',
            'direction', 'display_address', 'snippet',
        ]

    def get_direction(self, obj):
        return obj.direction

    def get_display_address(self, obj):
        temp = getattr(obj, 'temp_data', None)
        if not temp:
            return ''
        if self.get_direction(obj) == 'outbound':
            recipients = [a.strip() for a in (temp.to_email or '').split(',') if a.strip()]
            return recipients[0] if recipients else ''
        return temp.from_email or ''

    def get_snippet(self, obj):
        return _build_snippet(getattr(obj, 'temp_data', None))


from decimal import Decimal
from apps.api.inventory.serializers import OrderLineSerializer
from apps.inventory.models import InventoryItem


class EmailPOLineSerializer(OrderLineSerializer):
    """The email path has no fixed item, so `inventory_item` is allowed
    (null = freeform line, which then needs a description)."""
    inventory_item = serializers.PrimaryKeyRelatedField(
        queryset=InventoryItem.objects.all(), required=False, allow_null=True)
    qty = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if attrs.get('inventory_item') is None and not attrs.get('description'):
            raise serializers.ValidationError(
                {'description': ['A freeform line needs a description.']})
        return attrs


class EmailCreatePOSerializer(serializers.Serializer):
    """POST /api/emails/{id}/create-po/ (PO order flow §4.3). The legacy
    `{vendor_business_id}` body is a valid subset."""
    vendor_business_id = serializers.IntegerField()
    contact_id = serializers.IntegerField(required=False, allow_null=True)
    requested_date = serializers.DateTimeField(required=False, allow_null=True)
    line = EmailPOLineSerializer(required=False, allow_null=True)
