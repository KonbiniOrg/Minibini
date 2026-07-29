from apps.invoicing.models import Invoice, InvoiceLineItemSource

# Statuses in which an invoice is DEAD: it no longer bills anything, so it
# must hold no atom claims. Both source models are globally unique on
# (source_type, source_pk), so a dead document that kept its rows would lock
# those atoms out of every future invoice on the job.
#
#   cancelled   — void. Its atoms go back in the pool.
#   superseded  — nothing writes it yet (there is no invoice-revision flow;
#                 see LATER.md), but the invariant should not wait for one.
#                 Matches the SPA's INVOICE_DEAD_STATUSES, which has always
#                 counted it dead. NOTE for whoever builds invoice revision:
#                 move or re-point the source rows BEFORE flipping the parent
#                 to superseded, the way EstimateService.revise_estimate does
#                 — the release below fires on that transition.
#
# `paid` is emphatically not here: a paid invoice's claims are what stop the
# same atom being billed twice.
DEAD_INVOICE_STATUSES = (Invoice.STATUS_CANCELLED, Invoice.STATUS_SUPERSEDED)


def release_invoice_claims(invoice):
    """Drop every InvoiceLineItemSource row under a dead invoice.

    The line items themselves stay: a cancelled invoice remains a readable
    frozen snapshot of what it charged, the same shape a rejected estimate
    takes (apps/estimates/claims.py).

    Lives here and is called from Invoice.save() rather than from
    InvoiceService.cancel, so every writer is covered — including whatever
    supersedes an invoice once revision exists.
    """
    InvoiceLineItemSource.objects.filter(
        invoice_line_item__invoice=invoice).delete()


class InvoiceClaimService:
    """Single source of truth for 'is this atom on a live (non-cancelled) invoice'."""

    @staticmethod
    def _live_sources():
        return (
            InvoiceLineItemSource.objects
            .exclude(invoice_line_item__invoice__status__in=DEAD_INVOICE_STATUSES)
        )

    @classmethod
    def is_invoiced(cls, source_type, source_pk):
        return cls._live_sources().filter(
            source_type=source_type, source_pk=source_pk,
        ).exists()

    @classmethod
    def _map(cls, queryset):
        result = {}
        # display_number reads invoice.job.job_number — join it here or every
        # claim row costs a job query.
        for src in queryset.select_related('invoice_line_item__invoice__job'):
            inv = src.invoice_line_item.invoice
            result[(src.source_type, src.source_pk)] = {
                'invoice_id': inv.pk,
                'invoice_number': inv.display_number,
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
