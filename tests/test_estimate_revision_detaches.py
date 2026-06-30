"""Task 4.3: Revising (superseding) an estimate MOVES its atom claims to the new revision.

The superseded estimate keeps its EstimateLineItem rows as a frozen snapshot
but its EstimateLineItemSource rows are moved to the new revision's copied
line items so the live job atoms (Tasks / Materials / Fees) remain referenced
by default on the new draft — the user can later release or hold them via the
wizard.  Each atom is claimed exactly once throughout (unique_together remains
satisfied because the source row is re-pointed, not duplicated or dropped).
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService


class EstimateRevisionDetachesTest(TestCase):
    """revise_estimate moves source rows from the superseded estimate to the
    new revision, keeping the parent as a frozen snapshot (no sources) while
    the new revision references the job's atoms by default."""

    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Ada', last_name='Revision', email='ada@test.com')
        self.job = JobService.create_job(name='Revision Job', contact=self.contact)

        # A rate scheme and task on the job — the atom to claim.
        self.cat = AccountingCategory.objects.create(name='Labor-revdet', is_active=True)
        self.scheme = RateScheme.objects.create(
            name='Hourly-revdet',
            algorithm=RateScheme.ELAPSED_TIME,
            unit_label='hr',
            rate=Decimal('75.00'),
            accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job,
            name='Design work',
            rate_scheme=self.scheme,
            est_qty=Decimal('4'),
        )

        # An estimate with one line item that has an atom claim on the task.
        self.est = EstimateService.create_for_job(self.job.pk)
        self.li = EstimateLineItem.objects.create(
            estimate=self.est,
            description='Design work',
            qty=Decimal('4'),
            units='hr',
            price=Decimal('300.00'),
            line_number=1,
        )
        self.src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

        # Move the estimate to OPEN so revise_estimate will accept it.
        Estimate.objects.filter(pk=self.est.pk).update(
            status=Estimate.STATUS_OPEN,
        )
        self.est.refresh_from_db()

    def test_superseded_estimate_keeps_line_items(self):
        """The frozen snapshot (EstimateLineItem rows) must survive revision."""
        EstimateService.revise_estimate(self.est.pk)
        self.est.refresh_from_db()

        self.assertEqual(self.est.status, Estimate.STATUS_SUPERSEDED)
        self.assertTrue(
            EstimateLineItem.objects.filter(estimate=self.est).exists(),
            'Superseded estimate must keep its EstimateLineItem rows as a frozen snapshot',
        )

    def test_superseded_estimate_loses_source_rows(self):
        """EstimateLineItemSource rows must be moved away from the superseded
        estimate so the parent line items become a frozen snapshot (no live
        atom links)."""
        EstimateService.revise_estimate(self.est.pk)

        # Count sources still on the superseded estimate's line items.
        superseded_sources = EstimateLineItemSource.objects.filter(
            estimate_line_item__estimate=self.est,
        )
        self.assertEqual(
            superseded_sources.count(),
            0,
            'Superseded estimate must have no EstimateLineItemSource rows '
            '(sources moved to the new revision)',
        )

    def test_new_revision_has_source_rows(self):
        """After revision the new estimate's copied line items must carry the
        source rows that were on the parent — atoms referenced by default."""
        new_est = EstimateService.revise_estimate(self.est.pk)

        new_sources = EstimateLineItemSource.objects.filter(
            estimate_line_item__estimate=new_est,
        )
        self.assertEqual(
            new_sources.count(),
            1,
            'New estimate must inherit the source rows from the parent '
            '(atom references by default, moved not deleted)',
        )
        self.assertEqual(
            new_sources.first().source_pk,
            self.task.pk,
            'Moved source row must still reference the same job atom (task pk)',
        )

    def test_atom_claim_count_is_exactly_one(self):
        """The atom must be claimed exactly once across all estimates after
        revision — source moved (not duplicated or dropped), no IntegrityError."""
        new_est = EstimateService.revise_estimate(self.est.pk)

        total_claims = EstimateLineItemSource.objects.filter(
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(
            total_claims.count(),
            1,
            'Atom must be claimed exactly once after revision '
            '(source moved from parent to new revision, not duplicated)',
        )
        # And the single remaining claim is on the new revision, not the parent.
        self.assertEqual(
            total_claims.first().estimate_line_item.estimate_id,
            new_est.pk,
            'The surviving source row must belong to the new revision, not the superseded parent',
        )
