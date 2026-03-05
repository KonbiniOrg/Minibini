from decimal import Decimal
from django.db.models import F, Sum
from apps.inventory.models import InventoryItem, Earmark, InventoryAdjustment


class InventoryService:
    """Service for automatic inventory QOH updates."""

    @staticmethod
    def receive_po_line_item(po_line_item):
        """Increase QOH for inventory-linked PO line items.
        Creates/updates earmark if line item has a job."""
        if not po_line_item.inventory_item:
            return

        item = po_line_item.inventory_item
        item.qty_on_hand = F('qty_on_hand') + po_line_item.qty
        item.save(update_fields=['qty_on_hand'])
        item.refresh_from_db()

        if po_line_item.job:
            earmark, created = Earmark.objects.get_or_create(
                inventory_item=item,
                job=po_line_item.job,
                defaults={'quantity': po_line_item.qty},
            )
            if not created:
                earmark.quantity = F('quantity') + po_line_item.qty
                earmark.save(update_fields=['quantity'])

    @staticmethod
    def consume_material(material):
        """Decrease QOH and increase qty_sold when material is consumed at task start.
        Reduces/clears earmark for the material's job."""
        if not material.inventory_item:
            return

        item = material.inventory_item
        item.qty_on_hand = F('qty_on_hand') - material.quantity
        item.qty_sold = F('qty_sold') + material.quantity
        item.save(update_fields=['qty_on_hand', 'qty_sold'])
        item.refresh_from_db()

        # Reduce or clear earmark
        job = material.task.est_worksheet.job if material.task.est_worksheet else (
            material.task.work_order.job if material.task.work_order else None
        )
        if job:
            try:
                earmark = Earmark.objects.get(
                    inventory_item=item, job=job,
                )
                new_qty = earmark.quantity - material.quantity
                if new_qty <= Decimal('0.00'):
                    earmark.delete()
                else:
                    earmark.quantity = new_qty
                    earmark.save(update_fields=['quantity'])
            except Earmark.DoesNotExist:
                pass

    @staticmethod
    def complete_task_adjustment(material, actual_qty):
        """Adjust inventory when task completes and actual quantity differs from estimated.
        If actual < estimated, return excess to stock.
        If actual > estimated, consume additional stock."""
        if not material.inventory_item:
            return

        difference = actual_qty - material.quantity
        if difference == Decimal('0.00'):
            return

        item = material.inventory_item
        # difference > 0 means more consumed (decrease QOH more)
        # difference < 0 means less consumed (increase QOH back)
        item.qty_on_hand = F('qty_on_hand') - difference
        item.qty_sold = F('qty_sold') + difference
        item.save(update_fields=['qty_on_hand', 'qty_sold'])
        item.refresh_from_db()

    @staticmethod
    def manual_adjustment(inventory_item, quantity_change, reason=''):
        """Manually adjust QOH and create an audit record.
        Negative adjustments track as waste."""
        inventory_item.qty_on_hand = F('qty_on_hand') + quantity_change
        if quantity_change < Decimal('0.00'):
            inventory_item.qty_wasted = F('qty_wasted') - quantity_change
        inventory_item.save(update_fields=['qty_on_hand', 'qty_wasted'] if quantity_change < Decimal('0.00') else ['qty_on_hand'])
        inventory_item.refresh_from_db()

        InventoryAdjustment.objects.create(
            inventory_item=inventory_item,
            quantity_change=quantity_change,
            reason=reason,
        )


class EarmarkService:
    """Service for earmarking inventory when a job is approved."""

    @staticmethod
    def get_earmark_preview(job):
        """Get preview of inventory items needed for a job's materials.
        Aggregates by inventory item across all tasks on the job's worksheets.
        Returns list of dicts with inventory_item, needed_qty, available_qty, shortfall."""
        from apps.jobs.models import Material

        # Find all materials with inventory items across the job's worksheets
        materials = Material.objects.filter(
            task__est_worksheet__job=job,
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
    def create_earmarks_for_job(job, earmark_data):
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
