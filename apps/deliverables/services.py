from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
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


def _live_change_order(job):
    """Return the most-recent draft or open ChangeOrder for the job, or None."""
    from apps.estimates.models import ChangeOrder
    return (
        ChangeOrder.objects.filter(
            job=job, status__in=[ChangeOrder.STATUS_DRAFT, ChangeOrder.STATUS_OPEN],
        )
        .order_by('-change_order_id')
        .first()
    )


class DeliverableService:
    """Business-logic facade for the Deliverable model."""

    @staticmethod
    def is_editable(job):
        # A live change order takes priority over the estimate-state rule.
        live_co = _live_change_order(job)
        if live_co is not None:
            from apps.estimates.models import ChangeOrder
            # Draft CO: the proposal is being authored — list is editable.
            if live_co.status == ChangeOrder.STATUS_DRAFT:
                return True
            # Open CO: proposal is out for review — list is locked.
            if live_co.status == ChangeOrder.STATUS_OPEN:
                return False

        # No live CO: fall back to estimate-state rule.
        if _any_accepted_estimate(job):
            return False
        latest = _latest_active_estimate(job)
        if latest is None:
            return True
        return latest.status == Estimate.STATUS_DRAFT

    @staticmethod
    def editability_reason(job):
        live_co = _live_change_order(job)
        if live_co is not None:
            from apps.estimates.models import ChangeOrder
            if live_co.status == ChangeOrder.STATUS_DRAFT:
                return None
            if live_co.status == ChangeOrder.STATUS_OPEN:
                return 'change_order_sent'

        # No live CO: fall back to estimate-state rule.
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
    def create_from_estimate_line(line_item):
        """The Make Deliverable button (better-fees spec §6): copy the line's
        description/qty/units into a new Deliverable on the line's job, linked
        back via the `source_line` provenance FK. Provenance only — no sync;
        the FK is what suppresses re-offering the button on this line."""
        job = line_item.estimate.job
        DeliverableService._assert_editable(job)
        if line_item.deliverables.exists():
            raise ValidationError(
                'This line already has a deliverable made from it.')
        d = Deliverable(
            job=job,
            description=line_item.description,
            qty_ordered=line_item.qty,
            units=line_item.units,
            source_line=line_item,
        )
        d.full_clean()
        d.save()
        return d

    @staticmethod
    @transaction.atomic
    def update(*, deliverable, **fields):
        DeliverableService._assert_editable(deliverable.job)
        if ShipmentItem.objects.filter(deliverable=deliverable).exists():
            raise ValidationError(
                'Delivered items are frozen and cannot be edited or removed.'
            )
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
        if ShipmentItem.objects.filter(deliverable=deliverable).exists():
            raise ValidationError(
                'Delivered items are frozen and cannot be edited or removed.'
            )
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

    @staticmethod
    def all_deliverables_shipped(job):
        """True iff every Deliverable on the job is fully picked up.

        Prepared-but-not-picked-up does not count as delivered. A job with no
        deliverables returns True (nothing outstanding). Used by the job
        completion gate.
        """
        for d in Deliverable.objects.filter(job=job):
            fulfillment = DeliverableService.compute_fulfillment(d)
            if fulfillment['qty_picked_up'] < d.qty_ordered:
                return False
        return True

    @staticmethod
    @transaction.atomic
    def snapshot_document(*, estimate=None, change_order=None):
        """Write-once: copy the job's current live deliverables into a
        DeliverableSnapshot set attached to exactly one of estimate / change_order.
        Idempotent — if a snapshot already exists for that document, returns it
        unchanged. Version is the next integer for the job (estimate -> 1, then
        +1 per subsequently-snapshotted document)."""
        from apps.deliverables.models import DeliverableSnapshot
        if (estimate is None) == (change_order is None):
            raise ValidationError('Provide exactly one of estimate / change_order.')
        job = estimate.job if estimate is not None else change_order.job
        existing = list(DeliverableSnapshot.objects.filter(estimate=estimate, change_order=change_order))
        if existing:
            return existing
        # next version = 1 + number of distinct documents already snapshotted for this job
        prior_owners = set(
            DeliverableSnapshot.objects
            .filter(Q(estimate__job=job) | Q(change_order__job=job))
            .values_list('estimate_id', 'change_order_id')
        )
        version = len(prior_owners) + 1
        snaps = []
        for d in Deliverable.objects.filter(job=job).order_by('sort_order', 'pk'):
            snaps.append(DeliverableSnapshot.objects.create(
                estimate=estimate, change_order=change_order, version=version,
                description=d.description, qty_ordered=d.qty_ordered, units=d.units,
                sort_order=d.sort_order, source_deliverable=d,
            ))
        return snaps

    @staticmethod
    @transaction.atomic
    def restore_live_to_snapshot(*, estimate=None, change_order=None):
        """Reconcile the job's UNANCHORED live deliverables back to the snapshot set
        attached to the given document. Anchored (shipped) deliverables are left
        untouched. Re-creates rows that were removed, restores edited rows, and
        deletes unanchored rows that were added after the snapshot."""
        from apps.deliverables.models import DeliverableSnapshot
        if (estimate is None) == (change_order is None):
            raise ValidationError('Provide exactly one of estimate / change_order.')
        job = estimate.job if estimate is not None else change_order.job
        snaps = list(DeliverableSnapshot.objects.filter(estimate=estimate, change_order=change_order))
        # IDs of live rows that correspond to snapshot rows (restored or anchored)
        preserved_ids = set()
        for snap in snaps:
            live = None
            if snap.source_deliverable_id:
                live = Deliverable.objects.filter(pk=snap.source_deliverable_id, job=job).first()
            if live is not None:
                preserved_ids.add(live.pk)
                if ShipmentItem.objects.filter(deliverable=live).exists():
                    continue  # anchored — never touch
                live.description = snap.description
                live.qty_ordered = snap.qty_ordered
                live.units = snap.units
                live.sort_order = snap.sort_order
                live.save()
            else:
                # removed during the dead CO -> re-create
                new_d = Deliverable.objects.create(
                    job=job, description=snap.description, qty_ordered=snap.qty_ordered,
                    units=snap.units, sort_order=snap.sort_order,
                )
                preserved_ids.add(new_d.pk)
        # delete unanchored live rows that aren't in the snapshot (added after it)
        for d in Deliverable.objects.filter(job=job):
            if d.pk in preserved_ids:
                continue
            if ShipmentItem.objects.filter(deliverable=d).exists():
                continue  # anchored
            d.delete()


