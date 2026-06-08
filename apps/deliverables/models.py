from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.history import history


@history(exclude=['id', 'created_at', 'updated_at'])
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


class DeliverableSnapshot(models.Model):
    """Immutable, write-once copy of a deliverable's agreed scope, attached to the
    document (Estimate or ChangeOrder) it records. No fulfillment data. Exactly one
    of estimate/change_order is set."""

    estimate = models.ForeignKey(
        'estimates.Estimate', on_delete=models.CASCADE,
        null=True, blank=True, related_name='deliverable_snapshots',
    )
    change_order = models.ForeignKey(
        'estimates.ChangeOrder', on_delete=models.CASCADE,
        null=True, blank=True, related_name='deliverable_snapshots',
    )
    version = models.PositiveIntegerField()
    description = models.TextField()
    qty_ordered = models.DecimalField(max_digits=10, decimal_places=2)
    units = models.CharField(max_length=50)
    sort_order = models.PositiveIntegerField(default=0)
    source_deliverable = models.ForeignKey(
        Deliverable, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='snapshots',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'deliverable_snapshots'
        ordering = ['sort_order']

    def clean(self):
        super().clean()
        has_est = self.estimate_id is not None
        has_co = self.change_order_id is not None
        if has_est == has_co:
            raise ValidationError(
                'A DeliverableSnapshot must reference exactly one of estimate / change_order.'
            )

    def __str__(self):
        owner = f'est {self.estimate_id}' if self.estimate_id else f'co {self.change_order_id}'
        return f'Snapshot v{self.version} ({owner}): {self.description}'
