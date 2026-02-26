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

    def __str__(self):
        return f"{self.code} - {self.description[:50]}"
