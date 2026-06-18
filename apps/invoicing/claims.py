from apps.invoicing.models import Invoice, InvoiceLineItemSource


class InvoiceClaimService:
    """Single source of truth for 'is this atom on a live (non-cancelled) invoice'."""

    @staticmethod
    def _live_sources():
        return (
            InvoiceLineItemSource.objects
            .exclude(invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED)
        )

    @classmethod
    def is_invoiced(cls, source_type, source_pk):
        return cls._live_sources().filter(
            source_type=source_type, source_pk=source_pk,
        ).exists()

    @classmethod
    def _map(cls, queryset):
        result = {}
        for src in queryset.select_related('invoice_line_item__invoice'):
            inv = src.invoice_line_item.invoice
            result[(src.source_type, src.source_pk)] = {
                'invoice_id': inv.pk,
                'invoice_number': inv.invoice_number,
            }
        return result

    @classmethod
    def claims_for_job(cls, job):
        return cls._map(
            cls._live_sources().filter(invoice_line_item__invoice__job=job)
        )

    @classmethod
    def claims_for_atoms(cls, source_type, pks):
        if not pks:
            return {}
        return cls._map(
            cls._live_sources().filter(source_type=source_type, source_pk__in=list(pks))
        )
