from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.core.units import UnitsField
from apps.core.wizard import BaseWizardService


# Net days for invoice due-date calculation. Hardcoded for now; revisit when
# PaymentTerms grows a configurable net-days field or a Configuration key is added.
DEFAULT_INVOICE_NET_DAYS = 30

# Invoice statuses where outstanding balance is owed.
UNPAID_STATUSES = {
    Invoice.STATUS_OPEN,
    Invoice.STATUS_PARTLY_PAID,
    Invoice.STATUS_DEFAULTED,
}


def _agreement_ref_payload(line):
    """The `agreement_ref` field: null, or {kind, line_id, est_qty,
    est_price, est_amount} sourced from the referenced agreement line's own
    stored qty/price — never from the invoice line's current values.

    Values are stringified explicitly: this dict is returned from a plain
    SerializerMethodField, not routed through a DecimalField, so DRF's
    JSONEncoder never gets a chance to apply its normal (settings-driven)
    decimal-to-string coercion — its raw fallback for a bare Decimal is
    always `float(obj)` (see rest_framework.utils.encoders.JSONEncoder).
    An un-stringified payload silently ships floats: string/string
    equality checks (e.g. the frontend's actuals==estimate "synced" chip)
    never match, and PATCHing a float back as qty/price 400s against the
    model field's DecimalValidator for the ~96% of prices that need more
    than float's imprecise binary expansion. Same reasoning as
    `_serialize_agreement_line` in apps/api/invoicing/views.py."""
    ref = getattr(line, 'agreement_estimate_line', None)
    kind = 'estimate'
    if ref is None:
        ref = getattr(line, 'agreement_co_line', None)
        kind = 'change_order'
    if ref is None:
        return None
    return {
        'kind': kind,
        'line_id': ref.pk,
        'est_qty': str(ref.qty),
        'est_price': str(ref.price),
        'est_amount': str((ref.qty * ref.price).quantize(Decimal('0.01'))),
    }


def derive_backing(line):
    """Classify how a line's price is currently backed. Never stored —
    recomputed on every read from the line's own state (the CO surface
    reuses this for ChangeOrderLineItem/EstimateLineItem, so it is written
    duck-typed rather than importing InvoiceLineItem specifics):

    1. `is_deposit_line` -> 'deposit'; `is_deposit_deduction` -> 'deposit_credit'
       (invoice-only properties; default False when the line type lacks them).
    2. Has claimed source rows AND is in sync with them (the wizard's own
       `price == round(sum(sources) / qty, 2)` rule) -> 'actuals'.
    3. Has an agreement_ref AND qty/price still equal the ref's stored
       qty/price -> 'estimate'.
    4. Has an agreement_ref or sources, but matched neither rule above
       (hand-edited since seeding, or a claimed-but-out-of-sync line) ->
       'edited'.
    5. Otherwise (a plain hand line) -> None.
    """
    if getattr(line, 'is_deposit_line', False):
        return 'deposit'
    if getattr(line, 'is_deposit_deduction', False):
        return 'deposit_credit'

    sources = list(line.sources.all())
    if sources:
        sum_value = BaseWizardService._sum_sources(line)
        if BaseWizardService._is_in_sync(line, sum_value):
            return 'actuals'

    ref = getattr(line, 'agreement_line', None)
    if ref is not None and line.qty == ref.qty and line.price == ref.price:
        return 'estimate'

    if ref is not None or sources:
        return 'edited'

    return None


