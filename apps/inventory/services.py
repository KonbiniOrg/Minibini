from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum
from apps.inventory.models import Earmark, Material
from apps.inventory.models import InventoryItem


class InventoryService:
    """Service for inventory operations: InventoryItem CRUD, QOH updates, and earmarks."""

    # --- InventoryItem CRUD ---

    @staticmethod
    def _default_markup_percent():
        """Config-driven default material markup, as a Decimal percent.
        Unset/invalid → 0 (selling price defaults to cost)."""
        from decimal import InvalidOperation
        from apps.core.models import Configuration
        try:
            raw = Configuration.objects.get(
                key='default_material_markup_percent').value
        except Configuration.DoesNotExist:
            return Decimal('0')
        try:
            return Decimal(raw)
        except (InvalidOperation, TypeError):
            return Decimal('0')

    @staticmethod
    def create_item(**kwargs):
        """Create a new InventoryItem.

        When no explicit (non-zero) selling_price is given, derive it from
        purchase_price × the config markup, snapshotted at creation. update_item
        never re-applies this — the stored value is authoritative thereafter.
        """
        from apps.core.services import NotFoundError
        pli = InventoryItem(**kwargs)
        if not kwargs.get('selling_price') and kwargs.get('purchase_price'):
            markup = InventoryService._default_markup_percent()
            pli.selling_price = (
                pli.purchase_price * (Decimal('1') + markup / Decimal('100'))
            ).quantize(Decimal('0.01'))
        pli.full_clean()
        pli.save()
        return pli

    @staticmethod
    def update_item(pk, **kwargs):
        """Update an existing InventoryItem by PK."""
        from apps.core.services import NotFoundError
        try:
            pli = InventoryItem.objects.get(pk=pk)
        except InventoryItem.DoesNotExist:
            raise NotFoundError(f'InventoryItem {pk} not found')
        for field, value in kwargs.items():
            setattr(pli, field, value)
        pli.full_clean()
        pli.save()
        # A demoted catalog item that is empty becomes a finished lot — kept as
        # shop history, hidden by the hide-on-spend list filter. (The old
        # collect_if_finished auto-delete was retired by the deletion doctrine:
        # inventory rows are never auto-deleted.)
        return pli

    @staticmethod
    def assert_item_deletable(item):
        """Hard delete is mistake correction: never-referenced rows only.

        Estimate/invoice/PO/bill line items PROTECT at the DB level
        (can_be_deleted); Materials and Expense stock receipts are SET_NULL, so
        without this guard deleting an item would silently demote established
        materials to provisional and orphan stock-receipt records. A referenced
        item retires by deactivation (is_active) or lives on as a hidden
        finished lot instead.
        """
        from django.core.exceptions import ValidationError
        from apps.expenses.models import Expense
        if not item.can_be_deleted:
            raise ValidationError(
                'This item is referenced by document line items and cannot be '
                'deleted. Deactivate it instead.'
            )
        if Material.objects.filter(inventory_item=item).exists():
            raise ValidationError(
                'This item backs job materials and cannot be deleted. '
                'Deactivate it instead.'
            )
        if Earmark.objects.filter(inventory_item=item).exists():
            raise ValidationError(
                'This item has earmarked stock and cannot be deleted.'
            )
        if Expense.objects.filter(stock_pli=item).exists():
            raise ValidationError(
                'This item has expense stock receipts and cannot be deleted. '
                'Deactivate it instead.'
            )

    # --- Inventory history (durable audit trail) ---

    @staticmethod
    def _record_qoh_history(item, quantity_change, *, action, reason='',
                            user=None, job=None, document=''):
        """Append a durable inventory-history 'action' entry for a QOH event.

        Snapshots code/description so the entry stays legible after the item is
        hidden or deleted. Call AFTER the QOH change is saved + refreshed.
        Replaces the retired InventoryAdjustment audit object.
        """
        from apps.core.history import record_history
        job_ref = None
        if job is not None:
            job_ref = getattr(job, 'job_number', None) or getattr(job, 'pk', None)
        record_history(
            'inventoryitem', entry_type='action', object_id=item.pk, user=user,
            changes={
                '_action': action,
                'qty_change': str(Decimal(quantity_change).quantize(Decimal('0.01'))),
                'qty_on_hand': str(item.qty_on_hand),
                'code': item.code,
                'description': item.description,
                'job': job_ref,
                'document': document or None,
            },
            text=reason,
        )

    MERGE_OVERRIDE_FIELDS = (
        'code', 'description', 'units', 'purchase_price', 'selling_price',
        'is_catalog',
    )

    @staticmethod
    def merge(keep_id, discard_id, *, user=None, overrides=None):
        """Consolidate two inventory items into one (the manual dedup tool).

        Moves the discard's on-hand onto keep, repoints EVERY reference
        (earmarks — sum-collapsed on the (item, job) unique constraint —
        materials, plan materials, all four line-item tables, template-material
        associations, and expense stock links), folds the quantity aggregates,
        applies the caller's retained-field choices to keep, then deletes the
        now-reference-free discard. `overrides` is a dict of final values for
        keep (the frontend resolves which side's value to keep).

        Hard-blocks on a unit mismatch (the QOH addition would be nonsense) and
        refuses to discard a catalog item (demote it first)."""
        from django.core.exceptions import ValidationError
        from apps.estimates.models import EstimateLineItem
        from apps.invoicing.models import InvoiceLineItem
        from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem
        from apps.inventory.models import TemplateMaterialAssociation
        from apps.expenses.models import Expense
        from apps.core.history import record_history

        overrides = overrides or {}
        if keep_id == discard_id:
            raise ValidationError('Cannot merge an item into itself.')
        keep = InventoryItem.objects.get(pk=keep_id)
        discard = InventoryItem.objects.get(pk=discard_id)
        if discard.is_catalog:
            raise ValidationError(
                'Cannot discard a catalog item; uncheck its catalog flag to '
                'demote it to a lot first, then merge.')
        if keep.units != discard.units:
            raise ValidationError(
                f'Unit mismatch: cannot merge {discard.units!r} into '
                f'{keep.units!r}.')

        moved = discard.qty_on_hand
        discard_code = discard.code
        discard_desc = discard.description
        with transaction.atomic():
            # Earmarks: sum-collapse on the (item, job) unique constraint.
            for em in Earmark.objects.filter(inventory_item=discard):
                existing = Earmark.objects.filter(
                    inventory_item=keep, job=em.job).first()
                if existing:
                    existing.quantity += em.quantity
                    existing.save(update_fields=['quantity'])
                    em.delete()
                else:
                    em.inventory_item = keep
                    em.save(update_fields=['inventory_item'])
            # Repoint every remaining reference (pure FK swaps).
            Material.objects.filter(inventory_item=discard).update(inventory_item=keep)
            EstimateLineItem.objects.filter(inventory_item=discard).update(inventory_item=keep)
            InvoiceLineItem.objects.filter(inventory_item=discard).update(inventory_item=keep)
            PurchaseOrderLineItem.objects.filter(inventory_item=discard).update(inventory_item=keep)
            BillLineItem.objects.filter(inventory_item=discard).update(inventory_item=keep)
            TemplateMaterialAssociation.objects.filter(inventory_item=discard).update(inventory_item=keep)
            Expense.objects.filter(stock_pli=discard).update(stock_pli=keep)
            # Fold quantity aggregates.
            keep.qty_on_hand += discard.qty_on_hand
            keep.qty_sold += discard.qty_sold
            keep.qty_wasted += discard.qty_wasted
            # Record the discard's outgoing entry, then delete it — BEFORE
            # saving keep, so a retained `code` from discard won't collide on
            # the unique constraint while discard still holds it.
            record_history(
                'inventoryitem', entry_type='action', object_id=discard.pk,
                user=user,
                changes={
                    '_action': 'Merge (discarded)',
                    'qty_change': str((-moved).quantize(Decimal('0.01'))),
                    'qty_on_hand': '0.00',
                    'code': discard_code, 'description': discard_desc,
                    'merged_into': keep.code,
                },
                text=f'Merged into {keep.code}')
            discard.delete()
            # Apply retained-field choices, then save keep.
            for field in InventoryService.MERGE_OVERRIDE_FIELDS:
                if field in overrides:
                    setattr(keep, field, overrides[field])
            keep.full_clean()
            keep.save()
            keep.refresh_from_db()
            InventoryService._record_qoh_history(
                keep, moved, action='Merge (received)',
                reason=f'Merged from {discard_code}', user=user)
        return keep

    @staticmethod
    def write_off(item, qty=None, *, user=None, reason=''):
        """Write off some on-hand stock as wasted.

        `qty` is how much to waste (e.g. one damaged sheet); omit it to write off
        the whole on-hand balance. Decrements QOH and books `qty` to qty_wasted,
        recording the wastage history entry (via manual_adjustment) BEFORE any
        further state change so the wastage is never lost. If that empties the
        lot it becomes a finished lot (hidden, or collected if reference-free);
        a partial write-off just leaves a smaller balance. Catalog items survive
        at QOH 0 (just emptied)."""
        from decimal import InvalidOperation
        from django.core.exceptions import ValidationError
        remaining = item.qty_on_hand
        if remaining <= Decimal('0.00'):
            raise ValidationError('Nothing on hand to write off.')
        if qty is None or qty == '':
            qty = remaining
        else:
            try:
                qty = Decimal(str(qty))
            except (InvalidOperation, TypeError):
                raise ValidationError('Invalid write-off quantity.')
        if qty <= Decimal('0.00'):
            raise ValidationError('Write-off quantity must be positive.')
        if qty > remaining:
            raise ValidationError(
                f'Cannot write off {qty}; only {remaining} on hand.')
        InventoryService.manual_adjustment(
            item, -qty, reason=reason or 'Write-off', user=user,
        )
        # An emptied non-catalog lot becomes a finished lot — kept as shop
        # history, hidden by the hide-on-spend filter (never auto-deleted).
        item.refresh_from_db()
        return item

    # --- QOH operations ---

    @staticmethod
    def complete_task_adjustment(material, actual_qty):
        """Adjust inventory when task completes and actual quantity differs from estimated.
        If actual < estimated, return excess to stock.
        If actual > estimated, consume additional stock."""
        pli = material.inventory_item
        if not pli:
            return

        difference = actual_qty - material.quantity
        if difference == Decimal('0.00'):
            return

        # difference > 0 means more consumed (decrease QOH more)
        # difference < 0 means less consumed (increase QOH back)
        pli.qty_on_hand = F('qty_on_hand') - difference
        pli.qty_sold = F('qty_sold') + difference
        pli.save(update_fields=['qty_on_hand', 'qty_sold'])
        pli.refresh_from_db()

    @staticmethod
    def manual_adjustment(inventory_item, quantity_change, reason='', user=None):
        """Manually adjust QOH and record an audit-trail entry.
        Negative adjustments track as waste."""
        inventory_item.qty_on_hand = F('qty_on_hand') + quantity_change
        if quantity_change < Decimal('0.00'):
            inventory_item.qty_wasted = F('qty_wasted') - quantity_change
        inventory_item.save(update_fields=['qty_on_hand', 'qty_wasted'] if quantity_change < Decimal('0.00') else ['qty_on_hand'])
        inventory_item.refresh_from_db()

        InventoryService._record_qoh_history(
            inventory_item, quantity_change,
            action='Manual adjustment', reason=reason, user=user,
        )

    @staticmethod
    def receive_ad_hoc_purchase(material):
        """Increase QOH for an ad-hoc (job-level, no PO) purchase material.
        QOH-only — earmark was already created by MaterialService.create_on_job."""
        from django.db.models import F
        pli = material.inventory_item
        if not pli:
            return
        pli.qty_on_hand = F('qty_on_hand') + material.quantity
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        InventoryService._record_qoh_history(
            pli, material.quantity, action='Ad-hoc receive',
            reason=f'Ad-hoc receive on job {material.job.job_number}',
            job=material.job,
        )

    @staticmethod
    def reverse_ad_hoc_purchase(material):
        """Decrease QOH to reverse a previously received ad-hoc purchase.
        Reverses the full original purchase quantity (quantity + released_qty)."""
        from django.db.models import F
        pli = material.inventory_item
        if not pli:
            return
        total = material.quantity + material.released_qty
        pli.qty_on_hand = F('qty_on_hand') - total
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        InventoryService._record_qoh_history(
            pli, -total, action='Ad-hoc reverse',
            reason=f'Ad-hoc reverse on job {material.job.job_number}',
            job=material.job,
        )

    @staticmethod
    def receive_stock(pli, qty, *, reason='', user=None):
        """Increase QOH for a material-less stock receipt (an inventoried-PLI
        expense). No earmark, no Material — the job's consumable draws it down at
        consumption. Returns the delta applied (0 if not inventoried)."""
        from django.db.models import F
        if not pli or not qty or qty == Decimal('0.00'):
            return Decimal('0.00')
        pli.qty_on_hand = F('qty_on_hand') + qty
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        InventoryService._record_qoh_history(
            pli, qty, action='Stock receipt',
            reason=reason or 'Stock receipt (expense)', user=user,
        )
        return qty

    # --- Earmark operations ---

    @staticmethod
    def get_earmark_preview(job):
        """Get preview of inventoried items needed for a job's task materials.

        Aggregates by inventory_item across all Materials on all Tasks
        for this job. Returns list of dicts with inventory_item, needed_qty,
        available_qty, shortfall.
        """
        from apps.inventory.models import Material

        materials = Material.objects.filter(
            task__job=job,
            inventory_item__isnull=False,
        ).values('inventory_item').annotate(
            total_qty=Sum('quantity'),
        )

        preview = []
        for entry in materials:
            item = InventoryItem.objects.get(pk=entry['inventory_item'])
            needed = entry['total_qty']
            available = item.qty_available
            shortfall = max(needed - available, Decimal('0.00'))
            preview.append({
                'inventory_item': item,
                'needed_qty': needed,
                'available_qty': available,
                'shortfall': shortfall,
            })
        return preview

    @staticmethod
    def create_earmarks_for_job(job):
        """Create earmarks from a Job's materials (task-attached and task-less).

        Aggregates inventoried Materials by PLI across all Materials on the job
        (both task-attached and task-less), then upserts Earmark records for the
        job. Called as a hook after each job-population path (estimate,
        template, duplication).
        """
        from apps.inventory.models import Material

        # Exclude already-consumed materials: a material consumed pre-approval
        # already drew down QOH and needs no reservation — re-earmarking it here
        # would phantom-reserve stock that's already been used.
        materials = Material.objects.filter(
            job=job,
            inventory_item__isnull=False,
        ).exclude(
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        ).values('inventory_item').annotate(
            total_qty=Sum('quantity'),
        )

        if not materials:
            return

        earmark_data = [
            {
                'inventory_item_id': entry['inventory_item'],
                'quantity': entry['total_qty'],
            }
            for entry in materials
        ]
        InventoryService._upsert_earmarks(job, earmark_data)

    @staticmethod
    def _upsert_earmarks(job, earmark_data):
        """Create or update earmarks from user-confirmed data.
        earmark_data: list of dicts with inventory_item_id and quantity."""
        for entry in earmark_data:
            qty = entry['quantity']
            if qty <= Decimal('0.00'):
                continue
            item = InventoryItem.objects.get(pk=entry['inventory_item_id'])
            earmark, created = Earmark.objects.get_or_create(
                inventory_item=item,
                job=job,
                defaults={'quantity': qty},
            )
            if not created:
                earmark.quantity = qty
                earmark.save(update_fields=['quantity'])

    @staticmethod
    def _mutate_earmark(pli, job, delta):
        """Apply `delta` to the (pli, job) Earmark. Upsert if positive net, delete if zero.
        No-op if pli is None or not inventoried. Sole writer of Earmark rows."""
        if pli is None:
            return
        try:
            earmark = Earmark.objects.get(inventory_item=pli, job=job)
        except Earmark.DoesNotExist:
            if delta > Decimal('0.00'):
                Earmark.objects.create(inventory_item=pli, job=job, quantity=delta)
            return
        new_qty = earmark.quantity + delta
        if new_qty <= Decimal('0.00'):
            earmark.delete()
        else:
            earmark.quantity = new_qty
            earmark.save(update_fields=['quantity'])

    @staticmethod
    def release_earmarks_for_job(job):
        """Delete all remaining earmarks for a job.

        Called when a Job enters a terminal/closed state (work_complete,
        cancelled, or rejected) — any un-consumed earmark balance is released
        back to general inventory availability.
        """
        Earmark.objects.filter(job=job).delete()


