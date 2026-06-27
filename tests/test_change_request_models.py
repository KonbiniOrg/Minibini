from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest
from apps.jobs.models import Job, Task, Blep, BlepChangeRequest


class ChangeRequestModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='cr_u', password='x')
        self.now = timezone.now().replace(microsecond=0)

    def test_shift_change_request_defaults_pending(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='forgot to clock out',
        )
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)
        self.assertIsNone(r.shift)  # create-type
        self.assertEqual(ShiftChangeRequest._meta.db_table, 'shift_change_requests')

    def test_blep_change_request_carries_task(self):
        job = Job.objects.first()
        task = Task.objects.create(name='T', job=job, rate_scheme_id=1)
        r = BlepChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='wrong end time', task=task,
        )
        self.assertEqual(r.task, task)
        self.assertEqual(BlepChangeRequest._meta.db_table, 'blep_change_requests')
