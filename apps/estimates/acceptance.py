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
from django.core.exceptions import ValidationError
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

        from apps.estimates.models import EstimateLineItemSource

        fees_created = 0
        for li in estimate.estimatelineitem_set.all():
            if li.sources.exists():              # atom-backed → already on the job
                continue
            if li.adjustment_service_id is not None:  # percentage adjustments stay document-only
                continue
            # Defensive guard: Fee.accounting_category is NOT NULL. A hand-line
            # with no category would throw an opaque IntegrityError. Raise a
            # clear ValidationError here instead so the caller gets a useful message.
            if li.accounting_category_id is None:
                raise ValidationError(
                    f'Estimate line "{li.description or "(no description)"}" '
                    f'has no accounting category. All hand-line items must have '
                    f'an accounting category before the estimate can be accepted.'
                )
            fee = Fee.objects.create(
                job=job,
                description=li.description or '',
                quantity=li.qty or Decimal('1'),
                unit_rate=li.price or Decimal('0'),
                accounting_category=li.accounting_category,
                sort_order=li.line_number or 0,
            )
            # Link the estimate line to its crystallized Fee so copy_from_estimate
            # can trace which hand-line maps to which Fee and claim it on the invoice.
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_FEE,
                source_pk=fee.pk,
            )
            fees_created += 1

        InventoryService.create_earmarks_for_job(job)
        return {'fees_created': fees_created}
