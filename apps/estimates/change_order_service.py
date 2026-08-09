"""
Service class for ChangeOrder lifecycle operations.

Rules:
- A CO can only be created while the job is held (on_hold flag).
- Accepting a CO clears the hold — the job resumes its true underlying
  status (approved stays approved; in_progress resumes directly) — then
  crystallizes the CO's line deltas onto the Job's atoms
  (ChangeOrderAcceptanceService.on_accept — the CO parallel of
  EstimateAcceptanceService).
- Rejecting/expiring a CO snapshots the proposal and leaves the job held.
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
        - job must be held (on_hold flag).
        - job must have an accepted estimate.

        Trigger 1: snapshot the prior agreement onto the latest accepted CO
        for that estimate (if one exists) or the accepted estimate itself.
        snapshot_document is idempotent, so repeat calls are safe.
        """
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_id} not found')

        if not job.on_hold:
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
    def assert_all_bare_add_lines_have_ac(co):
        """A bare add line (no service/inventory descriptor) needs an
        accounting category to travel on documents — the category rides the
        line onto the agreement and its invoice copy, so a category-less line
        would surface as an unclassifiable charge downstream. Catch it at
        send, before the customer has said yes. The CO parallel of
        EstimateService.assert_all_hand_lines_have_ac; shared by
        ChangeOrder.clean()'s draft-exit guard (the invariant home) and
        ChangeOrderEmailService._validate_send (the pre-email copy, so the
        refusal lands before the customer is mailed a dead draft link)."""
        from apps.estimates.models import ChangeOrderLineItem
        missing = [
            li.description or f'line {li.line_number}'
            for li in ChangeOrderLineItem.objects.filter(
                change_order=co,
                action=ChangeOrderLineItem.ACTION_ADD,
                service_item__isnull=True,
                inventory_item__isnull=True,
                accounting_category__isnull=True,
            )
        ]
        if missing:
            raise ValidationError(
                'Cannot send: every added line item needs an '
                'accounting category first. Missing on: '
                + ', '.join(missing) + '.'
            )

    @staticmethod
    def has_sendable_changes(co):
        """The send / mark-open content gate: a CO is sendable when it carries
        line-item changes OR a deliverables diff against its baseline. A
        deliverables-only CO (spec/quantity correction, no price impact) is a
        legitimate send — the customer signs off on the scope change (RM
        decision 2026-07-20). Only a CO empty on BOTH halves is refused —
        shared by ChangeOrderEmailService._validate_send (pre-email check)
        and ChangeOrder.clean()'s draft-exit guard (the invariant home)."""
        if co.changeorderlineitem_set.exists():
            return True
        return any(r['kind'] != 'unchanged'
                   for r in ChangeOrderService.compose_deliverable_diff(co))

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

        - Accepted: clear the job's hold (status preserved); write system
          HistoryEntry; crystallize the CO's deltas onto the Job's atoms
          (typed add → new Task/Material, plain add stays document-only;
          remove/replace → retire the target's atom, with the replacement
          crystallized from the CO line).
        - Rejected / Expired: snapshot the proposal (Trigger 2); leave the
          job held.
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
        """Clear the job's hold (its true status is preserved — a job held
        from in_progress resumes work directly), write a system-attributed
        HistoryEntry, then crystallize the CO's deltas onto the Job's atoms.

        Crystallization runs after the un-hold because atom mutations are
        blocked while the job is held; update_status's transaction wraps
        both, so a failed crystallization rolls the acceptance back whole.
        """
        from apps.core.models import User
        from apps.estimates.co_acceptance import ChangeOrderAcceptanceService

        job = co.job
        job.refresh_from_db()

        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )

        if job.on_hold:
            job.on_hold = False
            job.save()  # save() clears hold_reason when the flag drops
            record_history(
                entry_type='action',
                object_type='changeorder',
                object_id=co.pk,
                user=system_user,
                changes={
                    'on_hold': {'old': True, 'new': False},
                    '_action': 'Change order accepted',
                },
            )

        ChangeOrderAcceptanceService.on_accept(co)

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
        deltas for the shop to revise. The job stays held (the CO editing
        room); the release guard keeps it parked until the new draft is
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
                inventory_item=li.inventory_item,
                service_item=li.service_item,
                is_material=li.is_material,
                accounting_category=li.accounting_category,
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
    def _assert_target_not_billed(target_line_item):
        """Block remove/replace against an agreement (estimate) line that a
        live (non-cancelled) invoice line already references — amending or
        removing the CO's target out from under an invoice that already
        billed it would silently desync the two documents. Mirrors the
        "live" definition InvoiceService.remaining_agreement_lines /
        _assert_agreement_line_unclaimed use (every invoice status except
        cancelled — see LIVE_INVOICE_STATUSES in apps/invoicing/services.py)."""
        from apps.invoicing.models import Invoice, InvoiceLineItem
        ref = (InvoiceLineItem.objects
               .filter(agreement_estimate_line=target_line_item)
               .exclude(invoice__status=Invoice.STATUS_CANCELLED)
               .select_related('invoice')
               .first())
        if ref is not None:
            raise ValidationError({'target_line_item': [
                f'Billed on {ref.invoice.display_number} — remove it from '
                f'that invoice before amending this line.']})

    @staticmethod
    def _assert_is_material_only_on_bare_line(li):
        """`is_material` is meaningful only on a bare line — a line with an
        inventory_item or service_item already knows its crystallization type.
        Mirrors EstimateService._assert_is_material_only_on_bare_line."""
        if not li.is_material:
            return
        if li.inventory_item_id is not None:
            raise ValidationError({'is_material': (
                'A line with an inventory item is already a material; '
                'the "is material" marker only applies to a bare line.'
            )})
        if li.service_item_id is not None:
            raise ValidationError({'is_material': (
                'A service line cannot be marked as a material.'
            )})

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
        from apps.estimates.services import EstimateService
        kwargs = LineItemService.normalize_fk_kwargs(ChangeOrderLineItem, kwargs)
        li = ChangeOrderLineItem(change_order=co, **kwargs)
        # Material lines (is_material=True) get their AC from config if not
        # supplied — same default the estimate side applies at authoring.
        EstimateService._apply_material_ac_default(li)
        ChangeOrderService._assert_is_material_only_on_bare_line(li)
        li.full_clean()
        if (li.action in (ChangeOrderLineItem.ACTION_REMOVE, ChangeOrderLineItem.ACTION_REPLACE)
                and li.target_line_item_id):
            ChangeOrderService._assert_target_not_billed(li.target_line_item)
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
            inventory_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            accounting_category=pli.accounting_category,
        )
        return li

    @staticmethod
    def update_fields(co, **fields):
        """Non-status field updates on a change order (status changes go
        through update_status). No extra guards today — this exists so the
        view owns no persistence and a future guard has one home."""
        for k, v in fields.items():
            setattr(co, k, v)
        co.save()
        return co

    @staticmethod
    def add_line_item_from_service(co_pk, service_item_pk, qty):
        """Add a deferred service line to a draft change order.

        Mirrors EstimateService.add_line_item_from_service: snapshots the priced
        values off the ServiceItem at instantiation and keeps `service_item` on
        the line purely as the crystallization target. Mints NO Task — the Task
        is created at CO acceptance (ChangeOrderAcceptanceService.on_accept)."""
        from apps.estimates.models import ServiceItem
        try:
            co = ChangeOrder.objects.get(pk=co_pk)
        except ChangeOrder.DoesNotExist:
            raise NotFoundError(f'ChangeOrder {co_pk} not found')
        if co.status != ChangeOrder.STATUS_DRAFT:
            raise ValidationError('Can only add line items to draft change orders.')
        try:
            service_item = ServiceItem.objects.get(pk=service_item_pk)
        except ServiceItem.DoesNotExist:
            raise NotFoundError(f'ServiceItem {service_item_pk} not found')
        from apps.estimates.services import _decimal_or_invalid
        scheme = service_item.rate_scheme
        li = ChangeOrderLineItem(
            change_order=co,
            action=ChangeOrderLineItem.ACTION_ADD,
            service_item=service_item,
            description=service_item.template_name,
            # str() first: a raw JSON float would expand to its binary value
            # and trip the 2-decimal-places validator.
            qty=_decimal_or_invalid(qty, 'qty'),
            units=scheme.unit_label or 'none',
            price=scheme.effective_rate(service_item.default_active_modifiers),
            accounting_category=service_item.effective_accounting_category,
        )
        li.full_clean()
        li.save()
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
        from apps.estimates.services import EstimateService
        kwargs = LineItemService.normalize_fk_kwargs(ChangeOrderLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        EstimateService._apply_material_ac_default(li)
        ChangeOrderService._assert_is_material_only_on_bare_line(li)
        li.full_clean()
        if (li.action in (ChangeOrderLineItem.ACTION_REMOVE, ChangeOrderLineItem.ACTION_REPLACE)
                and li.target_line_item_id):
            ChangeOrderService._assert_target_not_billed(li.target_line_item)
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