def _contact_address_lines(contact):
    """Return the contact's address as a list of non-empty lines."""
    lines = []
    for f in ('addr1', 'addr2', 'addr3'):
        v = (getattr(contact, f, '') or '').strip()
        if v:
            lines.append(v)
    city_line_parts = []
    city = (getattr(contact, 'city', '') or '').strip()
    muni = (getattr(contact, 'municipality', '') or '').strip()
    postal = (getattr(contact, 'postal_code', '') or '').strip()
    if city:
        city_line_parts.append(city)
    if muni:
        city_line_parts.append(muni)
    if postal:
        city_line_parts.append(postal)
    if city_line_parts:
        lines.append(', '.join(city_line_parts))
    return lines


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
    def _assert_job_not_on_hold(job):
        if job.on_hold:
            raise ValidationError('Cannot create a shipment while the job is on hold.')

    @staticmethod
    @transaction.atomic
    def create(*, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')
        ShipmentService._assert_job_not_on_hold(job)
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
        """Transition prepared -> picked_up.

        After persisting the status change, calls
        ``JobService.maybe_complete_if_resolved`` so that a job whose
        invoices are already all paid completes as soon as its final
        shipment is picked up.
        """
        try:
            shipment = Shipment.objects.select_for_update().get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFoundError(f'Shipment {pk} not found')
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be marked picked up.')
        shipment.status = Shipment.STATUS_PICKED_UP
        shipment.picked_up_date = timezone.now()
        shipment.save()

        # Trigger the completion check: if all invoices are also resolved
        # this shipment may be the last piece needed to complete the job.
        from apps.jobs.services import JobService
        JobService.maybe_complete_if_resolved(shipment.job)

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
        contact = getattr(shipment.job, 'contact', None)
        business = getattr(contact, 'business', None) if contact else None
        customer = {
            'contact_name': contact.name if contact else '',
            'business_name': business.business_name if business else '',
            'business_address': business.business_address if business else '',
            'contact_address_lines': _contact_address_lines(contact) if contact else [],
        }

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
            'customer': customer,
            'rows': rows,
        }
