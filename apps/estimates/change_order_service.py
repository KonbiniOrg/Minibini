"""
Service class for ChangeOrder lifecycle operations.

Rules:
- A CO can only be created while the job is on_hold.
- Accepting a CO auto-advances the job on_hold -> approved (no Task/Material mutations).
- Rejecting/expiring a CO snapshots the proposal and leaves the job on_hold.
"""

from django.core.exceptions import ValidationError
from apps.core.history import record_history
from django.db import transaction

from apps.core.services import NotFoundError
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate
from apps.jobs.models import Job


class ChangeOrderService:
    """Lifecycle operations for ChangeOrder."""

    @staticmethod
    @transaction.atomic
    def create(*, job_id):
        """Create a draft ChangeOrder for the given job.

        Guards:
        - job.status must be on_hold.
        - job must have an accepted estimate.

        Trigger 1: snapshot the prior agreement onto the latest accepted CO
        for that estimate (if one exists) or the accepted estimate itself.
        snapshot_document is idempotent, so repeat calls are safe.
        """
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')

        if job.status != Job.STATUS_ON_HOLD:
            raise ValidationError(
                'A change order can only be created while the job is on hold.'
            )

        try:
            accepted_est = Estimate.objects.get(job=job, status=Estimate.STATUS_ACCEPTED)
        except Estimate.DoesNotExist:
            raise ValidationError('Job has no accepted estimate to amend.')

        # Trigger 1: snapshot the prior agreement.
        from apps.deliverables.services import DeliverableService
        baseline = ChangeOrderService.baseline_document(co=None, estimate=accepted_est)
        if isinstance(baseline, ChangeOrder):
            DeliverableService.snapshot_document(change_order=baseline)
        else:
            DeliverableService.snapshot_document(estimate=baseline)

        co = ChangeOrder.objects.create(job=job, estimate=accepted_est)
        return co

    @staticmethod
    def baseline_document(*, co, estimate=None):
        """Return the document whose DeliverableSnapshot rows are the baseline for *co*.

        Resolution rule (mirrors Trigger 1 in create):
        - The latest accepted ChangeOrder on the estimate with a change_order_id
          strictly less than co.change_order_id (i.e. created before this CO),
          if one exists.
        - Otherwise the accepted Estimate itself.

        ``co`` may be None when called from ``create`` before the new CO is
        saved; in that case ``estimate`` must be supplied and the filter has no
        upper-bound (any accepted CO on the estimate qualifies as "prior").
        """
        est = estimate if estimate is not None else co.estimate
        qs = ChangeOrder.objects.filter(
            estimate=est, status=ChangeOrder.STATUS_ACCEPTED,
        )
        if co is not None:
            qs = qs.filter(change_order_id__lt=co.change_order_id)
        latest_accepted_co = qs.order_by('-change_order_id').first()
        if latest_accepted_co is not None:
            return latest_accepted_co
        return est

    @staticmethod
    def compose_deliverable_diff(co):
        """Baseline-vs-live deliverable diff for a change order, shared by the
        customer portal payload and the CO PDF.

        Baseline = the DeliverableSnapshot rows of the document this CO amends
        (``baseline_document``: the latest accepted CO before it, else the
        estimate); live = the job's current deliverables. Returns a list of
        ``{kind, description, qty, units}`` rows where ``kind`` is one of
        ``unchanged / changed / changed-orig / removed / added`` (a ``changed``
        row — the live value — is followed by its struck ``changed-orig``). qty
        is stringified for JSON/template use."""
        from apps.deliverables.models import DeliverableSnapshot

        baseline_doc = ChangeOrderService.baseline_document(co=co)
        if isinstance(baseline_doc, ChangeOrder):
            base = list(DeliverableSnapshot.objects.filter(
                change_order=baseline_doc).order_by('sort_order'))
        else:
            base = list(DeliverableSnapshot.objects.filter(
                estimate=baseline_doc).order_by('sort_order'))
        live = list(co.job.deliverables.all()) if co.job_id else []  # Meta order = sort_order

        live_by_id = {d.pk: d for d in live}
        baselined_live_ids = {s.source_deliverable_id for s in base
                              if s.source_deliverable_id}

        rows = []
        for snap in base:
            live_row = (live_by_id.get(snap.source_deliverable_id)
                        if snap.source_deliverable_id else None)
            if live_row is None:
                rows.append({'kind': 'removed', 'description': snap.description,
                             'qty': str(snap.qty_ordered), 'units': snap.units})
                continue
            changed = (live_row.description != snap.description
                       or live_row.qty_ordered != snap.qty_ordered
                       or live_row.units != snap.units)
            if changed:
                rows.append({'kind': 'changed', 'description': live_row.description,
                             'qty': str(live_row.qty_ordered), 'units': live_row.units})
                rows.append({'kind': 'changed-orig', 'description': snap.description,
                             'qty': str(snap.qty_ordered), 'units': snap.units})
            else:
                rows.append({'kind': 'unchanged', 'description': live_row.description,
                             'qty': str(live_row.qty_ordered), 'units': live_row.units})

        for d in live:
            if d.pk not in baselined_live_ids:
                rows.append({'kind': 'added', 'description': d.description,
                             'qty': str(d.qty_ordered), 'units': d.units})
        return rows

    @staticmethod
    @transaction.atomic
    def update_status(pk, new_status):
        """Update a ChangeOrder's status with lifecycle side-effects.

        - Accepted: advance job on_hold -> approved; write system HistoryEntry.
          Does NOT create or modify any Task or Material.
        - Rejected / Expired: snapshot the proposal (Trigger 2); leave job on_hold.
        """
        try:
            co = ChangeOrder.objects.select_for_update().get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        old_status = co.status
        co.status = new_status
        co.save()  # Model.clean() validates the transition and sets dates.

        if new_status == ChangeOrder.STATUS_ACCEPTED and old_status != ChangeOrder.STATUS_ACCEPTED:
            ChangeOrderService._handle_accepted(co)

        elif new_status in (ChangeOrder.STATUS_REJECTED, ChangeOrder.STATUS_EXPIRED):
            # Trigger 2: snapshot the proposal.
            from apps.deliverables.services import DeliverableService
            DeliverableService.snapshot_document(change_order=co)

        return co

    @staticmethod
    def _handle_accepted(co):
        """Advance the job on_hold -> approved and write a system-attributed HistoryEntry."""
        from apps.core.models import User
        from apps.jobs.services import JobService

        job = co.job
        job.refresh_from_db()

        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )

        if job.status == Job.STATUS_ON_HOLD:
            old_status = job.status
            JobService.update_job(job.pk, status=Job.STATUS_APPROVED)
            record_history(
                entry_type='action',
                object_type='changeorder',
                object_id=co.pk,
                user=system_user,
                changes={
                    'status': {
                        'old': old_status,
                        'new': Job.STATUS_APPROVED,
                    },
                    '_action': 'Change order accepted',
                },
            )

    @staticmethod
    def mark_open(pk):
        """Transition a draft CO to open."""
        return ChangeOrderService.update_status(pk, ChangeOrder.STATUS_OPEN)

    @staticmethod
    @transaction.atomic
    def request_changes(pk, actor):
        """Customer-initiated revision from the portal — the CO parallel of
        EstimateService.request_changes.

        Records the customer's comment, snapshots the proposal they saw,
        supersedes the open CO, and seeds a fresh draft CO carrying the same
        deltas for the shop to revise. The job stays on_hold (the CO editing
        room); the on_hold exit guard keeps it parked until the new draft is
        resolved — the structural parallel to the estimate flow bouncing the
        job back to draft. ``actor`` is the portal actor dict
        ``{'contact_id', 'email', 'reason'}``. Returns the new draft CO.
        """
        from apps.deliverables.services import DeliverableService

        try:
            co = ChangeOrder.objects.select_for_update().get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        # 1. Record the customer's comment against the CO they saw (same shape
        #    as the estimate flow's customer-action HistoryEntry).
        record_history(
            entry_type='action',
            object_type='changeorder',
            object_id=co.pk,
            user=None,
            changes={
                '_action': 'Changes requested via customer link',
                'contact_id': actor.get('contact_id'),
                'customer_email': actor.get('email'),
            },
            text=actor.get('reason') or '',
        )
        # 2. Preserve the proposal the customer saw, then supersede.
        DeliverableService.snapshot_document(change_order=co)
        co.status = ChangeOrder.STATUS_SUPERSEDED
        co.save()  # sets closed_date
        # 3. Seed a fresh draft CO carrying the same deltas for the shop.
        return ChangeOrderService.seed_new(co.pk)

    @staticmethod
    @transaction.atomic
    def seed_new(pk):
        """Create a new draft CO by copying all line items from an existing (terminal) CO.

        The source CO retains its status. The new CO gets parent=source.
        Line items are copied directly (no renumbering).
        """
        try:
            src = ChangeOrder.objects.get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        new_co = ChangeOrder.objects.create(
            job=src.job,
            estimate=src.estimate,
            parent=src,
        )

        for li in ChangeOrderLineItem.objects.filter(change_order=src):
            ChangeOrderLineItem.objects.create(
                change_order=new_co,
                action=li.action,
                target_line_item=li.target_line_item,
                description=li.description,
                qty=li.qty,
                units=li.units,
                price=li.price,
                line_number=li.line_number,
                source_template=li.source_template,
                price_list_item=li.price_list_item,
            )

        return new_co

    @staticmethod
    def discard_draft(pk):
        """Hard-delete a draft CO. Cascades to line items.

        Raises ValidationError if the CO is not in draft status.
        """
        try:
            co = ChangeOrder.objects.get(pk=pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {pk} not found')

        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError(
                'Only draft change orders can be discarded.'
            )
        co.delete()

    # ------------------------------------------------------------------
    # Line-item operations (mirror EstimateService pattern)
    # ------------------------------------------------------------------

    @staticmethod
    def add_line_item(co_pk, **kwargs):
        """Add a manual line item to a draft change order."""
        try:
            co = ChangeOrder.objects.get(pk=co_pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {co_pk} not found')
        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft change orders.')
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(ChangeOrderLineItem, kwargs)
        li = ChangeOrderLineItem(change_order=co, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(co_pk, pli_pk, qty):
        """Add a line item from a InventoryItem to a draft change order."""
        from apps.inventory.models import InventoryItem
        try:
            co = ChangeOrder.objects.get(pk=co_pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {co_pk} not found')
        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft change orders.')
        try:
            pli = InventoryItem.objects.get(pk=pli_pk)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {pli_pk} not found')

        li = ChangeOrderLineItem.objects.create(
            change_order=co,
            action=ChangeOrderLineItem.ACTION_ADD,
            price_list_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            accounting_category=pli.accounting_category,
        )
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update a change order line item — validates draft status."""
        try:
            li = ChangeOrderLineItem.objects.get(pk=line_item_id)
        except ChangeOrderLineItem.DoesNotExist:
            raise NotFoundError(f'ChangeOrderLineItem {line_item_id} not found')
        if li.change_order.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Can only modify line items on draft change orders.')
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(ChangeOrderLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(co_pk, item_ids):
        """Reorder change order line items by position list — validates draft status."""
        try:
            co = ChangeOrder.objects.get(pk=co_pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {co_pk} not found')
        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Can only modify line items on draft change orders.')
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                ChangeOrderLineItem.objects.filter(
                    pk=item_id, change_order=co,
                ).update(line_number=position)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete a change order line item and renumber — validates draft status."""
        from apps.core.services import LineItemService
        try:
            li = ChangeOrderLineItem.objects.get(pk=line_item_id)
        except ChangeOrderLineItem.DoesNotExist:
            raise NotFoundError(f'ChangeOrderLineItem {line_item_id} not found')
        if li.change_order.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Cannot modify line items on a non-draft change order.')
        return LineItemService.delete_line_item_with_renumber(li)
