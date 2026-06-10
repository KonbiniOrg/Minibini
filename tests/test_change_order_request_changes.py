"""Tests for ChangeOrderService.request_changes — the CO parallel of
EstimateService.request_changes (customer-initiated revision from the portal).

Supersedes the open CO, seeds a fresh draft carrying the deltas, leaves the job
on_hold, records the customer comment, and snapshots the superseded proposal.
"""
from decimal import Decimal
from apps.core.models import JobHistory

from django.core.exceptions import ValidationError

from tests.base import FixtureTestCase
from apps.core.models import HistoryEntry
from apps.deliverables.models import Deliverable, DeliverableSnapshot
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    Estimate, ChangeOrder, ChangeOrderLineItem,
)
from apps.jobs.models import Job


def _advance_job_to_on_hold(job):
    job.status = Job.STATUS_SUBMITTED; job.save()
    job.status = Job.STATUS_APPROVED; job.save()
    job.status = Job.STATUS_ON_HOLD; job.save()
    job.refresh_from_db()


class ChangeOrderRequestChangesTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-RC-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=self.job, description='Thing', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra', qty=Decimal('1'), price=Decimal('200'),
            line_number=1,
        )
        ChangeOrderService.mark_open(self.co.pk)
        self.co.refresh_from_db()

    def _actor(self, reason='make it cheaper'):
        return {'contact_id': None, 'email': 'pat@acme.com', 'reason': reason}

    def test_returns_new_draft_co(self):
        new_co = ChangeOrderService.request_changes(self.co.pk, self._actor())
        self.assertEqual(new_co.status, ChangeOrder.STATUS_DRAFT)
        self.assertEqual(new_co.parent, self.co)
        self.assertNotEqual(new_co.pk, self.co.pk)

    def test_supersedes_the_open_co(self):
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        self.co.refresh_from_db()
        self.assertEqual(self.co.status, ChangeOrder.STATUS_SUPERSEDED)

    def test_job_stays_on_hold(self):
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_ON_HOLD)

    def test_carries_line_items_to_new_draft(self):
        new_co = ChangeOrderService.request_changes(self.co.pk, self._actor())
        descriptions = list(
            ChangeOrderLineItem.objects.filter(change_order=new_co)
            .values_list('description', flat=True))
        self.assertEqual(descriptions, ['Extra'])

    def test_records_customer_action_history(self):
        ChangeOrderService.request_changes(
            self.co.pk, self._actor(reason='cut the price'))
        entry = JobHistory.objects.filter(
            object_type='changeorder', object_id=self.co.pk,
            entry_type='action', user__isnull=True,
        ).order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'cut the price')
        self.assertEqual(
            entry.changes.get('_action'), 'Changes requested via customer link')

    def test_snapshots_the_superseded_proposal(self):
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        snaps = list(DeliverableSnapshot.objects.filter(change_order=self.co))
        self.assertGreaterEqual(len(snaps), 1)

    def test_new_draft_blocks_off_hold(self):
        """The seeded draft keeps the on_hold exit guard armed."""
        from apps.jobs.services import JobService
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        with self.assertRaises(ValidationError):
            JobService.update_job(self.job.pk, status=Job.STATUS_IN_PROGRESS)

    def test_request_changes_history_uses_changeorder_object_type(self):
        ChangeOrderService.request_changes(self.co.pk, self._actor())
        entries = JobHistory.objects.filter(object_id=self.co.pk, entry_type='action')
        self.assertTrue(entries.exists())
        self.assertFalse(entries.filter(object_type='change_order').exists())
        self.assertTrue(entries.filter(object_type='changeorder').exists())
