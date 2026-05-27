from django.db import models
from django.utils import timezone


class Deliverable(models.Model):
    """A finished item the customer is buying on a Job. No price; quantity + units only."""

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='deliverables',
    )
    description = models.TextField()
    qty_ordered = models.DecimalField(max_digits=10, decimal_places=2)
    units = models.CharField(max_length=50)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'deliverables'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        if not self.pk and not self.sort_order:
            last = Deliverable.objects.filter(job=self.job).order_by('-sort_order').first()
            self.sort_order = (last.sort_order + 10) if last else 10
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.description} (qty {self.qty_ordered} {self.units})'


class Shipment(models.Model):
    """A single fulfillment event for a Job. Multiple Shipments per Job for phased delivery."""

    STATUS_PREPARED = 'prepared'
    STATUS_PICKED_UP = 'picked_up'
    STATUS_CHOICES = [
        (STATUS_PREPARED, 'Prepared'),
        (STATUS_PICKED_UP, 'Picked up'),
    ]

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='shipments',
    )
    sequence = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PREPARED,
    )
    prepared_date = models.DateTimeField(default=timezone.now)
    picked_up_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shipments'
        ordering = ['sequence']
        unique_together = [('job', 'sequence')]

    def __str__(self):
        return f'Shipment #{self.sequence} on Job {self.job_id}'


class ShipmentItem(models.Model):
    """A single Deliverable contribution to a Shipment. One row per (shipment, deliverable) pair."""

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='items',
    )
    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.PROTECT,
        related_name='shipment_items',
    )
    qty = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'shipment_items'
        unique_together = [('shipment', 'deliverable')]
        ordering = ['deliverable__sort_order']

    def __str__(self):
        return f'{self.qty} {self.deliverable.units} of {self.deliverable.description}'
