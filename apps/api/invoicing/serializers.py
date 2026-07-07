from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.core.units import UnitsField


# Net days for invoice due-date calculation. Hardcoded for now; revisit when
# PaymentTerms grows a configurable net-days field or a Configuration key is added.
DEFAULT_INVOICE_NET_DAYS = 30

# Invoice statuses where outstanding balance is owed.
UNPAID_STATUSES = {
    Invoice.STATUS_OPEN,
    Invoice.STATUS_PARTLY_PAID,
    Invoice.STATUS_DEFAULTED,
}


class InvoiceLineItemSourceSerializer(serializers.Serializer):
    """Serializer for InvoiceLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()

    def _resolve_or_none(self, obj):
        # A dangling row (atom deleted out from under the claim — pre-purge
        # data, or a race) must render as null, never 500 the list endpoint.
        from django.core.exceptions import ObjectDoesNotExist
        try:
            return obj.resolve()
        except ObjectDoesNotExist:
            return None

    def get_description(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        return InvoiceWizardService._atom_description(instance)

    def get_computed_amount(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = self._resolve_or_none(obj)
        if instance is None:
            return None
        return str(InvoiceWizardService._atom_computed_amount(instance))


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    accounting_category_name = serializers.SerializerMethodField()
    units = UnitsField()
    sources = InvoiceLineItemSourceSerializer(many=True, read_only=True)
    adjustment_service_detail = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
            'taxable_override', 'tax_rate_override',
            'adjustment_service', 'adjustment_target_categories',
            'adjustment_service_detail',
            'sources',
        ]
        read_only_fields = ['line_item_id']

    def get_accounting_category_name(self, obj):
        if obj.accounting_category:
            return obj.accounting_category.name
        return None

    def get_adjustment_service_detail(self, obj):
        if obj.adjustment_service_id is None:
            return None
        svc = obj.adjustment_service
        return {
            'name': svc.name,
            'rate': str(svc.rate),
            'algorithm': svc.algorithm,
        }


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(
        source='invoicelineitem_set', many=True, read_only=True
    )
    default_send_to = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    job_description = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    is_late = serializers.SerializerMethodField()
    job_has_other_invoices = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'line_items', 'default_send_to',
            'job_number', 'job_name', 'job_description',
            'due_date', 'is_late',
            'job_has_other_invoices',
        ]
        read_only_fields = [
            'invoice_id', 'invoice_number', 'created_date',
            'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'due_date', 'is_late',
            'job_has_other_invoices',
            # Transitions come only from the cancel action / send flow / QBO
            # polling — a bare PATCH must not flip status. (`job` stays
            # writable for CREATE, which routes through open_for_job; the
            # viewset's perform_update strips it so it is create-only.)
            'status',
        ]

    def get_due_date(self, obj):
        if not obj.sent_date:
            return None
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due.date().isoformat()

    def get_is_late(self, obj):
        if not obj.sent_date or obj.status not in UNPAID_STATUSES:
            return False
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due < timezone.now()

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

    def get_job_has_other_invoices(self, obj):
        """Return True if any non-cancelled Invoice exists for this job other than obj."""
        return Invoice.objects.filter(
            job=obj.job,
        ).exclude(
            pk=obj.pk,
        ).exclude(
            status=Invoice.STATUS_CANCELLED,
        ).exists()


class InvoiceSummarySerializer(serializers.ModelSerializer):
    """Lightweight list serializer for the A/R list. Reads total/amount_paid/
    balance/due_date off annotations set by InvoiceViewSet.get_queryset; falls
    back to direct computation if accessed unannotated."""
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    is_late = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'invoice_number', 'status', 'job',
            'job_number', 'job_name', 'customer_name',
            'sent_date', 'due_date', 'is_late',
            'total', 'amount_paid', 'balance',
        ]

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj):
        return getattr(obj.job, 'name', None) if obj.job else None

    def get_customer_name(self, obj):
        contact = obj.job.contact if obj.job else None
        if not contact:
            return None
        if contact.business:
            return contact.business.business_name
        return contact.name

    def get_due_date(self, obj):
        if not obj.sent_date:
            return None
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due.date().isoformat()

    def get_is_late(self, obj):
        if not obj.sent_date or obj.status not in UNPAID_STATUSES:
            return False
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due < timezone.now()

    def get_total(self, obj):
        val = getattr(obj, 'total_anno', None)
        val = val if val is not None else Decimal('0.00')
        return str(Decimal(val).quantize(Decimal('0.01')))

    def get_amount_paid(self, obj):
        anno = getattr(obj, 'amount_paid_anno', None)
        val = anno if anno is not None else (obj.qbo_amount_paid or Decimal('0.00'))
        return str(Decimal(val).quantize(Decimal('0.01')))

    def get_balance(self, obj):
        val = getattr(obj, 'balance_anno', None)
        val = val if val is not None else Decimal('0.00')
        return str(Decimal(val).quantize(Decimal('0.01')))
