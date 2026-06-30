"""Task 4.3: Revising (superseding) an estimate releases its atom claims.

The superseded estimate keeps its EstimateLineItem rows as a frozen snapshot
but its EstimateLineItemSource rows must be deleted so the live job atoms
(Tasks / Materials / Fees) are free for the new/revised estimate to re-claim.
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
    """revise_estimate deletes source rows from the superseded estimate so
    atoms are freed; the new revision starts with unclaimed line items."""

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
        """EstimateLineItemSource rows must be deleted from the superseded estimate
        so its atom claims are released back to the live job."""
        EstimateService.revise_estimate(self.est.pk)

        # Count sources on the superseded estimate's line items.
        superseded_sources = EstimateLineItemSource.objects.filter(
            estimate_line_item__estimate=self.est,
        )
        self.assertEqual(
            superseded_sources.count(),
            0,
            'Superseded estimate must have no EstimateLineItemSource rows '
            '(atoms released to live job)',
        )

    def test_new_revision_can_reclaim_atoms(self):
        """After revision the freed atom must be claimable by the new estimate
        (no unique_together conflict, confirming the old claim was deleted)."""
        new_est = EstimateService.revise_estimate(self.est.pk)

        # The new estimate should have a copied line item.
        new_li = EstimateLineItem.objects.filter(estimate=new_est).first()
        self.assertIsNotNone(new_li, 'New estimate must have at least one line item')

        # Creating a new EstimateLineItemSource for the same task on the new
        # estimate's line item must succeed without IntegrityError.
        new_src = EstimateLineItemSource.objects.create(
            estimate_line_item=new_li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(new_src.source_pk, self.task.pk)

    def test_new_revision_starts_without_source_rows(self):
        """The new/revised estimate's line items must have no source rows of
        their own after revision (the user re-claims via the wizard)."""
        new_est = EstimateService.revise_estimate(self.est.pk)

        new_sources = EstimateLineItemSource.objects.filter(
            estimate_line_item__estimate=new_est,
        )
        self.assertEqual(
            new_sources.count(),
            0,
            'New estimate must have no source rows after revision '
            '(atoms are re-claimed via the wizard, not auto-transferred)',
        )
