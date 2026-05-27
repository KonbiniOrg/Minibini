"""The Stop→Cancel threshold must reach the client. It rides on the two
authenticated payloads the relevant UI already fetches: the current-blep band
and the task-detail page. See docs/plans/2026-05-24-blep-handling-changes.md §2.
"""
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task
from apps.core.models import User
from apps.jobs.services import TaskLifecycleService


class BlepMinSecondsPayloadTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(job=self.job, name='T', rate_scheme_id=1)

    def test_current_blep_includes_min_seconds(self):
        TaskLifecycleService.start_work(self.task.pk, self.user)
        body = self.client.get('/api/bleps/current/').json()
        self.assertIsNotNone(body)
        self.assertEqual(int(body['blep_minimum_seconds']), 60)

    def test_task_detail_includes_min_seconds(self):
        body = self.client.get(f'/api/tasks/{self.task.pk}/').json()
        self.assertEqual(int(body['blep_minimum_seconds']), 60)
