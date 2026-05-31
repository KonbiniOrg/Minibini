from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep


class ShiftClockTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='clock_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)

    def test_clock_in_opens_shift(self):
        s = ShiftService.clock_in(self.user)
        self.assertTrue(s.is_open)

    def test_clock_in_twice_blocked(self):
        ShiftService.clock_in(self.user)
        with self.assertRaises(ValidationError):
            ShiftService.clock_in(self.user)

    def test_clock_out_closes_shift_and_open_bleps(self):
        # Clock in 30 min ago so the shift encloses an over-minimum blep that
        # clock_out will CLOSE (sub-minimum bleps are cancelled instead).
        s = ShiftService.clock_in(self.user, start_time=timezone.now() - timedelta(minutes=30))
        blep = Blep.objects.create(task=self.task, user=self.user,
                                   start_time=timezone.now() - timedelta(minutes=20))
        ShiftService.clock_out(self.user)
        s.refresh_from_db(); blep.refresh_from_db()
        self.assertIsNotNone(s.end_time)
        self.assertIsNotNone(blep.end_time)

    def test_clock_out_without_open_shift_blocked(self):
        with self.assertRaises(ValidationError):
            ShiftService.clock_out(self.user)
