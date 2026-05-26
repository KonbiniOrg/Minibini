from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User
from apps.jobs.models import Job, Task
from apps.schedule.services import ScheduleService
from tests.base import BaseTestCase


class ScheduleAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_unauthenticated_blocked(self):
        response = self.client.get('/api/schedule/')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_returns_envelope(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ('now', 'horizon_start', 'horizon_end', 'horizon_days',
                    'day_shape', 'days', 'jobs', 'workers'):
            self.assertIn(key, data)

    def test_days_param_respected(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=2')
        self.assertEqual(response.json()['horizon_days'], 2)

    def test_days_param_clamped_high(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=99')
        self.assertEqual(response.json()['horizon_days'], 14)

    def test_days_param_clamped_low(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=0')
        self.assertEqual(response.json()['horizon_days'], 1)


class ScheduleOnHoldExclusionTest(BaseTestCase):
    """Tasks on on_hold jobs must not appear in the schedule output."""

    def _make_worker(self):
        return User.objects.create_user(
            username='worker_onhold_test',
            password='pass',
            first_name='Hold',
            last_name='Worker',
        )

    def _make_job(self, contact, *statuses):
        job = Job.objects.create(
            job_number=f'JOB-SCHED-ONHOLD-{timezone.now().timestamp()}',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        for s in statuses:
            job.status = s
            job.save()
        return job

    def test_on_hold_job_task_worker_absent_from_schedule(self):
        """A worker whose only open task is on an on_hold job must not
        appear in the schedule's workers list."""
        contact = Job.objects.first().contact
        worker = self._make_worker()
        job = self._make_job(
            contact,
            Job.STATUS_SUBMITTED,
            Job.STATUS_APPROVED,
            Job.STATUS_ON_HOLD,
        )
        Task.objects.create(
            name='Hold task',
            job=job,
            assignee=worker,
            status=Task.STATUS_PENDING,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        self.assertNotIn(worker.pk, worker_ids)

    def test_in_progress_job_task_worker_present_in_schedule(self):
        """A worker with an open task on an in_progress job DOES appear."""
        contact = Job.objects.first().contact
        worker2 = User.objects.create_user(
            username='worker_inprog_test',
            password='pass',
            first_name='Inprog',
            last_name='Worker',
        )
        job = self._make_job(
            contact,
            Job.STATUS_SUBMITTED,
            Job.STATUS_APPROVED,
            Job.STATUS_IN_PROGRESS,
        )
        Task.objects.create(
            name='Active task',
            job=job,
            assignee=worker2,
            status=Task.STATUS_PENDING,
            rate_scheme_id=1,
            est_worker_time=timedelta(hours=1),
        )
        result = ScheduleService.get_schedule(now=timezone.now())
        worker_ids = [w['user']['id'] for w in result['workers']]
        self.assertIn(worker2.pk, worker_ids)