class InvoiceLineItemSourceSerializer(serializers.Serializer):
    """Serializer for InvoiceLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()
    qty = serializers.SerializerMethodField()
    units = serializers.SerializerMethodField()
    rate = serializers.SerializerMethodField()

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

    def _atom_detail_or_none(self, obj):
        """The {qty, rate, units, amount} breakdown for the nested atom row
        — the same helper the source pool itself uses
        (InvoiceWizardService._atom_detail: real task actual-qty ×
        effective_rate, material quantity × sell_price, fee quantity ×
        unit_rate). None for a dangling source AND for a deposit-credit
        claim — that resolves to another InvoiceLineItem, not a real work
        atom (get_actuals_total skips it the same way), so a fabricated
        qty/rate would be misleading rather than informative."""
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService
        instance = self._resolve_or_none(obj)
        if instance is None or isinstance(instance, InvoiceLineItem):
            return None
        return InvoiceWizardService._atom_detail(instance)

    def get_qty(self, obj):
        detail = self._atom_detail_or_none(obj)
        return str(detail['qty']) if detail else None

    def get_units(self, obj):
        detail = self._atom_detail_or_none(obj)
        return detail['units'] if detail else None

    def get_rate(self, obj):
        detail = self._atom_detail_or_none(obj)
        return str(detail['rate']) if detail else None


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    accounting_category_name = serializers.SerializerMethodField()
    units = UnitsField()
    sources = InvoiceLineItemSourceSerializer(many=True, read_only=True)
    adjustment_service_detail = serializers.SerializerMethodField()
    is_deposit = serializers.SerializerMethodField()
    agreement_ref = serializers.SerializerMethodField()
    backing = serializers.SerializerMethodField()
    actuals_total = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'inventory_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
                        'adjustment_service', 'adjustment_target_categories',
            'adjustment_service_detail',
            'sources', 'is_deposit',
            'agreement_ref', 'backing', 'actuals_total',
        ]
        read_only_fields = ['line_item_id']

    def get_accounting_category_name(self, obj):
        if obj.accounting_category:
            return obj.accounting_category.name
        return None

    def get_is_deposit(self, obj):
        return obj.is_deposit_line

    def get_agreement_ref(self, obj):
        return _agreement_ref_payload(obj)

    def get_backing(self, obj):
        return derive_backing(obj)

    def get_actuals_total(self, obj):
        """Sum of compute_amount() over claimed work atoms — null when the
        line has no such sources. Independent of `backing`: an out-of-sync
        ('edited') claimed line still reports its actuals total as the
        est-vs-actual reference figure. A SOURCE_DEPOSIT claim resolves to
        another InvoiceLineItem (no compute_amount — it isn't a work atom,
        just a credit against a deposit charge) and is skipped, same as a
        dangling/unresolvable source."""
        total = Decimal('0.00')
        found = False
        for src in obj.sources.all():
            from django.core.exceptions import ObjectDoesNotExist
            try:
                instance = src.resolve()
            except ObjectDoesNotExist:
                instance = None
            if instance is None or not hasattr(instance, 'compute_amount'):
                continue
            found = True
            total += BaseWizardService._atom_computed_amount(instance)
        if not found:
            return None
        return str(total.quantize(Decimal('0.01')))

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
    total = serializers.SerializerMethodField()
    is_deposit = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'display_number', 'status',
            'created_date', 'sent_date', 'closed_date',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'line_items', 'default_send_to',
            'job_number', 'job_name', 'job_description',
            'due_date', 'is_late',
            'job_has_other_invoices', 'total', 'is_deposit',
        ]
        read_only_fields = [
            'invoice_id', 'invoice_number', 'display_number', 'created_date',
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

    def get_total(self, obj):
        # Authoritative document total: summed line qty*price, matching
        # InvoiceSummarySerializer.total_anno and financials._invoiced. The
        # job-overview Invoicing block consumes this rather than recomputing on
        # the client (adjustment/percentage lines make client qty*price fragile).
        total = sum(
            (li.qty * li.price for li in obj.invoicelineitem_set.all()),
            Decimal('0'),
        )
        return str(total.quantize(Decimal('0.01')))

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

    def get_is_deposit(self, obj):
        return any(li.is_deposit_line
                   for li in obj.invoicelineitem_set.all())


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
    is_deposit = serializers.BooleanField(
        source='has_deposit', read_only=True, default=False)

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'invoice_number', 'display_number', 'status', 'job',
            'job_number', 'job_name', 'customer_name',
            'sent_date', 'due_date', 'is_late',
            'total', 'amount_paid', 'balance', 'is_deposit',
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
