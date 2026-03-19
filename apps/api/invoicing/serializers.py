from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(
        source='invoicelineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date', 'line_items',
        ]
        read_only_fields = [
            'invoice_id', 'invoice_number', 'created_date',
            'sent_date', 'closed_date',
        ]
