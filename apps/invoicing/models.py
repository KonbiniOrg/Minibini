from django.db import models
from django.utils import timezone
from decimal import Decimal
from apps.core.models import BaseLineItem


class Invoice(models.Model):
    INVOICE_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('cancelled', 'Cancelled'),
        ('superseded', 'Superseded'),
        ('partly-paid', 'Partly Paid'),
        ('paid', 'Paid in Full'),
        ('defaulted', 'Defaulted'),
    ]

    invoice_id = models.AutoField(primary_key=True)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='draft')
    created_date = models.DateTimeField(default=timezone.now)
    # date the invoice was sent to the customer and stopped being editable
    sent_date = models.DateTimeField(null=True, blank=True)
    # date the estimate was Paid in Full, or marked Defaulted
    closed_date = models.DateTimeField(null=True, blank=True)

    @property
    def customer_po_number(self):
        """Get customer PO number from the associated Job."""
        return self.job.customer_po_number

    def save(self, *args, **kwargs):
        """Override save to auto-generate invoice_number if not provided."""
        from apps.core.services import NumberGenerationService

        # Auto-generate invoice_number if not provided
        if not self.invoice_number:
            self.invoice_number = NumberGenerationService.generate_next_number('invoice')

        # Call parent save
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice {self.invoice_number}"



class PriceListItem(models.Model):
    price_list_item_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=50)
    units = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_on_hand = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_sold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_wasted = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)  # For soft-delete - use instead of hard deletion

    def __str__(self):
        return f"{self.code} - {self.description[:50]}"

    @property
    def can_be_deleted(self):
        """
        Check if this price list item can be safely deleted.
        Returns False if any line items reference it.

        Note: With PROTECT on_delete, this check is now enforced at the database level.
        This property is useful for UI to show/hide delete buttons.
        """
        from apps.jobs.models import EstimateLineItem
        from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem

        return not (
            EstimateLineItem.objects.filter(price_list_item=self).exists() or
            InvoiceLineItem.objects.filter(price_list_item=self).exists() or
            PurchaseOrderLineItem.objects.filter(price_list_item=self).exists() or
            BillLineItem.objects.filter(price_list_item=self).exists()
        )



class InvoiceLineItem(BaseLineItem):
    """Line item for invoices - inherits shared functionality from BaseLineItem."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Invoice Line Item"
        verbose_name_plural = "Invoice Line Items"

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'invoice'

    def __str__(self):
        return f"Invoice Line Item {self.pk} for {self.invoice.invoice_number}"