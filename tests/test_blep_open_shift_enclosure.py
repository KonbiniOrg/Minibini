"""An ongoing (open, end_time=None) shift must enclose bleps that fall within it.

Regression: editing a blep within an ongoing shift was rejected with "No shift
encloses the edited time" because enclosing_shift_for_blep only considered
closed shifts (end_time__isnull=False). An ongoing shift is still running, so it
encloses any blep starting at/after its start (its end is effectively unbounded;
a blep's end can't be in the future). Mirrors the open-shift handling already in
unenclosed_bleps_for_shift.
"""
from datetime import timedelta
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep
from apps.core.time_integrity import enclosing_shift_for_blep


class OpenShiftEnclosesBlepTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='blep_open_u', password='x')
        self.user.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, service_item_id=1)

    def test_open_shift_encloses_blep_pure(self):
        now = timezone.now()
        s = Shift.objects.create(user=self.user,
                                 start_time=now - timedelta(hours=3),
                                 end_time=None)
        # Blep entirely after the shift's start, ending in the past -> the
        # ongoing shift encloses it.
        self.assertEqual(
            enclosing_shift_for_blep(self.user, now - timedelta(hours=2),
                                     now - timedelta(hours=1)),
            s)
        # A blep starting before the shift's start is NOT enclosed.
        self.assertIsNone(
            enclosing_shift_for_blep(self.user, now - timedelta(hours=4),
                                     now - timedelta(hours=1)))

    def test_edit_blep_backward_within_ongoing_shift(self):
        now = timezone.now()
        Shift.objects.create(user=self.user,
                             start_time=now - timedelta(hours=3),
                             end_time=None)
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=1),
            end_time=now - timedelta(minutes=30))
        # Extend the start backward, still inside the ongoing shift.
        new_start = (now - timedelta(hours=2)).isoformat()
        resp = self.client.patch(f'/api/bleps/{blep.blep_id}/',
                                 {'start_time': new_start}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        blep.refresh_from_db()
        self.assertEqual(blep.start_time.replace(second=0, microsecond=0),
                         (now - timedelta(hours=2)).replace(second=0, microsecond=0))
