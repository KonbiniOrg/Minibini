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
        if po.status != PurchaseOrder.STATUS_ISSUED:
            raise ValidationError(
                f'Cannot cancel PO {po.po_number}. Only issued POs can be cancelled.'
            )
        po.status = PurchaseOrder.STATUS_CANCELLED
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
        if po.status != PurchaseOrder.STATUS_DRAFT:
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
            accounting_category=pli.accounting_category,
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
        if li.purchase_order.status != PurchaseOrder.STATUS_DRAFT:
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
        if li.purchase_order.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft purchase order.'
            )
        return LineItemService.delete_line_item_with_renumber(li)


class PurchaseOrderEmailService:
    """Service for sending purchase orders to vendors via email."""

    DEFAULT_SUBJECT = 'Purchase Order {po_number}'
    DEFAULT_BODY = (
        'Please find attached Purchase Order {po_number}.\n\n'
        'If you have any questions, please contact us.\n\n'
        'Thank you.'
    )

    @staticmethod
    def get_email_defaults(po):
        """Get the pre-populated email fields for a PO."""
        from apps.core.models import Configuration

        subject_template = PurchaseOrderEmailService.DEFAULT_SUBJECT
        body_template = PurchaseOrderEmailService.DEFAULT_BODY

        try:
            subject_template = Configuration.objects.get(
                key='po_email_subject_template'
            ).value
        except Configuration.DoesNotExist:
            pass

        try:
            body_template = Configuration.objects.get(
                key='po_email_body_template'
            ).value
        except Configuration.DoesNotExist:
            pass

        vendor_name = po.business.business_name if po.business else ''

        replacements = {
            'po_number': po.po_number,
            'vendor_name': vendor_name,
        }

        subject = subject_template.format(**replacements)
        body = body_template.format(**replacements)

        to = ''
        if po.contact and po.contact.email:
            to = po.contact.email

        return {'to': to, 'subject': subject, 'body': body}

    @staticmethod
    def send_po(po, to, subject, body, user=None):
        """
        Send a PO as a PDF attachment via email.
        If the PO is in draft status, it is issued first.
        Creates a HistoryEntry recording the send.
        Returns the updated PO.
        """
        from apps.core.models import HistoryEntry
        from apps.core.services import OutboundEmailService
        from apps.purchasing.pdf import generate_purchase_order_pdf

        if not to:
            raise ValidationError('Recipient email address is required.')
        if isinstance(to, str):
            to = [addr.strip() for addr in to.split(',') if addr.strip()]
            if not to:
                raise ValidationError('Recipient email address is required.')

        if po.status == PurchaseOrder.STATUS_DRAFT:
            if not po.purchaseorderlineitem_set.exists():
                raise ValidationError(
                    'Cannot issue a PO with no line items.'
                )
            po.status = PurchaseOrder.STATUS_ISSUED
            po.full_clean()
            po.save()

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot send a PO in status "{po.status}".'
            )

        pdf_bytes = generate_purchase_order_pdf(po)
        filename = f'{po.po_number}.pdf'

        to_list = to if isinstance(to, list) else [to]

        OutboundEmailService.send_email(
            to=to_list,
            subject=subject,
            body=body,
            attachments=[(filename, pdf_bytes, 'application/pdf')],
        )

        HistoryEntry.objects.create(
            entry_type='action',
            object_type='purchaseorder',
            object_id=po.pk,
            user=user,
            changes={'_action': f'PO emailed to {", ".join(to_list)}'},
        )

        return po


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
                accounting_category=po_li.accounting_category,
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
        if bill.status != Bill.STATUS_DRAFT:
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
            accounting_category=pli.accounting_category,
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
        if li.bill.status != Bill.STATUS_DRAFT:
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
        if li.bill.status != Bill.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft bill.'
            )
        return LineItemService.delete_line_item_with_renumber(li)
