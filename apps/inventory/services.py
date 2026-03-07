from decimal import Decimal
from django.db.models import F, Sum
from apps.inventory.models import Earmark, InventoryAdjustment
from apps.invoicing.models import PriceListItem


class InventoryService:
    """Service for automatic inventory QOH updates."""

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
            earmark, created = Earmark.objects.get_or_create(
                price_list_item=pli,
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
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return

        pli.qty_on_hand = F('qty_on_hand') - material.quantity
        pli.qty_sold = F('qty_sold') + material.quantity
        pli.save(update_fields=['qty_on_hand', 'qty_sold'])
        pli.refresh_from_db()

        # Reduce or clear earmark
        job = material.task.est_worksheet.job if material.task.est_worksheet else (
            material.task.work_order.job if material.task.work_order else None
        )
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


class EarmarkService:
    """Service for earmarking inventory when a job is approved."""

    @staticmethod
    def get_earmark_preview(job):
        """Get preview of inventoried items needed for a job's materials.
        Aggregates by price_list_item across all tasks on the job's worksheets.
        Returns list of dicts with price_list_item, needed_qty, available_qty, shortfall."""
        from apps.jobs.models import Material

        # Find all materials with inventoried price list items across the job's worksheets
        materials = Material.objects.filter(
            task__est_worksheet__job=job,
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
    def create_earmarks_for_job(job, earmark_data):
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
