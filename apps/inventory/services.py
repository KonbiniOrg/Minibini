from decimal import Decimal
from django.db.models import F, Sum
from apps.inventory.models import Earmark, Material, PlanMaterial
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
        return pli

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

    # --- QOH operations ---

    @staticmethod
    def complete_task_adjustment(material, actual_qty):
        """Adjust inventory when task completes and actual quantity differs from estimated.
        If actual < estimated, return excess to stock.
        If actual > estimated, consume additional stock."""
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
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
    def manual_adjustment(price_list_item, quantity_change, reason='', user=None):
        """Manually adjust QOH and record an audit-trail entry.
        Negative adjustments track as waste."""
        price_list_item.qty_on_hand = F('qty_on_hand') + quantity_change
        if quantity_change < Decimal('0.00'):
            price_list_item.qty_wasted = F('qty_wasted') - quantity_change
        price_list_item.save(update_fields=['qty_on_hand', 'qty_wasted'] if quantity_change < Decimal('0.00') else ['qty_on_hand'])
        price_list_item.refresh_from_db()

        InventoryService._record_qoh_history(
            price_list_item, quantity_change,
            action='Manual adjustment', reason=reason, user=user,
        )

    @staticmethod
    def receive_ad_hoc_purchase(material):
        """Increase QOH for an ad-hoc (job-level, no PO) purchase material.
        QOH-only — earmark was already created by MaterialService.create_on_job."""
        from django.db.models import F
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
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
        Reverses the full original purchase quantity (quantity + restocked_qty)."""
        from django.db.models import F
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return
        total = material.quantity + material.restocked_qty
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
        if not pli or not pli.is_inventoried or not qty or qty == Decimal('0.00'):
            return Decimal('0.00')
        pli.qty_on_hand = F('qty_on_hand') + qty
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        InventoryService._record_qoh_history(
            pli, qty, action='Stock receipt',
            reason=reason or 'Stock receipt (expense)', user=user,
        )
        return qty

    # --- PlanMaterial CRUD (worksheet-side) ---

    @staticmethod
    def create_plan_material(plan_task_pk, **kwargs):
        """Create a new PlanMaterial on a PlanTask."""
        from apps.core.services import NotFoundError
        from apps.jobs.models import PlanTask
        try:
            plan_task = PlanTask.objects.get(pk=plan_task_pk)
        except PlanTask.DoesNotExist:
            raise NotFoundError(f'PlanTask {plan_task_pk} not found')
        mat = PlanMaterial(
            plan_task=plan_task,
            est_worksheet_id=plan_task.est_worksheet_id,
            **kwargs,
        )
        mat.save()
        return mat

    @staticmethod
    def update_plan_material(pk, **kwargs):
        """Update an existing PlanMaterial by PK."""
        from apps.core.services import NotFoundError
        try:
            mat = PlanMaterial.objects.get(pk=pk)
        except PlanMaterial.DoesNotExist:
            raise NotFoundError(f'PlanMaterial {pk} not found')
        for field, value in kwargs.items():
            setattr(mat, field, value)
        mat.save()
        return mat

    @staticmethod
    def delete_plan_material(pk):
        """Delete a PlanMaterial by PK."""
        from apps.core.services import NotFoundError
        try:
            mat = PlanMaterial.objects.get(pk=pk)
        except PlanMaterial.DoesNotExist:
            raise NotFoundError(f'PlanMaterial {pk} not found')
        mat.delete()

    @staticmethod
    def update_plan_material_pricing(plan_material, *, unit_cost=None, sell_price=None, propagate_to_pli=False):
        """Same as MaterialService.update_pricing but for PlanMaterial."""
        from django.db import transaction
        with transaction.atomic():
            update_fields = []
            cost_changed = False
            price_changed = False
            if unit_cost is not None and unit_cost != plan_material.unit_cost:
                plan_material.unit_cost = unit_cost
                update_fields.append('unit_cost')
                cost_changed = True
            if sell_price is not None and sell_price != plan_material.sell_price:
                plan_material.sell_price = sell_price
                update_fields.append('sell_price')
                price_changed = True
            if update_fields:
                plan_material.save(update_fields=update_fields)

            if propagate_to_pli and plan_material.price_list_item_id is not None:
                pli = plan_material.price_list_item
                pli_fields = []
                if cost_changed and pli.purchase_price != plan_material.unit_cost:
                    pli.purchase_price = plan_material.unit_cost
                    pli_fields.append('purchase_price')
                if price_changed and pli.selling_price != plan_material.sell_price:
                    pli.selling_price = plan_material.sell_price
                    pli_fields.append('selling_price')
                if pli_fields:
                    pli.save(update_fields=pli_fields)
        return plan_material

    @staticmethod
    def create_plan_material_on_worksheet(worksheet, **kwargs):
        """Create a task-less PlanMaterial on a worksheet."""
        mat = PlanMaterial(est_worksheet=worksheet, plan_task=None, **kwargs)
        mat.save()
        return mat

    @staticmethod
    def assign_plan_task(plan_material, plan_task):
        """Move a PlanMaterial to a different PlanTask (or make it taskless with plan_task=None).

        Validates that plan_task (if given) belongs to the same worksheet as the material.
        Raises ValidationError on mismatch.
        """
        from django.core.exceptions import ValidationError
        if plan_task is not None:
            if plan_task.est_worksheet_id != plan_material.est_worksheet_id:
                raise ValidationError('PlanTask must belong to the same worksheet as the material')
        plan_material.plan_task = plan_task
        plan_material.save(update_fields=['plan_task_id'])

    # --- Thin wrappers for legacy HTML view call sites (to be removed in Phase 4) ---

    @staticmethod
    def create_material(task_pk, **kwargs):
        """Legacy wrapper; HTML views still call this on worksheet tasks."""
        return InventoryService.create_plan_material(task_pk, **kwargs)

    @staticmethod
    def update_material(pk, **kwargs):
        """Legacy wrapper; HTML views still call this."""
        return InventoryService.update_plan_material(pk, **kwargs)

    @staticmethod
    def delete_material(pk):
        """Legacy wrapper; HTML views still call this."""
        return InventoryService.delete_plan_material(pk)

    # --- Earmark operations ---

    @staticmethod
    def get_earmark_preview(job):
        """Get preview of inventoried items needed for a job's task materials.

        Aggregates by price_list_item across all Materials on all Tasks
        for this job. Returns list of dicts with price_list_item, needed_qty,
        available_qty, shortfall.
        """
        from apps.inventory.models import Material

        materials = Material.objects.filter(
            task__job=job,
            price_list_item__is_inventoried=True,
        ).values('price_list_item').annotate(
            total_qty=Sum('quantity'),
        )

        preview = []
        for entry in materials:
            item = InventoryItem.objects.get(pk=entry['price_list_item'])
            needed = entry['total_qty']
            available = item.qty_available
            shortfall = max(needed - available, Decimal('0.00'))
            preview.append({
                'price_list_item': item,
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
        job. Called as a hook after each job-population path (estimate, template,
        worksheet copy).
        """
        from apps.inventory.models import Material

        materials = Material.objects.filter(
            job=job,
            price_list_item__is_inventoried=True,
        ).values('price_list_item').annotate(
            total_qty=Sum('quantity'),
        )

        if not materials:
            return

        earmark_data = [
            {
                'price_list_item_id': entry['price_list_item'],
                'quantity': entry['total_qty'],
            }
            for entry in materials
        ]
        InventoryService._upsert_earmarks(job, earmark_data)

    @staticmethod
    def _upsert_earmarks(job, earmark_data):
        """Create or update earmarks from user-confirmed data.
        earmark_data: list of dicts with price_list_item_id and quantity."""
        for entry in earmark_data:
            qty = entry['quantity']
            if qty <= Decimal('0.00'):
                continue
            item = InventoryItem.objects.get(pk=entry['price_list_item_id'])
            earmark, created = Earmark.objects.get_or_create(
                price_list_item=item,
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
        if pli is None or not pli.is_inventoried:
            return
        try:
            earmark = Earmark.objects.get(price_list_item=pli, job=job)
        except Earmark.DoesNotExist:
            if delta > Decimal('0.00'):
                Earmark.objects.create(price_list_item=pli, job=job, quantity=delta)
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

            if propagate_to_pli and material.price_list_item_id is not None:
                pli = material.price_list_item
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
                      price_list_item=None, accounting_category=None, units='none',
                      source_plan_material=None, cost_source='document'):
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(job, 'add a material to this job')
        # Freeform (no-PLI) actual materials get their cost from a document
        # (Expense/PO), never typed manually.
        if (cost_source == 'manual' and price_list_item is None
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
                price_list_item=price_list_item,
                accounting_category=accounting_category,
                units=units,
                source_plan_material=source_plan_material,
            )
            m.save()  # full_clean() runs here; enforces task/job invariant
            InventoryService._mutate_earmark(price_list_item, job, quantity)
        return m

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
            pli = material.price_list_item
            if pli and pli.is_inventoried and qty > Decimal('0.00'):
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
        qty = material.quantity
        with transaction.atomic():
            pli = material.price_list_item
            if pli and pli.is_inventoried and qty > Decimal('0.00'):
                from django.db.models import F
                pli.qty_on_hand = F('qty_on_hand') + qty
                pli.qty_sold = F('qty_sold') - qty
                pli.save(update_fields=['qty_on_hand', 'qty_sold'])
                pli.refresh_from_db()
                InventoryService._mutate_earmark(pli, material.job, qty)
            material.consumption_state = Material.CONSUMPTION_STATE_PENDING
            material.save(update_fields=['consumption_state'])
        return material

    @staticmethod
    def restock(material, qty):
        from django.db import transaction
        from django.core.exceptions import ValidationError
        if qty <= Decimal('0.00') or qty > material.quantity:
            raise ValidationError('restock qty must be > 0 and <= quantity')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('restock requires pending state')
        expense_bound = material.is_expense_bound
        with transaction.atomic():
            InventoryService._mutate_earmark(material.price_list_item, material.job, -qty)
            material.quantity = material.quantity - qty
            update_fields = ['quantity']
            if expense_bound:
                material.restocked_qty = material.restocked_qty + qty
                update_fields.append('restocked_qty')
            material.save(update_fields=update_fields)
            if material.quantity == Decimal('0.00') and not expense_bound:
                material.delete()
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
            InventoryService._mutate_earmark(material.price_list_item, material.job, qty)
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
        """'keep' clears FK. 'delete' deletes the Material and backs out earmark.
        Raises if decision is invalid or Material is consumed."""
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
            InventoryService._mutate_earmark(
                material.price_list_item, material.job, -material.quantity,
            )
            material.delete()

    @staticmethod
    def resolve_or_create_for_line(po_line, *, job=None, price_list_item=None,
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
            if price_list_item is not None:
                candidates = Material.objects.select_for_update().filter(
                    job=job,
                    price_list_item=price_list_item,
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
                price_list_item=price_list_item,
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                accounting_category=accounting_category,
            )
            MaterialService.link_to_po_line(mat, po_line)
            return mat
