from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.core.models import BaseLineItem
from apps.core.history import history


@history(exclude=['invoice_id'])
class Invoice(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_OPEN = 'open'
    STATUS_CANCELLED = 'cancelled'
    STATUS_SUPERSEDED = 'superseded'
    STATUS_PARTLY_PAID = 'partly-paid'
    STATUS_PAID = 'paid'
    STATUS_DEFAULTED = 'defaulted'

    INVOICE_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_OPEN, 'Open'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_SUPERSEDED, 'Superseded'),
        (STATUS_PARTLY_PAID, 'Partly Paid'),
        (STATUS_PAID, 'Paid in Full'),
        (STATUS_DEFAULTED, 'Defaulted'),
    ]

    invoice_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default=STATUS_DRAFT)
    created_date = models.DateTimeField(default=timezone.now)
    # date the invoice was sent to the customer and stopped being editable
    sent_date = models.DateTimeField(null=True, blank=True)
    # date the estimate was Paid in Full, or marked Defaulted
    closed_date = models.DateTimeField(null=True, blank=True)

    # QuickBooks Online sync
    qbo_id = models.CharField(max_length=50, null=True)
    qbo_payment_status = models.CharField(max_length=50, blank=True, default='')
    qbo_amount_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    @property
    def customer_po_number(self):
        """Get customer PO number from the associated Job."""
        return self.job.customer_po_number

    def clean(self):
        super().clean()
        if self.pk:
            try:
                old_invoice = Invoice.objects.get(pk=self.pk)
                if old_invoice.status == Invoice.STATUS_DRAFT and self.status != Invoice.STATUS_DRAFT:
                    if not InvoiceLineItem.objects.filter(invoice=self).exists():
                        raise ValidationError(
                            'Cannot change Invoice status from Draft without at least one line item.'
                        )
            except Invoice.DoesNotExist:
                pass
        # Enforce single-draft-per-job at the application layer. The
        # equivalent partial UniqueConstraint is declared on Meta but
        # MySQL silently drops conditional constraints (W036), so this
        # check is the load-bearing one.
        if self.job_id and self.status == Invoice.STATUS_DRAFT:
            existing = Invoice.objects.filter(
                job_id=self.job_id, status=Invoice.STATUS_DRAFT,
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError(
                    'A draft invoice already exists for this job.'
                )

    def save(self, *args, **kwargs):
        """Override save to auto-generate invoice_number and check job completion."""
        from apps.core.services import NumberGenerationService

        old_status = None
        if self.pk:
            try:
                old_invoice = Invoice.objects.get(pk=self.pk)
                old_status = old_invoice.status
            except Invoice.DoesNotExist:
                pass

        # Stamp sent_date the first time the invoice leaves draft for open
        # (the send-to-customer transition; mirrors Estimate.save()). This is
        # what the serializer's derived due_date / is_late read off of.
        if (old_status == Invoice.STATUS_DRAFT
                and self.status == Invoice.STATUS_OPEN and not self.sent_date):
            self.sent_date = timezone.now()

        # Stamp closed_date the first time the invoice is marked paid (any path).
        if (old_status and old_status != self.status
                and self.status == Invoice.STATUS_PAID and not self.closed_date):
            self.closed_date = timezone.now()

        # Auto-generate invoice_number if not provided
        if not self.invoice_number:
            self.invoice_number = NumberGenerationService.generate_next_number('invoice')

        self.clean()

        # Call parent save
        super().save(*args, **kwargs)

        # Check if status changed to paid and all invoices for the job are now paid
        if old_status and old_status != self.status and self.status == Invoice.STATUS_PAID:
            self._maybe_complete_job()

    def _maybe_complete_job(self):
        """Delegate to JobService.maybe_complete_if_resolved.

        Completes the job if all its invoices are resolved (paid/cancelled)
        AND all its deliverables are fully picked up.  If either condition is
        unmet the job is left in its current status and the check will be
        re-triggered by the other path (shipment pickup or further invoice
        payments).
        """
        from apps.jobs.services import JobService
        JobService.maybe_complete_if_resolved(self.job)

    class Meta:
        db_table = 'invoices'
        constraints = [
            models.UniqueConstraint(
                fields=['job'],
                condition=models.Q(status='draft'),
                name='unique_draft_invoice_per_job',
            ),
        ]

    def __str__(self):
        return f"Invoice {self.invoice_number}"


class InvoiceLineItem(BaseLineItem):
    """Line item for invoices - inherits shared functionality from BaseLineItem."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)
    adjustment_service = models.ForeignKey(
        'jobs.ServiceItem', on_delete=models.PROTECT,
        null=True, blank=True, related_name='+',
        help_text='Set when this line is a percentage adjustment (rush/discount).',
    )
    adjustment_target_categories = models.ManyToManyField(
        'core.AccountingCategory', blank=True, related_name='+',
        help_text='Categories the adjustment applies to; empty = all non-adjustment lines.',
    )

    class Meta:
        db_table = 'invoice_li'
        verbose_name = "Invoice Line Item"
        verbose_name_plural = "Invoice Line Items"

    @property
    def task(self):
        """InvoiceLineItem no longer has a direct task FK. Kept as None for BaseLineItem.clean() compatibility."""
        return None

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'invoice'

    def __str__(self):
        return f"Invoice Line Item {self.pk} for {self.invoice.invoice_number}"


class InvoiceLineItemSource(models.Model):
    """Polymorphic join between an InvoiceLineItem and its source atom (Task or Material).

    The unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level: an atom can be referenced by at most one line item.
    """
    SOURCE_MATERIAL = 'material'
    SOURCE_TASK = 'task'
    SOURCE_EXPENSE = 'expense'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_MATERIAL, 'Material'),
        (SOURCE_TASK, 'Task'),
        (SOURCE_EXPENSE, 'Expense'),
    ]

    source_id = models.AutoField(primary_key=True)
    invoice_line_item = models.ForeignKey(
        InvoiceLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'invoice_line_item_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        """Return the concrete atom instance (Material or Task) referenced by this source."""
        if self.source_type == self.SOURCE_MATERIAL:
            from apps.inventory.models import Material
            return Material.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_TASK:
            from apps.jobs.models import Task
            return Task.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_EXPENSE:
            from apps.expenses.models import Expense
            return Expense.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return f'Source {self.source_id}: {self.source_type}:{self.source_pk} → LineItem {self.invoice_line_item_id}'
