from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest
from apps.core.services import TimeChangeRequestService
from apps.jobs.models import Job, Task, Blep


class ChangeRequestServiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='crs_u', password='x')
        self.mgr = User.objects.create_user(username='crs_mgr', password='x', is_superuser=True)
        self.now = timezone.now().replace(microsecond=0)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)

    def test_approve_create_request_makes_shift(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user,
            requested_start=self.now - timedelta(hours=40),
            requested_end=self.now - timedelta(hours=32),
            reason='worked, forgot to clock in',
        )
        TimeChangeRequestService.approve(r, reviewer=self.mgr)
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_APPROVED)
        self.assertTrue(Shift.objects.filter(user=self.user,
                        start_time=self.now - timedelta(hours=40)).exists())

    def test_approve_blocked_when_it_orphans_blep(self):
        shift = Shift.objects.create(user=self.user,
                                     start_time=self.now - timedelta(hours=5),
                                     end_time=self.now - timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=3))
        r = ShiftChangeRequest.objects.create(
            requester=self.user, shift=shift,
            requested_start=self.now - timedelta(hours=5),
            requested_end=self.now - timedelta(hours=3, minutes=30),  # cuts off the blep
            reason='left early',
        )
        with self.assertRaises(ValidationError):
            TimeChangeRequestService.approve(r, reviewer=self.mgr)
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)  # not consumed

    def test_deny_records_reviewer_and_note(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='x')
        TimeChangeRequestService.deny(r, reviewer=self.mgr, note='insufficient detail')
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_DENIED)
        self.assertEqual(r.review_note, 'insufficient detail')

    def test_submit_flags_known_conflict(self):
        shift = Shift.objects.create(user=self.user,
                                     start_time=self.now - timedelta(hours=5),
                                     end_time=self.now - timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=3))
        r = ShiftChangeRequest(requester=self.user, shift=shift,
                               requested_start=self.now - timedelta(hours=5),
                               requested_end=self.now - timedelta(hours=3, minutes=30),
                               reason='left early')
        TimeChangeRequestService.submit(r)
        self.assertTrue(r.has_known_conflict)
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)
