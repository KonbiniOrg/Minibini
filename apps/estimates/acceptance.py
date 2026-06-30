"""Acceptance crystallizes hand-lines into Fees (replaces worksheet carry-over).

Triggered when an Estimate transitions to ACCEPTED (see apps/estimates/signals.py).
In the job-owns-atoms model, work already lives on the Job (Tasks/Materials created
directly), so there is nothing to copy from a worksheet. Instead, acceptance:

  1. For each accepted-estimate line item with NO source row (a hand-line) that is
     not a percentage adjustment, creates a Fee on the job (the crystallized,
     frozen form of that charge).
  2. Earmarks the job's inventoried materials.

Atom-backed lines (those with an EstimateLineItemSource) already have their
Tasks/Materials on the job — nothing to convert. Adjustment lines stay
document-only (they recompute against the live lines and never become Fees).
"""
from decimal import Decimal
from django.db import transaction


class EstimateAcceptanceService:

    @staticmethod
    @transaction.atomic
    def on_accept(estimate):
        """Crystallize the estimate's hand-lines into Fees, then earmark the job.

        Returns: {'fees_created': int}
        """
        from apps.jobs.models import Fee
        from apps.inventory.services import InventoryService

        job = estimate.job
        # A sibling signal (estimate_status_changed_for_job) approves the job just
        # before this fires; refresh so we act against committed state.
        job.refresh_from_db()

        fees_created = 0
        for li in estimate.estimatelineitem_set.all():
            if li.sources.exists():              # atom-backed → already on the job
                continue
            if li.adjustment_service_id is not None:  # percentage adjustments stay document-only
                continue
            Fee.objects.create(
                job=job,
                description=li.description or '',
                quantity=li.qty or Decimal('1'),
                unit_rate=li.price or Decimal('0'),
                accounting_category=li.accounting_category,
                sort_order=li.line_number or 0,
            )
            fees_created += 1

        InventoryService.create_earmarks_for_job(job)
        return {'fees_created': fees_created}
