"""
Estimate claim service — mirrors apps/invoicing/claims.py for estimate-side
atom ownership. Used by the job-detail serializer to expose a per-atom
``claimed`` flag without N+1 queries.
"""
from apps.estimates.models import (
    ChangeOrderLineItemSource, Estimate, EstimateLineItemSource,
)


def atom_is_claimed(source_type, source_pk):
    """True when any estimate- or CO-lens source row points at the atom.

    The Rule-1 reference check for document claims: a claimed atom is part of
    a document's story and must be retired by a named event (change order,
    release), never hard-deleted. Invoice claims are checked separately via
    InvoiceClaimService.is_invoiced (which excludes cancelled invoices).
    """
    return (
        EstimateLineItemSource.objects.filter(
            source_type=source_type, source_pk=source_pk).exists()
        or ChangeOrderLineItemSource.objects.filter(
            source_type=source_type, source_pk=source_pk).exists()
    )


def atom_claimed_by_non_draft_document(source_type, source_pk):
    """True when a non-draft estimate or change order claims the atom.

    The Task variant of the Rule-1 check: draft claims stay deletable (the
    wizard's remove-atoms / line-delete releases them — "remove it from the
    line first"), but once the claiming document has been sent, the atom is
    part of a promise and must be cancelled, not deleted.
    """
    from apps.estimates.models import ChangeOrder
    return (
        EstimateLineItemSource.objects.filter(
            source_type=source_type, source_pk=source_pk,
        ).exclude(
            estimate_line_item__estimate__status=Estimate.STATUS_DRAFT,
        ).exists()
        or ChangeOrderLineItemSource.objects.filter(
            source_type=source_type, source_pk=source_pk,
        ).exclude(
            change_order_line_item__change_order__status=ChangeOrder.STATUS_DRAFT,
        ).exists()
    )


def purge_source_rows_for_atom(source_type, source_pk):
    """Drop the source rows of every document lens pointing at a deleted atom.

    Invariant: no EstimateLineItemSource / ChangeOrderLineItemSource /
    InvoiceLineItemSource row may outlive its atom — a dangling row breaks
    resolve() consumers (serializers, wizard bundle math). Called from
    Material.delete() and Task.delete(), so every deletion path
    (restock-to-zero, PO sever, task delete, CO retirement) upholds it. Paths that must NOT delete a
    billed atom guard *before* deleting (e.g. _assert_not_invoiced, the CO
    retirement skips); this purge is the consistency backstop, not the guard.
    """
    from apps.invoicing.models import InvoiceLineItemSource
    EstimateLineItemSource.objects.filter(
        source_type=source_type, source_pk=source_pk).delete()
    ChangeOrderLineItemSource.objects.filter(
        source_type=source_type, source_pk=source_pk).delete()
    InvoiceLineItemSource.objects.filter(
        source_type=source_type, source_pk=source_pk).delete()


class EstimateClaimService:
    """Single source of truth for 'is this atom on a live (non-superseded) estimate'."""

    @classmethod
    def _live_sources_for_job(cls, job):
        """EstimateLineItemSources whose estimate is NOT superseded, scoped to job."""
        return (
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=job)
            .exclude(estimate_line_item__estimate__status=Estimate.STATUS_SUPERSEDED)
        )

    @classmethod
    def claimed_set_for_job(cls, job):
        """Return a frozenset of (source_type, source_pk) tuples that are claimed
        by a non-superseded estimate on this job.

        'claimed' = referenced by an EstimateLineItemSource whose parent
        EstimateLineItem belongs to a non-SUPERSEDED Estimate on this job.

        Superseded estimates have had their source rows moved to the revision
        that superseded them (see EstimateService.revise_estimate); excluding
        them is therefore both logically correct and a safety net for any
        manually-constructed edge cases in tests.

        Returns an empty frozenset when no live estimates exist or no atoms
        are claimed (everything shows unclaimed).
        """
        return frozenset(
            cls._live_sources_for_job(job)
            .values_list('source_type', 'source_pk')
        )


# ---------------------------------------------------------------------------
# Dead-document claim release
# ---------------------------------------------------------------------------
# Both source models are globally unique on (source_type, source_pk), so a
# document that dies holding claims locks those atoms out of every FUTURE
# document on the job — permanently, since rejected/expired are terminal
# states. Releasing on death is the estimate/CO counterpart of
# InvoiceService.cancel deleting its rows (invoicing-and-expenses.md).
#
# Which statuses release:
#   rejected / expired  — the document died; nothing was promised, so its
#                         atoms return to the pool.
#   accepted            — NO. The claims ARE the agreement record (what was
#                         sold on which line); compose_agreement and
#                         ChangeOrderService.struck_atom_keys read them.
#   superseded          — already holds none: EstimateService.revise_estimate
#                         re-points the rows onto the new revision.
#
# Called from Estimate.save() / ChangeOrder.save() rather than a service, so
# every writer is covered — the portal decline endpoints, the expiry sweep,
# the status-transition actions, and the admin all go through save().
DEAD_DOCUMENT_STATUSES = ('rejected', 'expired')


def release_estimate_claims(estimate):
    """Drop every EstimateLineItemSource row under a dead estimate.

    The line items themselves stay: a rejected estimate remains a readable
    frozen snapshot of what was offered, exactly as a superseded one does.
    """
    EstimateLineItemSource.objects.filter(
        estimate_line_item__estimate=estimate).delete()


def release_change_order_claims(change_order):
    """ChangeOrderLineItemSource counterpart of release_estimate_claims."""
    ChangeOrderLineItemSource.objects.filter(
        change_order_line_item__change_order=change_order).delete()