class MaterialService:
    """Sole entry point for Material row creation and lifecycle ops.
    All earmark mutations go through InventoryService._mutate_earmark."""

    @staticmethod
    def _assert_not_invoiced(material):
        from django.core.exceptions import ValidationError
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        if InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_MATERIAL, material.pk,
        ):
            raise ValidationError(
                'Cannot change a material that is on an invoice; '
                'remove it from the invoice first.'
            )

    @staticmethod
    def update_pricing(material, *, unit_cost=None, sell_price=None, propagate_to_pli=False,
                       cost_source='manual'):
        """Update unit_cost and/or sell_price on a Material. If propagate_to_pli is
        True and the Material is PLI-linked, also update the PLI's purchase_price /
        selling_price to match — but only for fields that actually changed.

        `cost_source` records where a unit_cost change originates: 'manual' (a user
        typing a cost) or 'document' (an Expense/PO supplying it). Freeform (no-PLI)
        materials only accept a document-sourced cost — see Task A5 enforcement.

        No permission check: open to any authenticated user (deliberate carve-out
        from can_manage_financials per design).
        """
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(material.job, 'edit this material')
        if sell_price is not None and sell_price != material.sell_price:
            MaterialService._assert_not_invoiced(material)
        from django.db import transaction
        with transaction.atomic():
            update_fields = []
            cost_changed = False
            price_changed = False
            if unit_cost is not None and unit_cost != material.unit_cost:
                material.unit_cost = unit_cost
                update_fields.append('unit_cost')
                cost_changed = True
            if sell_price is not None and sell_price != material.sell_price:
                material.sell_price = sell_price
                update_fields.append('sell_price')
                price_changed = True
            if update_fields:
                material.save(update_fields=update_fields)

            if propagate_to_pli and material.inventory_item_id is not None:
                pli = material.inventory_item
                pli_fields = []
                if cost_changed and pli.purchase_price != material.unit_cost:
                    pli.purchase_price = material.unit_cost
                    pli_fields.append('purchase_price')
                if price_changed and pli.selling_price != material.sell_price:
                    pli.selling_price = material.sell_price
                    pli_fields.append('selling_price')
                if pli_fields:
                    pli.save(update_fields=pli_fields)
        return material

    @staticmethod
    def create_on_job(*, job, task=None, description='', quantity=Decimal('0.00'),
                      unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                      inventory_item=None, accounting_category=None, units='none',
                      cost_source='document'):
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(job, 'add a material to this job')
        # Freeform (no-PLI) actual materials get their cost from a document
        # (Expense/PO), never typed manually.
        if (cost_source == 'manual' and inventory_item is None
                and unit_cost and unit_cost != Decimal('0.00')):
            from django.core.exceptions import ValidationError
            raise ValidationError({
                'unit_cost': 'A freeform material’s cost comes from a linked '
                             'expense or PO, not manual entry.'
            })
        from django.db import transaction
        with transaction.atomic():
            m = Material(
                job=job, task=task,
                description=description, quantity=quantity,
                unit_cost=unit_cost, sell_price=sell_price,
                inventory_item=inventory_item,
                accounting_category=accounting_category,
                units=units,
            )
            m.save()  # full_clean() runs here; enforces task/job invariant
            # Only earmark immediately for committed (approved or later) jobs.
            # Pre-approval jobs (draft / submitted) do NOT reserve stock; their
            # materials are earmarked in bulk when the estimate is accepted via
            # EstimateAcceptanceService → InventoryService.create_earmarks_for_job.
            from apps.jobs.models import Job as _Job
            _PRE_APPROVAL = (_Job.STATUS_DRAFT, _Job.STATUS_SUBMITTED)
            if job.status not in _PRE_APPROVAL:
                InventoryService._mutate_earmark(inventory_item, job, quantity)
            # Attached to a task that already started? The promote-time
            # consumption sweep already ran — consume now (stock permitting).
            MaterialService.consume_if_task_started(m)
        return m

    @staticmethod
    def consume_if_task_started(material):
        """Consume a pending material whose task is already IN_PROGRESS.

        Consumption normally fires once, at the task's pending → in_progress
        promotion — a material attached *after* that missed the sweep and
        would stay pending (never billable) forever. Stock that physically
        isn't there (PLI with insufficient QOH) stays pending instead of
        raising: an in-flight procurement (add shortfall → order via PO) is a
        legitimate pending state and must not block the add."""
        from apps.jobs.models import Task
        task = material.task
        if task is None or task.status != Task.STATUS_IN_PROGRESS:
            return material
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            return material
        pli = material.inventory_item
        if pli is not None and material.quantity > Decimal('0.00'):
            pli.refresh_from_db()
            if pli.qty_on_hand < material.quantity:
                return material
        return MaterialService.consume(material)

    @staticmethod
    def consume(material):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError(
                f'consume requires pending state; got {material.consumption_state}'
            )
        qty = material.quantity
        with transaction.atomic():
            pli = material.inventory_item
            if pli and qty > Decimal('0.00'):
                pli.refresh_from_db()
                if pli.qty_on_hand < qty:
                    raise ValidationError(
                        f'Cannot consume {qty} {pli.units} of {pli.code}: '
                        f'only {pli.qty_on_hand} on hand. To start now, reduce '
                        f'this material to {pli.qty_on_hand} and add a second '
                        f'task/material for the remainder while it is procured.'
                    )
                from django.db.models import F
                pli.qty_on_hand = F('qty_on_hand') - qty
                pli.qty_sold = F('qty_sold') + qty
                pli.save(update_fields=['qty_on_hand', 'qty_sold'])
                pli.refresh_from_db()
                InventoryService._mutate_earmark(pli, material.job, -qty)
            material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
            material.save(update_fields=['consumption_state'])
        return material

    @staticmethod
    def unconsume(material):
        """Inverse of consume: return a CONSUMED material to PENDING and restore
        inventory (qty_on_hand, qty_sold, earmark). Used by the blep-cancel undo
        path when an oops-Start that consumed materials is reverted. Keeps a
        later re-Start safe, since consume() requires PENDING state."""
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_CONSUMED:
            raise ValidationError(
                f'unconsume requires consumed state; got {material.consumption_state}'
            )
        MaterialService._assert_not_invoiced(material)
        qty = material.quantity
        from apps.jobs.models import Job as _Job
        _PRE_APPROVAL = (_Job.STATUS_DRAFT, _Job.STATUS_SUBMITTED)
        with transaction.atomic():
            pli = material.inventory_item
            if pli and qty > Decimal('0.00'):
                from django.db.models import F
                pli.qty_on_hand = F('qty_on_hand') + qty
                pli.qty_sold = F('qty_sold') - qty
                pli.save(update_fields=['qty_on_hand', 'qty_sold'])
                pli.refresh_from_db()
                # Mirror consume's earmark no-op on pre-approval jobs: they carry
                # no earmarks (consume removed none), so unconsume restores none —
                # keeping the "no reservations until approval" invariant intact.
                if material.job.status not in _PRE_APPROVAL:
                    InventoryService._mutate_earmark(pli, material.job, qty)
            material.consumption_state = Material.CONSUMPTION_STATE_PENDING
            material.save(update_fields=['consumption_state'])
        return material

    @staticmethod
    def _is_referenced(material, *, ignore_po_link=False):
        """True when anything references this material — an expense, a PO line,
        or a document claim in any lens. Referenced materials are *released*
        (a named retirement that keeps the row as job history), never deleted;
        an unreferenced material is scratch paper and may be deleted (Rule 1 of
        the deletion doctrine). ignore_po_link supports the PO-sever path,
        where the PO link itself is what's being dissolved."""
        from apps.estimates.claims import atom_is_claimed
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        if material.is_expense_bound:
            return True
        if not ignore_po_link and material.po_line_item_id is not None:
            return True
        if atom_is_claimed('material', material.pk):
            return True
        return InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_MATERIAL, material.pk)

    @staticmethod
    def release(material):
        """pending → released: the named "planned it, didn't use it" retirement.

        Backs out the earmark and moves the remaining quantity into
        released_qty (conservation: quantity + released_qty = originally
        planned), so a released row sums to zero in every aggregate consumer.
        Claims are NOT purged — the row keeps supporting its estimate/CO/invoice
        lines as history. Terminal: every other lifecycle op requires pending.
        """
        from django.core.exceptions import ValidationError
        from django.db import transaction
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError(
                f'release requires pending state; got {material.consumption_state}'
            )
        with transaction.atomic():
            InventoryService._mutate_earmark(
                material.inventory_item, material.job, -material.quantity)
            material.released_qty = material.released_qty + material.quantity
            material.quantity = Decimal('0.00')
            material.consumption_state = Material.CONSUMPTION_STATE_RELEASED
            material.save(
                update_fields=['quantity', 'released_qty', 'consumption_state'])
        return material

    @staticmethod
    def restock(material, qty, *, ignore_po_link=False):
        """Return `qty` of a pending material to the shelf.

        Always tracks the return in released_qty. At quantity zero the
        restock-to-zero rule applies: a referenced material becomes `released`
        (job history — claims, expense/PO links, and the released_qty record
        survive); an unreferenced one is deleted (scratch paper).
        """
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if qty <= Decimal('0.00') or qty > material.quantity:
            raise ValidationError('restock qty must be > 0 and <= quantity')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('restock requires pending state')
        with transaction.atomic():
            InventoryService._mutate_earmark(material.inventory_item, material.job, -qty)
            material.quantity = material.quantity - qty
            material.released_qty = material.released_qty + qty
            if material.quantity == Decimal('0.00'):
                if MaterialService._is_referenced(
                        material, ignore_po_link=ignore_po_link):
                    material.consumption_state = Material.CONSUMPTION_STATE_RELEASED
                    material.save(update_fields=[
                        'quantity', 'released_qty', 'consumption_state'])
                else:
                    material.delete()
            else:
                material.save(update_fields=['quantity', 'released_qty'])
        return material

    @staticmethod
    def draw_more(material, qty):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if qty <= Decimal('0.00'):
            raise ValidationError('draw_more qty must be > 0')
        if material.is_expense_bound:
            raise ValidationError('draw_more not allowed on expense-bound materials')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('draw_more requires pending state')
        with transaction.atomic():
            material.quantity = material.quantity + qty
            material.save(update_fields=['quantity'])
            InventoryService._mutate_earmark(material.inventory_item, material.job, qty)
        return material

    @staticmethod
    def assign_task(material, task):
        """Move a material to a different task (or make it taskless with task=None)."""
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('assign_task requires pending state')
        if task is not None:
            if task.job_id != material.job_id:
                raise ValidationError('Task must belong to the same job as the material')
            if task.status in ('complete', 'cancelled'):
                raise ValidationError('Cannot assign material to a completed or cancelled task')
        material.task = task
        material.save(update_fields=['task_id'])
        # Moved onto a task that already started? The promote-time
        # consumption sweep already ran — consume now (stock permitting).
        MaterialService.consume_if_task_started(material)

    @staticmethod
    def link_to_po_line(material, po_line):
        """Set material.po_line_item = po_line. Validates pending + unlinked invariants."""
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot link; Material is not pending.')
        if material.po_line_item_id is not None and material.po_line_item_id != po_line.pk:
            raise ValidationError('Material is already linked to a different PO line.')
        material.po_line_item = po_line
        material.save(update_fields=['po_line_item'])

    @staticmethod
    def unlink_from_po_line(material):
        """Clear material.po_line_item. Validates pending state."""
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot unlink; Material is not pending.')
        material.po_line_item = None
        material.save(update_fields=['po_line_item'])

    @staticmethod
    def sever(material, decision):
        """'keep' clears the PO-line FK. 'delete' retires the Material: released
        if anything else still references it (claims, expenses — job history),
        hard-deleted otherwise (scratch paper). Backs out the earmark either
        way. Raises if decision is invalid or Material is consumed."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        if decision not in ('keep', 'delete'):
            raise ValidationError(f'Unknown sever decision: {decision!r}')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot sever; Material is not pending.')
        if decision == 'keep':
            MaterialService.unlink_from_po_line(material)
            return
        with transaction.atomic():
            MaterialService.unlink_from_po_line(material)
            if MaterialService._is_referenced(material):
                MaterialService.release(material)
            else:
                InventoryService._mutate_earmark(
                    material.inventory_item, material.job, -material.quantity,
                )
                material.delete()

    @staticmethod
    def resolve_or_create_for_line(po_line, *, job=None, inventory_item=None,
                                    qty, unit_cost, description,
                                    accounting_category=None, material_id=None):
        """Resolver precedence: explicit (material_id) -> claim exactly-one -> create new.

        Returns the linked Material. Raises ValidationError on explicit-link failures.

        Job arg semantics:
          - If material_id is given, job may be None — the Material's job is used.
            If both are given, they must match.
          - If material_id is None, job must be supplied (used for claim/create).

        Note: on explicit and claim paths, the existing Material's qty/unit_cost/
        description are NOT updated from the PO line. The Material is the source
        of truth for planned consumption; only the link is established.
        """
        from django.core.exceptions import ValidationError
        from django.db import transaction

        with transaction.atomic():
            # Step 1: explicit link
            if material_id is not None:
                try:
                    mat = Material.objects.select_for_update().get(pk=material_id)
                except Material.DoesNotExist:
                    raise ValidationError(f'Material {material_id} not found')
                if job is not None and mat.job_id != job.pk:
                    raise ValidationError('Material is not on the requested job')
                MaterialService.link_to_po_line(mat, po_line)
                return mat

            # Step 2 and 3 require a job
            if job is None:
                raise ValidationError('job is required when material_id is not provided')

            # Step 2: claim exactly-one unlinked pending match
            if inventory_item is not None:
                candidates = Material.objects.select_for_update().filter(
                    job=job,
                    inventory_item=inventory_item,
                    consumption_state=Material.CONSUMPTION_STATE_PENDING,
                    po_line_item__isnull=True,
                )
                matches = list(candidates[:2])
                if len(matches) == 1:
                    MaterialService.link_to_po_line(matches[0], po_line)
                    return matches[0]

            # Step 3: create new
            mat = MaterialService.create_on_job(
                job=job,
                inventory_item=inventory_item,
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                accounting_category=accounting_category,
            )
            MaterialService.link_to_po_line(mat, po_line)
            return mat
