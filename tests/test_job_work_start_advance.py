"""Bug 1: starting work on a Job (a Blep begins, or a Task is completed)
auto-advances an APPROVED Job to IN_PROGRESS."""

from datetime import timedelta

from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task
from apps.jobs.services import BlepService, JobService, TaskLifecycleService


def _job_at(contact, *statuses):
    job = Job.objects.create(
        job_number=f'J-WSA-{timezone.now().timestamp()}',
        contact=contact, status=Job.STATUS_DRAFT,
    )
    for s in statuses:
        job.status = s
        job.save()
    return job


class MarkWorkStartedTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact

    def test_advances_approved_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_noop_on_draft_job(self):
        job = _job_at(self.contact)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_DRAFT)

    def test_noop_on_submitted_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_SUBMITTED)

    def test_noop_on_in_progress_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS)
        JobService.mark_work_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)


class WorkStartAdvancesJobTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact
        self.user = User.objects.get(username='admin')
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )

    def test_start_work_advances_approved_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        task = Task.objects.create(name='T', job=job, service_price_id=1)
        TaskLifecycleService.start_work(task.pk, self.user)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_complete_task_advances_approved_job_with_others_remaining(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        t1 = Task.objects.create(name='T1', job=job, service_price_id=1)
        Task.objects.create(name='T2', job=job, service_price_id=1)
        now = timezone.now()
        BlepService._create(t1, self.user, start_time=now - timedelta(hours=1), end_time=now)
        TaskLifecycleService.complete_task(t1.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_create_historical_advances_approved_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        task = Task.objects.create(name='T', job=job, service_price_id=1)
        now = timezone.now()
        BlepService.create_historical(
            self.user, task, now - timedelta(hours=2), now - timedelta(hours=1),
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_create_historical_on_work_complete_job_stays_work_complete(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE)
        task = Task.objects.create(name='T', job=job, service_price_id=1)
        now = timezone.now()
        BlepService.create_historical(
            self.user, task, now - timedelta(hours=2), now - timedelta(hours=1),
        )
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)
