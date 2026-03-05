from decimal import Decimal
from django.db import models


class InventoryItem(models.Model):
    inventory_item_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    units = models.CharField(max_length=50, blank=True, default='sq ft')
    qty_on_hand = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_sold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    qty_wasted = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)

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

    def __str__(self):
        return f"{self.code} - {self.description[:50]}"


class Earmark(models.Model):
    earmark_id = models.AutoField(primary_key=True)
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    created_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('inventory_item', 'job')]

    def __str__(self):
        return f"{self.inventory_item.code} earmarked {self.quantity} for {self.job.job_number}"


class InventoryAdjustment(models.Model):
    adjustment_id = models.AutoField(primary_key=True)
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE)
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.inventory_item.code} adjusted by {self.quantity_change}"
