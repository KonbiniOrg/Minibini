from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep
from apps.core.time_integrity import unenclosed_bleps_for_shift, enclosing_shift_for_blep


class TimeIntegrityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='integ_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_price_id=1)
        self.t0 = timezone.now().replace(microsecond=0) - timedelta(hours=10)

    def _blep(self, start_h, end_h):
        return Blep.objects.create(
            task=self.task, user=self.user,
            start_time=self.t0 + timedelta(hours=start_h),
            end_time=self.t0 + timedelta(hours=end_h),
        )

    def test_shift_fully_encloses_blep_no_conflict(self):
        self._blep(1, 2)
        bad = unenclosed_bleps_for_shift(self.user, self.t0, self.t0 + timedelta(hours=8))
        self.assertEqual(list(bad), [])

    def test_blep_spilling_past_shift_end_is_conflict(self):
        b = self._blep(1, 5)
        bad = unenclosed_bleps_for_shift(self.user, self.t0, self.t0 + timedelta(hours=4))
        self.assertIn(b, list(bad))

    def test_blep_orphaned_by_shrunk_shift_is_conflict(self):
        b = self._blep(1, 2)
        bad = unenclosed_bleps_for_shift(
            self.user, self.t0 + timedelta(hours=6), self.t0 + timedelta(hours=8),
            also_span=(self.t0, self.t0 + timedelta(hours=8)),
        )
        self.assertIn(b, list(bad))

    def test_enclosing_shift_found(self):
        Shift.objects.create(user=self.user, start_time=self.t0,
                             end_time=self.t0 + timedelta(hours=8))
        s = enclosing_shift_for_blep(self.user, self.t0 + timedelta(hours=1),
                                     self.t0 + timedelta(hours=2))
        self.assertIsNotNone(s)

    def test_no_enclosing_shift_returns_none(self):
        s = enclosing_shift_for_blep(self.user, self.t0 + timedelta(hours=1),
                                     self.t0 + timedelta(hours=2))
        self.assertIsNone(s)
