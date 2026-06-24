"""Sub-minimum bleps are accidental starts: closing one (via any path) cancels
it with full cancel_work undo rather than persisting a closed blep.

Enforced at BlepService._close_open, so stop_work, ShiftService.clock_out, and
logout/deactivation all share the behavior.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.api.users.services import UserAdminService
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import BlepService, TaskLifecycleService


class BlepMinimumCancelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(name='T', job=self.job, service_price_id=1)
        self.user = User.objects.create_user(username='min_cancel_worker', password='x')
        self.now = timezone.now()
        # Open shift starting well in the past: clock_out will close it at `now`,
        # so a KEPT (over-minimum) blep started minutes ago is enclosed.
        self.shift = Shift.objects.create(
            user=self.user,
            start_time=self.now - timedelta(days=1),
        )

    def _open_blep(self, minutes_ago):
        """Create an open blep started `minutes_ago` minutes ago and put the
        task into the first/only-activity state (in_progress)."""
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=self.now - timedelta(minutes=minutes_ago),
        )
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        return blep

    # ── clock_out ────────────────────────────────────────────────
    def test_clock_out_cancels_sub_minimum_blep(self):
        # start_time == now → 0 whole minutes < 1 → cancelled (deleted).
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        ShiftService.clock_out(self.user)
        self.assertFalse(Blep.objects.filter(pk=blep.pk).exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_PENDING)

    def test_clock_out_keeps_over_minimum_blep(self):
        blep = self._open_blep(minutes_ago=10)
        ShiftService.clock_out(self.user)
        self.assertTrue(Blep.objects.filter(pk=blep.pk).exists())
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    # ── stop_work ────────────────────────────────────────────────
    def test_stop_work_cancels_sub_minimum_blep(self):
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        TaskLifecycleService.stop_work(self.task.pk, self.user)
        self.assertFalse(Blep.objects.filter(pk=blep.pk).exists())
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_PENDING)

    def test_stop_work_keeps_over_minimum_blep(self):
        blep = self._open_blep(minutes_ago=10)
        TaskLifecycleService.stop_work(self.task.pk, self.user)
        self.assertTrue(Blep.objects.filter(pk=blep.pk).exists())
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    # ── cancel_work guard preserved ──────────────────────────────
    def test_cancel_work_rejects_over_minimum_blep(self):
        self._open_blep(minutes_ago=10)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_work(self.task.pk, self.user)


class CloseOpenAutocommitTest(TransactionTestCase):
    """The logout and deactivate paths call BlepService.close_user_open_bleps
    with NO enclosing transaction (autocommit). Closing a SUB-MINIMUM open blep
    there routes through _cancel_blep, whose select_for_update() requires a
    transaction. _close_open must therefore be self-atomic, or these 500.

    These use TransactionTestCase (not TestCase) so the test body runs under
    real autocommit — a TestCase would wrap it in a transaction and mask the
    bug.
    """
    # TransactionTestCase doesn't inherit BaseTestCase's fixtures attr; declare
    # the same fixture so Job/ServicePrice/config rows exist.
    fixtures = ['unit_test_data.json']

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(
            name='T', job=self.job, service_price_id=1
        )

    def _open_sub_minute_blep(self, user):
        """An OPEN sub-minute blep on the in_progress task (first activity)."""
        blep = Blep.objects.create(
            task=self.task, user=user, start_time=timezone.now(),
        )
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_IN_PROGRESS
        )
        return blep

    def test_logout_cancels_sub_minute_blep_without_crashing(self):
        user = User.objects.create_user(
            username='logout_autocommit', password='x'
        )
        blep = self._open_sub_minute_blep(user)
        client = APIClient()
        client.force_authenticate(user=user)
        # Without the self-atomic fix this 500s (TransactionManagementError).
        resp = client.post('/api/auth/logout/')
        self.assertEqual(resp.status_code, 200)
        # Sub-minute = accidental start → cancelled (deleted).
        self.assertFalse(Blep.objects.filter(pk=blep.pk).exists())

    def test_deactivate_cancels_sub_minute_blep_without_crashing(self):
        actor = User.objects.create_user(
            username='deactivate_actor', password='x', is_superuser=True
        )
        target = User.objects.create_user(
            username='deactivate_target', password='x'
        )
        blep = self._open_sub_minute_blep(target)
        # Calls close_user_open_bleps under autocommit; without the fix it 500s.
        UserAdminService.deactivate_user(actor, target)
        self.assertFalse(Blep.objects.filter(pk=blep.pk).exists())
        target.refresh_from_db()
        self.assertFalse(target.is_active)
