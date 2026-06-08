"""Tests for ChangeOrderService.compose_deliverable_diff — the baseline-vs-live
deliverable diff shared by the customer portal payload and the CO PDF."""
from decimal import Decimal

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import Estimate
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _advance_job_to_on_hold(job):
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_ON_HOLD):
        job.status = s
        job.save()
    job.refresh_from_db()


class ComposeDeliverableDiffTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='C', email='pat@acme.com')
        self.job = JobService.create_job(name='Deliv Diff Job', contact=self.contact)
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-DD-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        self.da = Deliverable.objects.create(
            job=self.job, description='Panel A', qty_ordered=Decimal('5'),
            units='ea', sort_order=10)
        self.db = Deliverable.objects.create(
            job=self.job, description='Panel B', qty_ordered=Decimal('3'),
            units='ea', sort_order=20)
        _advance_job_to_on_hold(self.job)
        # create snapshots the prior agreement (here the estimate) — baseline = A, B.
        self.co = ChangeOrderService.create(job_id=self.job.pk)

    def _kinds(self):
        return [(r['kind'], r['description'])
                for r in ChangeOrderService.compose_deliverable_diff(self.co)]

    def test_no_changes_all_unchanged(self):
        self.assertEqual(
            self._kinds(),
            [('unchanged', 'Panel A'), ('unchanged', 'Panel B')])

    def test_changed_qty_emits_changed_and_orig(self):
        self.da.qty_ordered = Decimal('10')
        self.da.save()
        kinds = self._kinds()
        self.assertEqual(kinds[0], ('changed', 'Panel A'))
        self.assertEqual(kinds[1], ('changed-orig', 'Panel A'))
        self.assertIn(('unchanged', 'Panel B'), kinds)

    def test_added_deliverable(self):
        Deliverable.objects.create(
            job=self.job, description='Panel C', qty_ordered=Decimal('1'),
            units='ea', sort_order=30)
        self.assertIn(('added', 'Panel C'), self._kinds())

    def test_removed_deliverable(self):
        self.db.delete()
        self.assertIn(('removed', 'Panel B'), self._kinds())

    def test_qty_is_stringified(self):
        rows = ChangeOrderService.compose_deliverable_diff(self.co)
        self.assertIsInstance(rows[0]['qty'], str)
