from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep, RateScheme
from apps.jobs.services import BlepService, TaskLifecycleService


class BlepShiftIntegrationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='bsi_u', password='x')
        self.job = Job.objects.first()
        # Bypass transition validation — start_work/create_historical require an
        # active job; the workflow path to get there is irrelevant to this test.
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_IN_PROGRESS)
        self.job.refresh_from_db()
        self.task = Task(name='T', job=self.job)
        self.task.stamp_from_scheme(RateScheme.objects.get(pk=1))
        self.task.save()

    def test_live_start_auto_clocks_in(self):
        self.assertIsNone(ShiftService.open_shift_for(self.user))
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.assertIsNotNone(ShiftService.open_shift_for(self.user))

    def test_create_historical_blep_requires_enclosing_shift(self):
        now = timezone.now().replace(microsecond=0)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(
                actor=self.user, task=self.task,
                start_time=now - timedelta(hours=2),
                end_time=now - timedelta(hours=1),
                target_user=self.user,
            )

    def test_create_historical_blep_inside_shift_ok(self):
        now = timezone.now().replace(microsecond=0)
        Shift.objects.create(user=self.user, start_time=now - timedelta(hours=3),
                             end_time=now - timedelta(minutes=30))
        blep = BlepService.create_historical(
            actor=self.user, task=self.task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            target_user=self.user,
        )
        self.assertIsNotNone(blep.pk)
