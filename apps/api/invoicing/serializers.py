from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    accounting_category_name = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
            'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']

    def get_accounting_category_name(self, obj):
        if obj.accounting_category:
            return obj.accounting_category.name
        return None


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(
        source='invoicelineitem_set', many=True, read_only=True
    )
    default_send_to = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'line_items', 'default_send_to', 'job_number',
        ]
        read_only_fields = [
            'invoice_id', 'invoice_number', 'created_date',
            'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
        ]

    def get_default_send_to(self, obj):
        """Return the job contact's email for pre-filling Send To."""
        if obj.job and obj.job.contact:
            return obj.job.contact.email
        return ''

    def get_job_number(self, obj):
        """Return the job number for display."""
        if obj.job:
            return obj.job.job_number
        return None
