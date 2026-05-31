"""Explicit logout closes the user's active blep(s). Session expiry does NOT
(there's no server-side expiry hook) — so the close lives only in the logout
endpoint. See docs/designs/jobs-tasks-and-worksheets.md §5.
"""
from datetime import timedelta

from rest_framework.test import APIClient
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, Task, Blep


class LogoutClosesBlepsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.other = User.objects.create_user(username='logout_other', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)

    def test_logout_closes_users_open_blep(self):
        # Over-minimum so logout CLOSES it (a sub-minimum blep is cancelled).
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/auth/logout/')
        self.assertEqual(resp.status_code, 200)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_logout_leaves_another_users_blep_open(self):
        other_blep = Blep.objects.create(
            task=self.task, user=self.other, start_time=timezone.now(),
        )
        self.client.force_authenticate(user=self.user)
        self.client.post('/api/auth/logout/')
        other_blep.refresh_from_db()
        self.assertIsNone(other_blep.end_time)

    def test_logout_with_no_open_blep_succeeds(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/auth/logout/')
        self.assertEqual(resp.status_code, 200)
