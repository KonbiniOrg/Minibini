from decimal import Decimal
from django.db import models


class Earmark(models.Model):
    earmark_id = models.AutoField(primary_key=True)
    price_list_item = models.ForeignKey('PriceListItem', on_delete=models.CASCADE)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    created_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'earmarks'
        unique_together = [('price_list_item', 'job')]

    def __str__(self):
        return f"{self.price_list_item.code} earmarked {self.quantity} for {self.job.job_number}"


class InventoryAdjustment(models.Model):
    adjustment_id = models.AutoField(primary_key=True)
    price_list_item = models.ForeignKey('PriceListItem', on_delete=models.CASCADE)
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inv_adjustments'

    def __str__(self):
        return f"{self.price_list_item.code} adjusted by {self.quantity_change}"


class PriceListItem(models.Model):
    price_list_item_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=50, unique=True)
    units = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_on_hand = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_sold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_wasted = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)  # For soft-delete - use instead of hard deletion
    is_inventoried = models.BooleanField(default=False)

    # AccountingCategory for categorization and taxability
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        related_name='price_list_items',
        null=True,  # Nullable initially for migration; will be made required after data migration
        blank=True
    )

    @property
    def qty_earmarked(self):
        """Total quantity earmarked across all jobs."""
        total = self.earmark_set.aggregate(
            total=models.Sum('quantity')
        )['total']
        return total or Decimal('0.00')

    @property
    def qty_available(self):
        """Quantity available (on hand minus earmarked)."""
        return self.qty_on_hand - self.qty_earmarked

    class Meta:
        db_table = 'price_list'

    def __str__(self):
        return f"{self.code} - {self.description[:50]}"

    @property
    def can_be_deleted(self):
        """
        Check if this price list item can be safely deleted.
        Returns False if any line items reference it.
        """
        from apps.estimates.models import EstimateLineItem
        from apps.invoicing.models import InvoiceLineItem
        from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem

        return not (
            EstimateLineItem.objects.filter(price_list_item=self).exists() or
            InvoiceLineItem.objects.filter(price_list_item=self).exists() or
            PurchaseOrderLineItem.objects.filter(price_list_item=self).exists() or
            BillLineItem.objects.filter(price_list_item=self).exists() or
            self.earmark_set.exists() or
            self.inventoryadjustment_set.exists()
        )


class Material(models.Model):
    material_id = models.AutoField(primary_key=True)
    task = models.ForeignKey('jobs.Task', on_delete=models.CASCADE, related_name='materials')
    price_list_item = models.ForeignKey(
        PriceListItem, on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost

    @property
    def total_sell(self):
        return self.quantity * self.sell_price

    def save(self, *args, **kwargs):
        # Auto-fill from price list item if linked
        if self.price_list_item:
            if not self.description:
                self.description = self.price_list_item.description[:255]
            if self.unit_cost == Decimal('0.00'):
                self.unit_cost = self.price_list_item.purchase_price
            if self.sell_price == Decimal('0.00'):
                self.sell_price = self.price_list_item.selling_price
            if not self.accounting_category:
                self.accounting_category = self.price_list_item.accounting_category
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'materials'

    def __str__(self):
        return f"{self.description} (qty: {self.quantity})"
