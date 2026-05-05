from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.core.units import UnitsField


class InvoiceLineItemSourceSerializer(serializers.Serializer):
    """Serializer for InvoiceLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()

    def get_description(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = obj.resolve()
        return InvoiceWizardService._atom_description(instance)

    def get_computed_amount(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = obj.resolve()
        return str(InvoiceWizardService._atom_computed_amount(instance))


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    accounting_category_name = serializers.SerializerMethodField()
    units = UnitsField()
    sources = InvoiceLineItemSourceSerializer(many=True, read_only=True)

    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
            'taxable_override', 'tax_rate_override',
            'sources',
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
    job_name = serializers.SerializerMethodField()
    job_description = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'line_items', 'default_send_to',
            'job_number', 'job_name', 'job_description',
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

    def get_job_name(self, obj):
        """Return the job's short name for display."""
        if obj.job:
            return obj.job.name
        return ''

    def get_job_description(self, obj):
        """Return the job description for display."""
        if obj.job:
            return obj.job.description
        return ''
