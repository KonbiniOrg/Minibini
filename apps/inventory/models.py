from decimal import Decimal
from django.db import models


class Earmark(models.Model):
    earmark_id = models.AutoField(primary_key=True)
    price_list_item = models.ForeignKey('invoicing.PriceListItem', on_delete=models.CASCADE)
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    created_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('price_list_item', 'job')]

    def __str__(self):
        return f"{self.price_list_item.code} earmarked {self.quantity} for {self.job.job_number}"


class InventoryAdjustment(models.Model):
    adjustment_id = models.AutoField(primary_key=True)
    price_list_item = models.ForeignKey('invoicing.PriceListItem', on_delete=models.CASCADE)
    quantity_change = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True, default='')
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.price_list_item.code} adjusted by {self.quantity_change}"
