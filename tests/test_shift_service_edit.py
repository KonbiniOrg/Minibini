from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep


class ShiftEditTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='edit_u', password='x')
        self.mgr = User.objects.create_user(username='edit_mgr', password='x', is_superuser=True)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_item_id=1)
        # Floor to the whole minute: Shift/Blep save() now stores minute-granular
        # times, so test expectations derived from self.now must land on a minute
        # boundary to compare equal to the stored values.
        self.now = timezone.now().replace(second=0, microsecond=0)

    def _recent_shift(self):
        return Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=3),
                                    end_time=self.now - timedelta(hours=1))

    def test_owner_edits_recent_shift(self):
        s = self._recent_shift()
        ShiftService.update(s, actor=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=1))
        s.refresh_from_db()
        self.assertEqual(s.start_time, self.now - timedelta(hours=4))

    def test_owner_cannot_edit_old_shift(self):
        old = Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=40),
                                   end_time=self.now - timedelta(hours=38))
        with self.assertRaises(ValidationError):
            ShiftService.update(old, actor=self.user,
                                start_time=self.now - timedelta(hours=41),
                                end_time=self.now - timedelta(hours=38))

    def test_manager_edits_old_shift(self):
        old = Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=40),
                                   end_time=self.now - timedelta(hours=38))
        ShiftService.update(old, actor=self.mgr,
                            start_time=self.now - timedelta(hours=41),
                            end_time=self.now - timedelta(hours=38))
        old.refresh_from_db()
        self.assertEqual(old.start_time, self.now - timedelta(hours=41))

    def test_edit_that_orphans_blep_blocked(self):
        s = self._recent_shift()
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=2, minutes=30),
                            end_time=self.now - timedelta(hours=2))
        with self.assertRaises(ValidationError):
            ShiftService.update(s, actor=self.user,
                                start_time=self.now - timedelta(minutes=90),
                                end_time=self.now - timedelta(hours=1))
