"""A blep's end_time may not be in the future (you can't have worked ahead of
now), with a 30s clock-skew buffer for mismatched device clocks.
See docs/plans/2026-05-24-blep-handling-changes.md §1.
"""
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError

from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import BlepService


class NoFutureEndTimeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.user = User.objects.create_user(username='nofuture_worker', password='x')
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )

    def _active_blep(self):
        return Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=5),
        )

    def test_update_rejects_future_end_time(self):
        blep = self._active_blep()
        future = timezone.now() + timedelta(minutes=5)
        with self.assertRaises(ValidationError):
            BlepService.update(blep, self.user, end_time=future)

    def test_update_allows_end_within_skew_buffer(self):
        blep = self._active_blep()
        near = timezone.now() + timedelta(seconds=20)
        updated = BlepService.update(blep, self.user, end_time=near)
        self.assertIsNotNone(updated.end_time)

    def test_update_active_to_past_end_closes_it(self):
        blep = self._active_blep()
        end = timezone.now() - timedelta(minutes=1)
        updated = BlepService.update(blep, self.user, end_time=end)
        self.assertEqual(updated.end_time, end)

    def test_create_historical_rejects_future_end_time(self):
        start = timezone.now() - timedelta(minutes=10)
        future = timezone.now() + timedelta(minutes=5)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, self.task, start, future)
