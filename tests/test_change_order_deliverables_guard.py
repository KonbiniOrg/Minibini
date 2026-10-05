"""A change order cannot leave draft (mark-open or send) while its Job has
zero Deliverables — the CO sibling of the estimate's mark_open guard
(tests/test_estimate_mark_open_deliverables_guard.py). Removing the last
deliverable is a legitimate *diff* (has_sendable_changes is true), but the
result would be an agreed scope that delivers nothing."""
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import Estimate, ChangeOrder, ChangeOrderLineItem
from apps.jobs.models import Job
from apps.jobs.services import JobService
from tests.base import FixtureTestCase


def _advance_job_to_on_hold(job):
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


class ChangeOrderDeliverablesGuardTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Guard Job', contact=contact)
        Estimate.objects.create(
            job=self.job, estimate_number='EST-COG-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Thing', qty_ordered=Decimal('1'),
            units='ea', sort_order=10)
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        # A line-item change so the CO is otherwise sendable on its own.
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1, accounting_category_id=901)

    def test_mark_open_blocked_when_job_has_no_deliverables(self):
        self.deliverable.delete()
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderService.mark_open(self.co.pk)
        self.assertIn('no deliverables', str(ctx.exception))
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_DRAFT)

    def test_mark_open_succeeds_with_a_deliverable(self):
        ChangeOrderService.mark_open(self.co.pk)
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_OPEN)

    def test_removing_the_last_deliverable_is_a_diff_but_still_refused(self):
        # has_sendable_changes is satisfied by the removal alone…
        ChangeOrderLineItem.objects.filter(change_order=self.co).delete()
        self.deliverable.delete()
        self.assertTrue(ChangeOrderService.has_sendable_changes(self.co))
        # …but the CO still can't go out.
        with self.assertRaises(ValidationError):
            ChangeOrderService.mark_open(self.co.pk)
