from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.estimates.models import Estimate
from apps.core.services import NotFoundError


# Estimate statuses that don't count as "active" — these are terminal/inactive
# for the purposes of computing the latest active estimate.
_INACTIVE_ESTIMATE_STATUSES = {
    Estimate.STATUS_SUPERSEDED,
    Estimate.STATUS_REJECTED,
    Estimate.STATUS_EXPIRED,
}


def _latest_active_estimate(job):
    return (
        Estimate.objects.filter(job=job)
        .exclude(status__in=_INACTIVE_ESTIMATE_STATUSES)
        .order_by('-version', '-pk')
        .first()
    )


def _any_accepted_estimate(job):
    return Estimate.objects.filter(
        job=job, status=Estimate.STATUS_ACCEPTED,
    ).exists()


class DeliverableService:
    """Business-logic facade for the Deliverable model."""

    @staticmethod
    def is_editable(job):
        if _any_accepted_estimate(job):
            return False
        latest = _latest_active_estimate(job)
        if latest is None:
            return True
        return latest.status == Estimate.STATUS_DRAFT

    @staticmethod
    def editability_reason(job):
        if _any_accepted_estimate(job):
            return 'estimate_accepted'
        latest = _latest_active_estimate(job)
        if latest is None or latest.status == Estimate.STATUS_DRAFT:
            return None
        if latest.status == Estimate.STATUS_OPEN:
            return 'estimate_sent'
        return None

    @staticmethod
    def _assert_editable(job):
        if not DeliverableService.is_editable(job):
            raise ValidationError('Deliverables list is not editable in the current state.')

    @staticmethod
    @transaction.atomic
    def create(*, job_id, description, qty_ordered, units, sort_order=None):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')
        DeliverableService._assert_editable(job)
        d = Deliverable(
            job=job,
            description=description,
            qty_ordered=qty_ordered,
            units=units,
        )
        if sort_order is not None:
            d.sort_order = sort_order
        d.full_clean()
        d.save()
        return d

    @staticmethod
    @transaction.atomic
    def update(*, deliverable, **fields):
        DeliverableService._assert_editable(deliverable.job)
        allowed = {'description', 'qty_ordered', 'units', 'sort_order'}
        for field, value in fields.items():
            if field not in allowed:
                raise ValidationError(f'Field {field!r} is not updatable.')
            setattr(deliverable, field, value)
        deliverable.full_clean()
        deliverable.save()
        return deliverable

    @staticmethod
    @transaction.atomic
    def delete(*, deliverable):
        DeliverableService._assert_editable(deliverable.job)
        job = deliverable.job
        deliverable.delete()
        remaining = list(
            Deliverable.objects.filter(job=job).order_by('sort_order', 'pk')
        )
        for idx, item in enumerate(remaining, start=1):
            new_sort = idx * 10
            if item.sort_order != new_sort:
                item.sort_order = new_sort
                item.save(update_fields=['sort_order', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def reorder(*, job, ordered_ids):
        DeliverableService._assert_editable(job)
        for idx, pk in enumerate(ordered_ids, start=1):
            Deliverable.objects.filter(pk=pk, job=job).update(sort_order=idx * 10)
        return list(
            Deliverable.objects.filter(job=job).order_by('sort_order')
        )

    @staticmethod
    def compute_fulfillment(deliverable):
        items = ShipmentItem.objects.filter(
            deliverable=deliverable,
        ).select_related('shipment')
        picked_up = Decimal('0')
        prepped = Decimal('0')
        for item in items:
            if item.shipment.status == Shipment.STATUS_PICKED_UP:
                picked_up += item.qty
            elif item.shipment.status == Shipment.STATUS_PREPARED:
                prepped += item.qty
        return {
            'qty_ordered': deliverable.qty_ordered,
            'qty_picked_up': picked_up,
            'qty_prepped': prepped,
            'qty_remaining': deliverable.qty_ordered - picked_up - prepped,
        }


class ShipmentService:
    """Business-logic facade for the Shipment + ShipmentItem models."""

    @staticmethod
    def _assert_d_list_locked(job):
        if not _any_accepted_estimate(job):
            raise ValidationError(
                'Cannot create a shipment until the deliverables list is locked '
                '(estimate accepted).'
            )

    @staticmethod
    @transaction.atomic
    def create(*, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')
        ShipmentService._assert_d_list_locked(job)
        last = Shipment.objects.filter(job=job).order_by('-sequence').first()
        next_seq = (last.sequence + 1) if last else 1
        s = Shipment.objects.create(
            job=job,
            sequence=next_seq,
            status=Shipment.STATUS_PREPARED,
            prepared_date=timezone.now(),
        )
        return s

    @staticmethod
    @transaction.atomic
    def update(*, shipment, **fields):
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be edited.')
        allowed = {'notes'}
        for field, value in fields.items():
            if field not in allowed:
                raise ValidationError(f'Field {field!r} is not updatable.')
            setattr(shipment, field, value)
        shipment.full_clean()
        shipment.save()
        return shipment

    @staticmethod
    @transaction.atomic
    def delete(*, shipment):
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be deleted.')
        if shipment.items.exists():
            raise ValidationError('Remove items before deleting the shipment.')
        shipment.delete()

    @staticmethod
    @transaction.atomic
    def mark_picked_up(pk):
        """Transition prepared -> picked_up."""
        try:
            shipment = Shipment.objects.select_for_update().get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFoundError(f'Shipment {pk} not found')
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be marked picked up.')
        shipment.status = Shipment.STATUS_PICKED_UP
        shipment.picked_up_date = timezone.now()
        shipment.save()
        return shipment

    @staticmethod
    def _validate_qty_bounds(deliverable, *, requested_qty, exclude_item_id=None):
        if requested_qty is None:
            raise ValidationError('Quantity is required.')
        try:
            requested_qty = Decimal(str(requested_qty))
        except (TypeError, ValueError, ArithmeticError):
            raise ValidationError('Quantity must be a number.')
        if requested_qty <= 0:
            raise ValidationError('Quantity must be greater than zero.')
        existing = ShipmentItem.objects.filter(deliverable=deliverable)
        if exclude_item_id is not None:
            existing = existing.exclude(pk=exclude_item_id)
        already_committed = sum(
            (item.qty for item in existing),
            Decimal('0'),
        )
        if already_committed + requested_qty > deliverable.qty_ordered:
            raise ValidationError(
                f'Quantity exceeds remaining ({deliverable.qty_ordered - already_committed}).'
            )
        return requested_qty

    @staticmethod
    @transaction.atomic
    def add_item(*, shipment, deliverable_id, qty):
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be added to prepared shipments.')
        try:
            deliverable = Deliverable.objects.select_for_update().get(
                pk=deliverable_id, job=shipment.job,
            )
        except Deliverable.DoesNotExist:
            raise NotFoundError(f'Deliverable {deliverable_id} not found for this Job')
        qty = ShipmentService._validate_qty_bounds(deliverable, requested_qty=qty)
        item = ShipmentItem(shipment=shipment, deliverable=deliverable, qty=qty)
        item.full_clean()
        item.save()
        return item

    @staticmethod
    @transaction.atomic
    def update_item(*, item, qty):
        if item.shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be edited on prepared shipments.')
        deliverable = Deliverable.objects.select_for_update().get(pk=item.deliverable_id)
        qty = ShipmentService._validate_qty_bounds(
            deliverable, requested_qty=qty, exclude_item_id=item.pk,
        )
        item.qty = qty
        item.full_clean()
        item.save()
        return item

    @staticmethod
    @transaction.atomic
    def remove_item(*, item):
        if item.shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be removed from prepared shipments.')
        item.delete()

    @staticmethod
    def packing_list_payload(shipment):
        """Return JSON-serializable payload for the printable packing list view.

        Decimal quantities are emitted as strings with two decimal places to
        match the project's API convention.
        """
        deliverables = list(
            Deliverable.objects.filter(job=shipment.job).order_by('sort_order', 'pk')
        )
        items_for_job = list(
            ShipmentItem.objects
            .filter(shipment__job=shipment.job)
            .select_related('shipment')
        )

        two_places = Decimal('0.01')
        rows = []
        for d in deliverables:
            qty_this = Decimal('0')
            qty_prev = Decimal('0')
            for item in items_for_job:
                if item.deliverable_id != d.pk:
                    continue
                if item.shipment_id == shipment.pk:
                    qty_this = item.qty
                elif item.shipment.status == Shipment.STATUS_PICKED_UP:
                    qty_prev += item.qty
            qty_remaining_after = d.qty_ordered - qty_prev - qty_this
            rows.append({
                'deliverable_id': d.pk,
                'description': d.description,
                'units': d.units,
                'qty_ordered': str(d.qty_ordered.quantize(two_places)),
                'qty_this_shipment': str(qty_this.quantize(two_places)),
                'qty_previously_picked_up': str(qty_prev.quantize(two_places)),
                'qty_remaining_after_this_shipment': str(qty_remaining_after.quantize(two_places)),
            })
        return {
            'shipment': {
                'id': shipment.pk,
                'sequence': shipment.sequence,
                'status': shipment.status,
                'prepared_date': shipment.prepared_date,
                'picked_up_date': shipment.picked_up_date,
                'notes': shipment.notes,
            },
            'job': {
                'id': shipment.job.pk,
                'job_number': shipment.job.job_number,
                'name': shipment.job.name,
            },
            'rows': rows,
        }
