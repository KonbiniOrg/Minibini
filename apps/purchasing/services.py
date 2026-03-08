from django.core.exceptions import ValidationError
from django.db import transaction

from apps.purchasing.models import (
    PurchaseOrder, Bill, PurchaseOrderLineItem, BillLineItem,
)
from apps.core.services import NotFoundError, NumberGenerationService


class PurchaseOrderService:
    """Service for purchase order operations."""

    @staticmethod
    def create_po(**kwargs):
        """Create a new PurchaseOrder with auto-generated number."""
        po_number = NumberGenerationService.generate_next_number('po')
        po = PurchaseOrder(po_number=po_number, **kwargs)
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def update_po(pk, **kwargs):
        """Update an existing PurchaseOrder by PK."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        for field, value in kwargs.items():
            setattr(po, field, value)
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def update_status(pk, new_status):
        """Update PO status."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        po.status = new_status
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def cancel_po(pk):
        """Cancel an issued PO."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != 'issued':
            raise ValidationError(
                f'Cannot cancel PO {po.po_number}. Only issued POs can be cancelled.'
            )
        po.status = 'cancelled'
        po.full_clean()
        po.save()
        return po

    @staticmethod
    def delete_po(pk):
        """Delete a draft PO."""
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != 'draft':
            raise ValidationError(
                f'Cannot delete PO {po.po_number}. Only draft POs can be deleted.'
            )
        po.delete()

    @staticmethod
    def add_line_item(po_id, **kwargs):
        """Add a manual line item to a PO."""
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        li = PurchaseOrderLineItem(purchase_order=po, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(po_id, price_list_item_id, qty):
        """Add a line item from a PriceListItem."""
        from apps.inventory.models import PriceListItem
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        try:
            pli = PriceListItem.objects.get(pk=price_list_item_id)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {price_list_item_id} not found')
        li = PurchaseOrderLineItem(
            purchase_order=po,
            price_list_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.purchase_price,
            line_item_type=pli.line_item_type,
        )
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder a PO line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft purchase order.'
            )
        return LineItemService.reorder_line_item(li, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete a PO line item and renumber — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft purchase order.'
            )
        return LineItemService.delete_line_item_with_renumber(li)


class BillService:
    """Service for bill operations."""

    @staticmethod
    def create_bill(**kwargs):
        """Create a new Bill with auto-generated number."""
        bill_number = NumberGenerationService.generate_next_number('bill')
        bill = Bill(bill_number=bill_number, **kwargs)
        bill.full_clean()
        bill.save()
        return bill

    @staticmethod
    @transaction.atomic
    def create_bill_from_po(po_id, **kwargs):
        """Create a bill from a PO, copying its line items."""
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')

        bill_number = NumberGenerationService.generate_next_number('bill')
        bill = Bill(
            bill_number=bill_number,
            purchase_order=po,
            business=po.business,
            contact=po.contact,
            **kwargs,
        )
        bill.full_clean()
        bill.save()

        # Copy line items from PO
        po_line_items = PurchaseOrderLineItem.objects.filter(
            purchase_order=po
        ).order_by('line_number')
        for po_li in po_line_items:
            BillLineItem.objects.create(
                bill=bill,
                price_list_item=po_li.price_list_item,
                task=po_li.task,
                description=po_li.description,
                qty=po_li.qty,
                units=po_li.units,
                price=po_li.price,
                line_number=po_li.line_number,
                line_item_type=po_li.line_item_type,
            )

        return bill

    @staticmethod
    def update_status(pk, new_status):
        """Update bill status."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        bill.status = new_status
        bill.full_clean()
        bill.save()
        return bill

    @staticmethod
    def delete_bill(pk):
        """Delete a draft bill."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        if bill.status != 'draft':
            raise ValidationError(
                f'Cannot delete Bill {bill.bill_number}. Only draft bills can be deleted.'
            )
        bill.delete()

    @staticmethod
    def add_line_item(bill_id, **kwargs):
        """Add a manual line item to a bill."""
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        li = BillLineItem(bill=bill, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(bill_id, price_list_item_id, qty):
        """Add a line item from a PriceListItem."""
        from apps.inventory.models import PriceListItem
        try:
            bill = Bill.objects.get(pk=bill_id)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {bill_id} not found')
        try:
            pli = PriceListItem.objects.get(pk=price_list_item_id)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {price_list_item_id} not found')
        li = BillLineItem(
            bill=bill,
            price_list_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.purchase_price,
            line_item_type=pli.line_item_type,
        )
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder a bill line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = BillLineItem.objects.get(pk=line_item_id)
        except BillLineItem.DoesNotExist:
            raise NotFoundError(f'BillLineItem {line_item_id} not found')
        if li.bill.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft bill.'
            )
        return LineItemService.reorder_line_item(li, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete a bill line item and renumber — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            li = BillLineItem.objects.get(pk=line_item_id)
        except BillLineItem.DoesNotExist:
            raise NotFoundError(f'BillLineItem {line_item_id} not found')
        if li.bill.status != 'draft':
            raise ValidationError(
                'Cannot modify line items on a non-draft bill.'
            )
        return LineItemService.delete_line_item_with_renumber(li)
