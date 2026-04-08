from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.core.services import NotFoundError, TaxCalculationService


class InvoiceService:
    """Service for invoice operations."""

    @staticmethod
    def _validate_draft(invoice):
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Can only modify line items on draft invoices.'
            )

    @staticmethod
    def add_line_item(invoice_pk, **kwargs):
        """Add a manual line item to a draft invoice."""
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(InvoiceLineItem, kwargs)
        li = InvoiceLineItem(invoice=invoice, **kwargs)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def add_line_item_from_pli(invoice_pk, pli_pk, qty):
        """Add a line item from a PriceListItem to a draft invoice."""
        from apps.inventory.models import PriceListItem
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        try:
            pli = PriceListItem.objects.get(pk=pli_pk)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {pli_pk} not found')
        li = InvoiceLineItem(
            invoice=invoice,
            price_list_item=pli,
            description=pli.description,
            qty=qty,
            units=pli.units,
            price=pli.selling_price,
            accounting_category=pli.accounting_category,
        )
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def update_line_item(line_item_id, **kwargs):
        """Update an invoice line item — validates draft status."""
        try:
            li = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        InvoiceService._validate_draft(li.invoice)
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(InvoiceLineItem, kwargs)
        for field, value in kwargs.items():
            setattr(li, field, value)
        li.full_clean()
        li.save()
        return li

    @staticmethod
    def reorder_line_items(invoice_pk, item_ids):
        """Reorder invoice line items by position list — validates draft status."""
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        from django.db import transaction as db_transaction
        with db_transaction.atomic():
            for position, item_id in enumerate(item_ids, start=1):
                InvoiceLineItem.objects.filter(
                    pk=item_id, invoice=invoice,
                ).update(line_number=position)

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder an invoice line item — validates draft status, delegates to LineItemService."""
        from apps.core.services import LineItemService
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        if line_item.invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft invoice.'
            )
        return LineItemService.reorder_line_item(line_item, direction)

    @staticmethod
    def delete_line_item(line_item_id):
        """Delete an invoice line item and renumber — validates draft status."""
        from apps.core.services import LineItemService
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        if line_item.invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError(
                'Cannot modify line items on a non-draft invoice.'
            )
        return LineItemService.delete_line_item_with_renumber(line_item)


class InvoiceGroupingService:
    """Groups invoice line items by AccountingCategory + taxability for QBO push."""

    @staticmethod
    def group_for_qbo(invoice):
        line_items = invoice.invoicelineitem_set.select_related('accounting_category').all()
        job_number = invoice.job.job_number

        groups = defaultdict(lambda: {
            'amount': Decimal('0.00'),
            'category_name': '',
            'qbo_item_id': '',
            'taxable': False,
        })

        for item in line_items:
            taxable = TaxCalculationService.get_effective_taxability(item)
            cat = item.accounting_category
            cat_id = cat.pk if cat else None
            key = (cat_id, taxable)

            groups[key]['amount'] += item.total_amount
            groups[key]['taxable'] = taxable

            if cat:
                groups[key]['category_name'] = cat.name
                groups[key]['qbo_item_id'] = cat.qbo_item_id
            else:
                groups[key]['category_name'] = 'Uncategorized'

        result = []
        for (cat_id, taxable), data in groups.items():
            tax_label = '(taxable)' if taxable else '(non-taxable)'
            data['description'] = f"Job {job_number}: {data['category_name']} {tax_label}"
            result.append(data)

        return sorted(result, key=lambda g: g['category_name'])
