from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep


class BackfillShiftsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='backfill_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.day = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=2)
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.day, end_time=self.day + timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.day + timedelta(hours=2),
                            end_time=self.day + timedelta(hours=4))

    def test_creates_enclosing_shift_for_day(self):
        call_command('backfill_shifts')
        shifts = Shift.objects.filter(user=self.user)
        self.assertEqual(shifts.count(), 1)
        s = shifts.first()
        self.assertLessEqual(s.start_time, self.day)
        self.assertGreaterEqual(s.end_time, self.day + timedelta(hours=4))

    def test_idempotent(self):
        call_command('backfill_shifts')
        call_command('backfill_shifts')
        self.assertEqual(Shift.objects.filter(user=self.user).count(), 1)
