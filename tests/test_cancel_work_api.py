"""API: POST /api/tasks/{id}/cancel-work/ mirrors stop-work for the
under-the-minimum cancel path. See docs/plans/2026-05-24-blep-handling-changes.md §2.
"""
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, Blep
from apps.core.models import User


class CancelWorkAPITest(BaseTestCase):
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

    def test_cancel_work_deletes_blep_and_reverts_task(self):
        self.client.post(f'/api/tasks/{self.task.pk}/start-work/')
        resp = self.client.post(f'/api/tasks/{self.task.pk}/cancel-work/')
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        self.assertFalse(
            Blep.objects.filter(task=self.task, user=self.user).exists()
        )

    def test_cancel_work_without_open_blep_returns_400(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        resp = self.client.post(f'/api/tasks/{self.task.pk}/cancel-work/')
        self.assertEqual(resp.status_code, 400)
