from decimal import Decimal
from django.db.models import F, Sum
from apps.inventory.models import Earmark, InventoryAdjustment, Material, PlanMaterial
from apps.inventory.models import PriceListItem


class InventoryService:
    """Service for inventory operations: PriceListItem CRUD, QOH updates, and earmarks."""

    # --- PriceListItem CRUD ---

    @staticmethod
    def create_item(**kwargs):
        """Create a new PriceListItem."""
        from apps.core.services import NotFoundError
        pli = PriceListItem(**kwargs)
        pli.full_clean()
        pli.save()
        return pli

    @staticmethod
    def update_item(pk, **kwargs):
        """Update an existing PriceListItem by PK."""
        from apps.core.services import NotFoundError
        try:
            pli = PriceListItem.objects.get(pk=pk)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {pk} not found')
        for field, value in kwargs.items():
            setattr(pli, field, value)
        pli.full_clean()
        pli.save()
        return pli

    # --- QOH operations ---

    @staticmethod
    def receive_po_line_item(po_line_item):
        """Increase QOH for inventoried PO line items.
        Creates/updates earmark if line item has a job."""
        pli = po_line_item.price_list_item
        if not pli or not pli.is_inventoried:
            return

        pli.qty_on_hand = F('qty_on_hand') + po_line_item.qty
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()

        if po_line_item.job:
            InventoryService._mutate_earmark(pli, po_line_item.job, po_line_item.qty)

    @staticmethod
    def consume_material(material):
        """Decrease QOH and increase qty_sold when material is consumed at task start.
        Reduces/clears earmark for the material's job. Sets consumption_state=consumed."""
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return

        pli.qty_on_hand = F('qty_on_hand') - material.quantity
        pli.qty_sold = F('qty_sold') + material.quantity
        pli.save(update_fields=['qty_on_hand', 'qty_sold'])
        pli.refresh_from_db()

        # Reduce or clear earmark
        job = material.job
        if job:
            try:
                earmark = Earmark.objects.get(
                    price_list_item=pli, job=job,
                )
                new_qty = earmark.quantity - material.quantity
                if new_qty <= Decimal('0.00'):
                    earmark.delete()
                else:
                    earmark.quantity = new_qty
                    earmark.save(update_fields=['quantity'])
            except Earmark.DoesNotExist:
                pass

        material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        material.save(update_fields=['consumption_state'])

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
    def manual_adjustment(price_list_item, quantity_change, reason=''):
        """Manually adjust QOH and create an audit record.
        Negative adjustments track as waste."""
        price_list_item.qty_on_hand = F('qty_on_hand') + quantity_change
        if quantity_change < Decimal('0.00'):
            price_list_item.qty_wasted = F('qty_wasted') - quantity_change
        price_list_item.save(update_fields=['qty_on_hand', 'qty_wasted'] if quantity_change < Decimal('0.00') else ['qty_on_hand'])
        price_list_item.refresh_from_db()

        InventoryAdjustment.objects.create(
            price_list_item=price_list_item,
            quantity_change=quantity_change,
            reason=reason,
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

    @staticmethod
    def reverse_ad_hoc_purchase(material):
        """Decrease QOH to reverse a previously received ad-hoc purchase.
        QOH-only — earmark is managed separately."""
        from django.db.models import F
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return
        pli.qty_on_hand = F('qty_on_hand') - material.quantity
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()

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
    def create_plan_material_on_worksheet(worksheet, **kwargs):
        """Create a task-less PlanMaterial on a worksheet."""
        mat = PlanMaterial(est_worksheet=worksheet, plan_task=None, **kwargs)
        mat.save()
        return mat

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
            item = PriceListItem.objects.get(pk=entry['price_list_item'])
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
            item = PriceListItem.objects.get(pk=entry['price_list_item_id'])
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

        Called when a Job enters work_complete — any un-consumed earmark
        balance is released back to general inventory availability.
        """
        Earmark.objects.filter(job=job).delete()


class MaterialService:
    """Sole entry point for Material row creation and lifecycle ops.
    All earmark mutations go through InventoryService._mutate_earmark."""

    @staticmethod
    def create_on_job(*, job, task=None, description='', quantity=Decimal('0.00'),
                      unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                      price_list_item=None, accounting_category=None):
        from django.db import transaction
        with transaction.atomic():
            m = Material(
                job=job, task=task,
                description=description, quantity=quantity,
                unit_cost=unit_cost, sell_price=sell_price,
                price_list_item=price_list_item,
                accounting_category=accounting_category,
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
        eff = material.effective_qty
        if eff <= Decimal('0.00'):
            return material
        with transaction.atomic():
            pli = material.price_list_item
            if pli and pli.is_inventoried:
                from django.db.models import F
                pli.qty_on_hand = F('qty_on_hand') - eff
                pli.qty_sold = F('qty_sold') + eff
                pli.save(update_fields=['qty_on_hand', 'qty_sold'])
                pli.refresh_from_db()
                InventoryService._mutate_earmark(pli, material.job, -eff)
            material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
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
