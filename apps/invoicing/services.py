from apps.invoicing.models import InvoiceLineItem
from apps.core.services import NotFoundError


class InvoiceService:
    """Service for invoice operations."""

    @staticmethod
    def reorder_line_item(line_item_id, direction):
        """Reorder an invoice line item by delegating to LineItemService.

        Args:
            line_item_id: PK of the InvoiceLineItem
            direction: 'up' or 'down'

        Raises:
            NotFoundError: if line item not found
            ValidationError: if invoice is not in draft status
        """
        from apps.core.services import LineItemService
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_id)
        except InvoiceLineItem.DoesNotExist:
            raise NotFoundError(f'InvoiceLineItem {line_item_id} not found')
        return LineItemService.reorder_line_item(line_item, direction)
