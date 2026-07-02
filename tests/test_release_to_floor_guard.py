"""Release-to-floor guard: a job with no Tasks cannot be released to the floor.

"Release to floor" is the user PATCH of an approved job to in_progress (the
JobHeader button). A job with no Tasks has no work to release, so the API rejects
it (400). The guard lives at the user-PATCH boundary, not in JobService — the
completion cascade and blep-start legitimately walk through in_progress internally.
"""
from decimal import Decimal
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, Task


class ReleaseToFloorGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Job.objects.first().contact

    def _approved_job(self, *, with_task):
        job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-RTF-1',
        )
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            job.status = s
            job.save()
        if with_task:
            Task.objects.create(job=job, name='Cut', rate_scheme_id=1)
        return job

    def test_release_to_floor_blocked_without_tasks(self):
        job = self._approved_job(with_task=False)
        resp = self.client.patch(
            f'/api/jobs/{job.pk}/', {'status': 'in_progress'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('task', str(resp.data).lower())
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)  # not released

    def test_release_to_floor_allowed_with_task(self):
        job = self._approved_job(with_task=True)
        resp = self.client.patch(
            f'/api/jobs/{job.pk}/', {'status': 'in_progress'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
