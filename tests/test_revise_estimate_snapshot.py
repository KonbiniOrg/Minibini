from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable, DeliverableSnapshot
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class ReviseEstimateSnapshotTest(TestCase):
    """Superseding an estimate (via revise_estimate) freezes its deliverables
    onto a DeliverableSnapshot set, so an out-of-date estimate keeps the scope
    the customer saw while it was the live proposal."""

    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Snapshot Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Build widget',
            qty=Decimal('2'), units='each', price=Decimal('50.00'))
        self.d = Deliverable.objects.create(
            job=self.job, description='One finished widget',
            qty_ordered=Decimal('2'), units='each')

    def test_revise_snapshots_parent_deliverables(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        EstimateService.revise_estimate(self.est.pk)

        snaps = DeliverableSnapshot.objects.filter(estimate=self.est)
        self.assertEqual(snaps.count(), 1)
        snap = snaps.first()
        self.assertEqual(snap.description, 'One finished widget')
        self.assertEqual(snap.qty_ordered, Decimal('2'))
        self.assertEqual(snap.units, 'each')
        self.assertEqual(snap.source_deliverable, self.d)

    def test_new_revision_has_no_snapshot(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(self.est.pk)
        self.assertFalse(
            DeliverableSnapshot.objects.filter(estimate=new_est).exists())

    def test_snapshot_frozen_against_later_live_edit(self):
        # Supersede, which re-opens the live list for editing on the new draft.
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        EstimateService.revise_estimate(self.est.pk)
        # Edit the live deliverable as a revision would.
        self.d.refresh_from_db()
        self.d.qty_ordered = Decimal('99')
        self.d.description = 'Two finished widgets'
        self.d.save()

        snap = DeliverableSnapshot.objects.filter(estimate=self.est).first()
        self.assertEqual(snap.qty_ordered, Decimal('2'))
        self.assertEqual(snap.description, 'One finished widget')
