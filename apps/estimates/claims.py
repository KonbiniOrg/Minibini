"""
Estimate claim service — mirrors apps/invoicing/claims.py for estimate-side
atom ownership. Used by the job-detail serializer to expose a per-atom
``claimed`` flag without N+1 queries.
"""
from apps.estimates.models import Estimate, EstimateLineItemSource


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
