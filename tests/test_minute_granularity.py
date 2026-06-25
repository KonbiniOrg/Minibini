from datetime import datetime, timedelta, timezone as tz
from django.utils import timezone
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.core.timeutils import floor_to_minute
from apps.jobs.models import Job, Task, Blep


class MinuteGranularityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='mg_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_item_id=1)

    def test_floor_helper(self):
        d = datetime(2026, 5, 31, 16, 30, 45, 123456, tzinfo=tz.utc)
        f = floor_to_minute(d)
        self.assertEqual((f.second, f.microsecond, f.minute), (0, 0, 30))
        self.assertIsNone(floor_to_minute(None))

    def test_shift_save_floors(self):
        t = timezone.now().replace(second=45, microsecond=123456)
        s = Shift.objects.create(user=self.user, start_time=t, end_time=t + timedelta(hours=1))
        s.refresh_from_db()
        self.assertEqual((s.start_time.second, s.start_time.microsecond), (0, 0))
        self.assertEqual((s.end_time.second, s.end_time.microsecond), (0, 0))

    def test_blep_save_floors(self):
        t = timezone.now().replace(second=33, microsecond=99)
        b = Blep.objects.create(task=self.task, user=self.user, start_time=t, end_time=t + timedelta(hours=1))
        b.refresh_from_db()
        self.assertEqual((b.start_time.second, b.start_time.microsecond), (0, 0))
        self.assertEqual((b.end_time.second, b.end_time.microsecond), (0, 0))

    def test_clockout_closes_blep_via_save_and_floors_end(self):
        # If _close_open still used QuerySet.update(), end_time would keep its seconds.
        odd = timezone.now().replace(second=37, microsecond=500000)
        ShiftService.clock_in(self.user, start_time=odd - timedelta(hours=1))
        b = Blep.objects.create(task=self.task, user=self.user, start_time=odd - timedelta(minutes=30))
        ShiftService.clock_out(self.user, end_time=odd)
        b.refresh_from_db()
        self.assertIsNotNone(b.end_time)
        self.assertEqual((b.end_time.second, b.end_time.microsecond), (0, 0))
