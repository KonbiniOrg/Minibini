"""
Tests for the mark_change_orders_expired management command.

Mirrors tests/test_mark_estimates_expired.py patterns.
"""
from datetime import timedelta

from django.utils import timezone

from apps.core.models import HistoryEntry
from apps.deliverables.models import Deliverable
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate
from apps.jobs.models import Job
from tests.base import FixtureTestCase


def _advance_job_to_on_hold(job):
    """Advance a draft job through submitted -> approved -> on_hold."""
    job.status = Job.STATUS_SUBMITTED
    job.save()
    job.status = Job.STATUS_APPROVED
    job.save()
    job.status = Job.STATUS_ON_HOLD
    job.save()
    job.refresh_from_db()


def _make_accepted_estimate(job, number='EST-MCO-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _make_open_co_past_due(job, est, *, days_overdue=1):
    """Create an open ChangeOrder with an expiration_date in the past.

    Bypasses the normal draft->open transition so we can set a past
    expiration_date directly (the service would compute a future one).
    Also adds a line item so full_clean() is happy if invoked from open.
    """
    co = ChangeOrder.objects.create(job=job, estimate=est)
    ChangeOrderLineItem.objects.create(
        change_order=co,
        action=ChangeOrderLineItem.ACTION_ADD,
        description='Extra scope',
        qty=1,
        price=100,
        line_number=1,
    )
    past = timezone.now() - timedelta(days=days_overdue)
    # Bypass Model.save() business logic to force open + past expiration_date
    ChangeOrder.objects.filter(pk=co.pk).update(
        status=ChangeOrder.STATUS_OPEN,
        sent_date=past - timedelta(days=5),
        expiration_date=past,
    )
    co.refresh_from_db()
    return co


class MarkChangeOrdersExpiredCommandTests(FixtureTestCase):
    """mark_change_orders_expired expires open COs past their expiration_date."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        # A deliverable is needed for snapshot side-effects on the service
        Deliverable.objects.create(
            job=self.job, description='Panel', qty_ordered=1, units='ea', sort_order=10,
        )
        _advance_job_to_on_hold(self.job)

    def _run_command(self):
        from apps.estimates.management.commands.mark_change_orders_expired import Command
        return Command().run()

    # ------------------------------------------------------------------
    # Core: past-due open CO is expired
    # ------------------------------------------------------------------

    def test_past_due_co_status_becomes_expired(self):
        co = _make_open_co_past_due(self.job, self.est)
        self._run_command()
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_EXPIRED)

    def test_past_due_co_counted_in_expired(self):
        _make_open_co_past_due(self.job, self.est)
        result = self._run_command()
        self.assertEqual(result['expired'], 1)

    def test_past_due_co_writes_system_history_entry(self):
        co = _make_open_co_past_due(self.job, self.est)
        before = HistoryEntry.objects.filter(
            object_type='changeorder', object_id=co.pk,
        ).count()
        self._run_command()
        after = HistoryEntry.objects.filter(
            object_type='changeorder', object_id=co.pk,
        ).count()
        self.assertGreater(after, before)

    def test_history_entry_has_correct_status_transition(self):
        co = _make_open_co_past_due(self.job, self.est)
        self._run_command()
        entry = HistoryEntry.objects.filter(
            object_type='changeorder', object_id=co.pk,
        ).order_by('-id').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.changes['status']['old'], ChangeOrder.STATUS_OPEN)
        self.assertEqual(entry.changes['status']['new'], ChangeOrder.STATUS_EXPIRED)

    def test_history_entry_action_includes_validity_days(self):
        """_action should say 'Auto-expired (valid N days)' when sent_date is set."""
        co = _make_open_co_past_due(self.job, self.est, days_overdue=1)
        self._run_command()
        entry = HistoryEntry.objects.filter(
            object_type='changeorder', object_id=co.pk,
        ).order_by('-id').first()
        self.assertIn('Auto-expired', entry.changes['_action'])

    def test_history_entry_user_is_system(self):
        co = _make_open_co_past_due(self.job, self.est)
        self._run_command()
        entry = HistoryEntry.objects.filter(
            object_type='changeorder', object_id=co.pk,
        ).order_by('-id').first()
        self.assertEqual(entry.user.username, 'system')

    # ------------------------------------------------------------------
    # Skipped: open CO with null expiration_date is not expired
    # ------------------------------------------------------------------

    def test_open_co_without_expiry_skipped(self):
        # Create a CO with status=open but expiration_date=None (update directly)
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        ChangeOrderLineItem.objects.create(
            change_order=co,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Item',
            qty=1,
            price=50,
            line_number=1,
        )
        ChangeOrder.objects.filter(pk=co.pk).update(
            status=ChangeOrder.STATUS_OPEN,
            sent_date=timezone.now() - timedelta(days=10),
            expiration_date=None,
        )
        result = self._run_command()
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_OPEN)
        self.assertGreaterEqual(result['skipped_no_expiry'], 1)

    # ------------------------------------------------------------------
    # Draft CO is untouched
    # ------------------------------------------------------------------

    def test_draft_co_is_untouched(self):
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        self.assertEqual(co.status, ChangeOrder.STATUS_DRAFT)
        self._run_command()
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_DRAFT)

    def test_draft_co_not_counted_as_expired(self):
        ChangeOrder.objects.create(job=self.job, estimate=self.est)
        result = self._run_command()
        self.assertEqual(result['expired'], 0)

    # ------------------------------------------------------------------
    # No errors on a clean run
    # ------------------------------------------------------------------

    def test_no_errors_on_clean_run(self):
        _make_open_co_past_due(self.job, self.est)
        result = self._run_command()
        self.assertEqual(result['errors'], [])

    # ------------------------------------------------------------------
    # Multiple COs: only past-due ones are expired
    # ------------------------------------------------------------------

    def test_future_expiry_co_not_expired(self):
        """A CO whose expiration_date is in the future should not be expired."""
        co = ChangeOrder.objects.create(job=self.job, estimate=self.est)
        ChangeOrderLineItem.objects.create(
            change_order=co,
            action=ChangeOrderLineItem.ACTION_ADD,
            description='Future item',
            qty=1,
            price=75,
            line_number=1,
        )
        future = timezone.now() + timedelta(days=10)
        ChangeOrder.objects.filter(pk=co.pk).update(
            status=ChangeOrder.STATUS_OPEN,
            sent_date=timezone.now() - timedelta(days=5),
            expiration_date=future,
        )
        result = self._run_command()
        co.refresh_from_db()
        self.assertEqual(co.status, ChangeOrder.STATUS_OPEN)
        self.assertEqual(result['expired'], 0)
