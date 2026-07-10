from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum
from apps.inventory.models import Earmark, Material
from apps.inventory.models import InventoryItem, TemplateMaterialAssociation


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
        # Inventory rows are never auto-deleted — an empty item is kept as shop
        # history and retired manually via is_active.
        return pli

    @staticmethod
    def assert_item_deletable(item):
        """Hard delete is mistake correction: never-referenced rows only.

        Estimate/invoice/PO/bill line items PROTECT at the DB level
        (can_be_deleted); Materials and Expense stock receipts are SET_NULL, so
        without this guard deleting an item would silently demote established
        materials to provisional and orphan stock-receipt records. A referenced
        item retires by deactivation (is_active) instead.
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
    )

    @staticmethod
    def merge(keep_id, discard_id, *, overrides=None):
        """Consolidate two inventory items into one (the manual dedup tool).

        Moves the discard's on-hand onto keep, repoints EVERY reference
        (earmarks — sum-collapsed on the (item, job) unique constraint —
        materials, plan materials, all four line-item tables, template-material
        associations, and expense stock links), folds the quantity aggregates,
        applies the caller's retained-field choices to keep, then deletes the
        now-reference-free discard. `overrides` is a dict of final values for
        keep (the frontend resolves which side's value to keep).

        Hard-blocks on a unit mismatch (the QOH addition would be nonsense).
        Accepts any discard item — the catalog discard-guard is retired; an
        explicit confirm lives in the UI."""
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
        # 'none' means *unknown*, not a real unit — merging across it is fine
        # and the known unit wins. A real-unit mismatch (sheets vs lbs) still
        # blocks: the QOH addition would be nonsense.
        if keep.units != discard.units:
            if 'none' not in (keep.units, discard.units):
                raise ValidationError(
                    f'Unit mismatch: cannot merge {discard.units!r} into '
                    f'{keep.units!r}.')
            if keep.units == 'none' and 'units' not in overrides:
                overrides = {**overrides, 'units': discard.units}

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
                reason=f'Merged from {discard_code}')
        return keep

    @staticmethod
    def write_off(item, qty=None, *, reason=''):
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
            item, -qty, reason=reason or 'Write-off',
        )
        # An emptied non-catalog lot becomes a finished lot — kept as shop
        # history, hidden by the hide-on-spend filter (never auto-deleted).
        item.refresh_from_db()
        return item

    @staticmethod
    def order_stock(item, quantity, po=None):
        """Order an inventory item to stock: a plain PO line with no material
        link and no job — legit to buy just to have the inventory. Receipt
        lands in QOH via the normal PO receiving path. Mirrors
        MaterialService.order's draft-append-or-create contract."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        if quantity is None or quantity <= 0:
            raise ValidationError({'quantity': ['Quantity must be greater than 0.']})
        if po is not None and po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError('Can only add lines to a draft purchase order.')
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po()
            li = PurchaseOrderService.add_line_item_from_pli(
                po.pk, item.pk, quantity)
        return po, li

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
    def manual_adjustment(inventory_item, quantity_change, reason=''):
        """Manually adjust QOH and record an audit-trail entry.
        Negative adjustments track as waste."""
        inventory_item.qty_on_hand = F('qty_on_hand') + quantity_change
        if quantity_change < Decimal('0.00'):
            inventory_item.qty_wasted = F('qty_wasted') - quantity_change
        inventory_item.save(update_fields=['qty_on_hand', 'qty_wasted'] if quantity_change < Decimal('0.00') else ['qty_on_hand'])
        inventory_item.refresh_from_db()

        InventoryService._record_qoh_history(
            inventory_item, quantity_change,
            action='Manual adjustment', reason=reason,
        )

    @staticmethod
    def receive_ad_hoc_purchase(material, qty=None):
        """Increase QOH for an ad-hoc (job-level, no PO) purchase material.
        QOH-only — earmark was already created by MaterialService.create_on_job.
        `qty` defaults to the material's full quantity; an attach receipt may
        top up only part of it (e.g. the remainder after a partial PO receipt)."""
        from django.db.models import F
        pli = material.inventory_item
        if not pli:
            return
        qty = qty if qty is not None else material.quantity
        pli.qty_on_hand = F('qty_on_hand') + qty
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        InventoryService._record_qoh_history(
            pli, qty, action='Ad-hoc receive',
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

        Pre-approval jobs (draft/submitted) never reserve stock — earmarks are
        generated at estimate/CO acceptance (which approves the job first) or
        immediately for materials landing on an already-committed job. The
        guard lives HERE, at the single bulk entry point, so every population
        path inherits the invariant (a template applied to a draft job was
        silently earmarking before this).
        """
        from apps.inventory.models import Material
        from apps.jobs.models import Job as _Job

        if job.status in (_Job.STATUS_DRAFT, _Job.STATUS_SUBMITTED):
            return

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
    def _earmark_if_committed(material):
        """Reserve stock only for committed (approved+) jobs — pre-approval
        jobs earmark in bulk at acceptance (create_earmarks_for_job)."""
        from apps.jobs.models import Job as _Job
        _PRE_APPROVAL = (_Job.STATUS_DRAFT, _Job.STATUS_SUBMITTED)
        if material.job.status not in _PRE_APPROVAL:
            InventoryService._mutate_earmark(
                material.inventory_item, material.job, material.quantity)

    @staticmethod
    def mint_lot(material, *, unit_cost, sell_price=None):
        """Create the InventoryItem lot backing a one-off established material.
        QOH 0; sell defaults from the markup config when not supplied."""
        if not sell_price or sell_price == Decimal('0.00'):
            markup = InventoryService._default_markup_percent()
            sell_price = (unit_cost * (Decimal('1') + markup / Decimal('100'))
                          ).quantize(Decimal('0.01'))
        return InventoryService.create_item(
            code=f'LOT-{material.pk}',
            description=material.description,
            units=material.units,
            purchase_price=unit_cost,
            selling_price=sell_price,
            qty_on_hand=Decimal('0.00'),
            accounting_category=material.accounting_category,
        )

    @staticmethod
    def establish(material, *, inventory_item=None, unit_cost=None,
                  sell_price=None, cost_source=None):
        """provisional → established: supplying the price mints/attaches the lot.
        A sell_price already on the material (estimate-locked) is never re-derived."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        cost_source = cost_source or Material.COST_SOURCE_ENTERED
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('establish requires pending state')
        if material.inventory_item_id is not None:
            raise ValidationError('Material is already established.')
        if inventory_item is None and unit_cost is None:
            raise ValidationError(
                {'unit_cost': ['Establishing without an inventory item requires a cost.']})
        with transaction.atomic():
            locked_sell = material.sell_price
            if inventory_item is None:
                lot = MaterialService.mint_lot(
                    material, unit_cost=unit_cost, sell_price=locked_sell or sell_price)
                material.inventory_item = lot
                material.unit_cost = unit_cost
                if not locked_sell:
                    material.sell_price = lot.selling_price
            else:
                material.inventory_item = inventory_item
                if unit_cost is not None:
                    material.unit_cost = unit_cost
                elif not material.unit_cost:
                    material.unit_cost = inventory_item.purchase_price
                if not locked_sell:
                    material.sell_price = (
                        sell_price if sell_price else inventory_item.selling_price)
            material.cost_source = cost_source
            material.save()
            MaterialService._earmark_if_committed(material)
            MaterialService.consume_if_task_started(material)
        return material

    @staticmethod
    def establish_reverse_markup(material):
        """Establish a document-crystallized bare material at acceptance.

        The accepted price is the locked sell; back out an implied placeholder
        cost = sell / (1 + default markup %) and mint a QOH-0 lot at that cost
        (cost_source='estimated'). The real cost arrives when a PO line
        supplies it (cost_source flips to 'po'), but the material is
        established from the start so work can consume against the
        (to-be-received) lot. Shared by estimate and CO acceptance so both
        documents crystallize bare material lines identically.
        """
        sell = material.sell_price or Decimal('0')
        markup = InventoryService._default_markup_percent()
        unit_cost = (
            sell / (Decimal('1') + markup / Decimal('100'))
        ).quantize(Decimal('0.01'))
        return MaterialService.establish(
            material, unit_cost=unit_cost,
            cost_source=Material.COST_SOURCE_ESTIMATED,
        )

    @staticmethod
    def update_pricing(material, *, unit_cost=None, sell_price=None, propagate_to_pli=False):
        """Update unit_cost and/or sell_price on a Material. If propagate_to_pli is
        True and the Material is PLI-linked, also update the PLI's purchase_price /
        selling_price to match — but only for fields that actually changed.

        Provenance (cost_source) is not set here — callers stamp it on the Material
        (establishment mints/attaches the lot; document flows own their own source).

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
                      cost_source=None, customer_supplied=False):
        from django.core.exceptions import ValidationError
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(job, 'add a material to this job')
        from django.db import transaction
        if customer_supplied and (
                inventory_item is not None
                or (unit_cost and unit_cost != Decimal('0.00'))
                or (sell_price and sell_price != Decimal('0.00'))):
            # sell_price included: a pre-set sell would ride establish()'s
            # locked-sell preservation and mint the lot at that price.
            raise ValidationError(
                'A customer-supplied material carries no pricing — it is the '
                'customer’s property, carried at zero.')
        # Priced at authoring with no item pick → born established (mint the lot).
        # Only user-entered pricing establishes here; document-sourced costs
        # (PO/expense) record the cost but establish through their own flows
        # (Tasks 7-9), so they must NOT auto-mint.
        mint = (
            inventory_item is None
            and unit_cost and unit_cost != Decimal('0.00')
            and cost_source in (None, Material.COST_SOURCE_ENTERED)
        )
        with transaction.atomic():
            m = Material(
                job=job, task=task,
                description=description, quantity=quantity,
                # In the mint branch establish() sets unit_cost; construct at 0
                # so _populate_from_pli / establish don't fight over it.
                unit_cost=(Decimal('0.00') if mint else unit_cost),
                sell_price=sell_price,
                inventory_item=inventory_item,
                accounting_category=accounting_category,
                units=units,
            )
            m.save()  # full_clean() runs here; enforces task/job invariant
            if customer_supplied:
                # Born established at a deliberate, locked $0 — the customer
                # owns the thing; we track arrival, never price it.
                return MaterialService.establish(
                    m, unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                    cost_source=Material.COST_SOURCE_CUSTOMER)
            if mint:
                # Priced at authoring with no item pick → born established.
                m = MaterialService.establish(
                    m, unit_cost=unit_cost, cost_source=cost_source)
            else:
                # Only earmark immediately for committed (approved or later)
                # jobs. Pre-approval jobs (draft / submitted) do NOT reserve
                # stock; their materials are earmarked in bulk when the estimate
                # is accepted via EstimateAcceptanceService →
                # InventoryService.create_earmarks_for_job.
                MaterialService._earmark_if_committed(m)
                if inventory_item is not None:
                    m.cost_source = cost_source or Material.COST_SOURCE_ENTERED
                    m.save(update_fields=['cost_source'])
                elif cost_source is not None:
                    # Freeform (lot-less) material carrying a known provenance
                    # (document cost, customer-supplied, or a duplicated one) —
                    # record it. A genuinely provisional add (cost_source None)
                    # stays NULL. No ENTERED default here: a lot-less material is
                    # never "entered" (that path mints above).
                    m.cost_source = cost_source
                    m.save(update_fields=['cost_source'])
                # Attached to a task that already started? The promote-time
                # consumption sweep already ran — consume now (stock permitting).
                MaterialService.consume_if_task_started(m)
        return m

    @staticmethod
    def update_fields(material, *, propagate_to_pli=False, **fields):
        """The single write entry point for a material PATCH.

        - Quantity moves are refused — draw_more/restock own them (with their
          earmark math); a bare quantity write would silently desync earmarks.
        - Pricing on a PLI-linked material routes through update_pricing
          (invoiced-freeze + optional PLI propagation); like the endpoints it
          replaces, that path applies pricing only.
        - A pricing write on a provisional (no-lot) material ESTABLISHES it —
          attaching the given item or minting a lot. A sell-only edit leaves it
          provisional.
        - Everything else — metadata — saves under the on_hold guard, with the
          invoiced freeze on any sell_price change.
        """
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.jobs.services import _assert_job_not_on_hold
        if {'quantity', 'released_qty'} & set(fields):
            raise ValidationError(
                'Quantity changes must use the draw-more or restock actions.')
        # Every mutation path below (establish, PLI pricing, metadata) edits the
        # material, so the on-hold guard applies uniformly up front.
        _assert_job_not_on_hold(material.job, 'edit this material')
        # Locked before either pricing route below (the provisional-establish
        # branch and the PLI-backed pricing carve-out) can be reached: a
        # customer-supplied material is the customer's property, carried at a
        # deliberate, locked $0 — never priced.
        if material.is_customer_supplied and (
                'unit_cost' in fields or 'sell_price' in fields):
            raise ValidationError(
                'A customer-supplied material is not priced — it is the '
                'customer’s property, carried at zero.')
        # One PATCH = one transaction: a raise after the establish route (e.g.
        # the descriptive-fields refusal below) must roll the mint/earmark back,
        # never leave a half-applied establish behind an error response.
        with transaction.atomic():
            if material.inventory_item_id is None:
                inv = fields.pop('inventory_item', None)
                uc = fields.pop('unit_cost', None)
                sp = fields.pop('sell_price', None)
                if inv is not None or (uc and uc != Decimal('0.00')):
                    MaterialService.establish(
                        material, inventory_item=inv, unit_cost=uc, sell_price=sp)
                    material.refresh_from_db()
                    if not fields:
                        return material
                elif sp is not None:
                    fields['sell_price'] = sp  # sell-only edit stays provisional
            if material.inventory_item_id is not None:
                # PLI-backed rows take description/units/AC from the inventory
                # item and are locked (see materials doc: unit math depends on
                # the pairing); only the pricing carve-out is editable.
                non_pricing = set(fields) - {'unit_cost', 'sell_price'}
                if non_pricing:
                    raise ValidationError(
                        'A catalog-backed material takes its descriptive fields '
                        'from the inventory item, so they are immutable here; '
                        'only unit cost / sell price are editable. Rejected: '
                        + ', '.join(sorted(non_pricing)))
            if material.inventory_item_id is not None and (
                    'unit_cost' in fields or 'sell_price' in fields):
                MaterialService.update_pricing(
                    material,
                    unit_cost=fields.get('unit_cost'),
                    sell_price=fields.get('sell_price'),
                    propagate_to_pli=propagate_to_pli,
                )
                material.refresh_from_db()
                return material
            if 'sell_price' in fields and fields['sell_price'] != material.sell_price:
                MaterialService._assert_not_invoiced(material)
            for k, v in fields.items():
                setattr(material, k, v)
            material.save()
        return material

    @staticmethod
    def remove(material):
        """Doctrine-correct removal for the delete affordance.

        pending qty>0 → full restock (restock-to-zero rule applies:
        referenced → released, unreferenced → deleted); pending qty==0 →
        the same rule directly (release keeps claims resolving, delete is
        scratch-paper). consumed/released rows are actuals/history and are
        never hard-deleted — unconsume or leave them.
        Returns the surviving material, or None when the row was deleted.
        """
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError(
                'A consumed or released material is job history and cannot be '
                'deleted. Unconsume it first if the work never happened.')
        if material.quantity > Decimal('0.00'):
            return MaterialService.restock(material, material.quantity)
        if MaterialService._is_referenced(material):
            return MaterialService.release(material)
        material.delete()
        return None

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
        if pli is None:
            return material  # provisional: stays pending, never silently consumed
        if material.quantity > Decimal('0.00'):
            pli.refresh_from_db()
            if pli.qty_on_hand < material.quantity:
                return material
        return MaterialService.consume(material)

    @staticmethod
    def mark_on_hand(material, qty, *, user=None):
        """Deliberate no-document receipt (Path 3), and the customer-delivery
        receipt for customer-supplied materials (Path 4)."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from django.db.models import F
        if material.inventory_item_id is None:
            raise ValidationError('Set pricing on this material first.')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Only a pending material can be received.')
        if qty <= Decimal('0.00'):
            raise ValidationError({'quantity': ['Quantity must be positive.']})
        with transaction.atomic():
            pli = material.inventory_item
            pli.qty_on_hand = F('qty_on_hand') + qty
            pli.save(update_fields=['qty_on_hand'])
            pli.refresh_from_db()
            action = ('Customer delivery' if material.is_customer_supplied
                      else 'Marked on-hand')
            InventoryService._record_qoh_history(
                pli, qty, action=action,
                reason=f'{action} on job {material.job.job_number}',
                job=material.job, user=user)
        return material

    @staticmethod
    def consume(material):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError(
                f'consume requires pending state; got {material.consumption_state}'
            )
        if material.inventory_item_id is None:
            raise ValidationError(
                'This material is provisional — set its pricing and receive it '
                'before work can consume it.'
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
                        f'task/material for the remainder while it is procured. '
                        f'If it is on order or coming from the customer, wait '
                        f'for arrival.'
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

        Blocked while the job is on hold: restock is replanning (shrinking
        the job's material plan), not procurement — on-hold freezes the plan.
        Named system retirements (PO sever, CO descope, completion release)
        route through release() or run on jobs that can't be on hold.
        """
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(material.job, 'restock this material')
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
        if material.po_line_item_id is not None:
            # Same rule as expense-bound: the quantity is pinned by a
            # procurement document. Drawing more would pretend the PO line
            # covers units it never bought (and re-show a concluded PO as
            # this row's supply). One row ↔ one procurement story.
            raise ValidationError(
                'This material’s quantity is covered by its purchase order. '
                'Add a second material for the additional quantity and order '
                'that one.')
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
            from apps.jobs.models import Task
            if task.job_id != material.job_id:
                raise ValidationError('Task must belong to the same job as the material')
            if task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
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
    def order(material, po=None):
        """Path 1: start (or append to) a draft PO with a line linked to this
        material. Vendor-less create is fine — vendor is required at issue."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        if material.inventory_item_id is None:
            raise ValidationError('Set pricing on this material before ordering.')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Only a pending material can be ordered.')
        if material.is_customer_supplied:
            raise ValidationError(
                'A customer-supplied material is not ordered — the customer sends it.')
        if material.po_line_item_id is not None:
            raise ValidationError('Material is already on a purchase order.')
        if po is not None and po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError('Can only add lines to a draft purchase order.')
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po()
            li = PurchaseOrderService.add_line_item_from_pli(
                po.pk, material.inventory_item_id, material.quantity,
                job=material.job_id, material_id=material.pk)
        return po, li

    @staticmethod
    def _apply_po_line_cost(material, po_line, price):
        """Supply/override a PO-linked material's cost from the PO line price.

        - Provisional (lot-less) material → ESTABLISH it: mint a QOH-0 lot at
          `price`, stamp cost_source='po', and (when the PO line itself has no
          inventory_item) repoint the line at the minted lot so
          PurchaseOrderReceivingService.receive_items' `li.inventory_item.qty_on_hand
          += qty` bump lands on that lot. establish is the SOLE earmark writer
          here (it earmarks committed jobs; the provisional row had no lot, so
          no earmark existed — no double).
        - Established material → override unit_cost via update_pricing and stamp
          cost_source='po'. Sell price is NEVER touched, and no earmark is added.

        No-op when the line carries no usable price.
        """
        if price is None:
            return material
        if material.inventory_item_id is None:
            MaterialService.establish(
                material, unit_cost=price, cost_source=Material.COST_SOURCE_PO)
            if po_line.inventory_item_id is None:
                po_line.inventory_item = material.inventory_item
                po_line.save(update_fields=['inventory_item'])
        elif price != material.unit_cost:
            MaterialService.update_pricing(material, unit_cost=price)
            material.cost_source = Material.COST_SOURCE_PO
            material.save(update_fields=['cost_source'])
        return material

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
                # The PO write supplies/overrides the material's cost (a
                # hand-built PO line may name a provisional material).
                MaterialService._apply_po_line_cost(mat, po_line, unit_cost)
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
                    # Claimed match is inventoried (filtered on inventory_item),
                    # so it is established — override its cost from the PO line.
                    MaterialService._apply_po_line_cost(
                        matches[0], po_line, unit_cost)
                    return matches[0]

            # Step 3: create new. A PO line's cost is document-sourced, so
            # create_on_job records the cost with cost_source='po' but does NOT
            # auto-mint. We then establish through _apply_po_line_cost: a
            # catalog line's material is already lot-backed (no-op); a freeform
            # (pli-less) line's material is minted a LOT-{pk} lot at the line
            # price, and the PO line is repointed at it so receiving can bump
            # QOH — without this a freeform-PO material could never arrive and
            # consume() would refuse it forever.
            mat = MaterialService.create_on_job(
                job=job,
                inventory_item=inventory_item,
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                accounting_category=accounting_category,
                cost_source=Material.COST_SOURCE_PO,
            )
            MaterialService.link_to_po_line(mat, po_line)
            MaterialService._apply_po_line_cost(mat, po_line, unit_cost)
            return mat


class TemplateMaterialAssociationService:
    """Owns TemplateMaterialAssociation writes (the WorkTemplate materials
    tab) — views translate HTTP, this validates and persists."""

    @staticmethod
    def create(template, **fields):
        assoc = TemplateMaterialAssociation(work_template=template, **fields)
        assoc.full_clean()
        assoc.save()
        return assoc

    @staticmethod
    def update(assoc, **fields):
        for k, v in fields.items():
            setattr(assoc, k, v)
        assoc.full_clean()
        assoc.save()
        return assoc

    @staticmethod
    def delete(assoc):
        assoc.delete()
