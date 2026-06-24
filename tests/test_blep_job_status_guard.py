"""Bug 2: creating a Blep on a Task is rejected when the Job's status
disallows it. Live start_work allows APPROVED/IN_PROGRESS only; backfilled
create_historical also allows WORK_COMPLETE."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task
from apps.jobs.services import BlepService, TaskLifecycleService


def _job_at(contact, *statuses):
    job = Job.objects.create(
        job_number=f'J-GUARD-{timezone.now().timestamp()}',
        contact=contact, status=Job.STATUS_DRAFT,
    )
    for s in statuses:
        job.status = s
        job.save()
    return job


class StartWorkJobStatusGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact
        self.user = User.objects.get(username='admin')

    def _task(self, job):
        return Task.objects.create(name='T', job=job, service_price_id=1)

    def test_start_work_rejected_on_draft_job(self):
        task = self._task(_job_at(self.contact))
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(task.pk, self.user)

    def test_start_work_rejected_on_submitted_job(self):
        task = self._task(_job_at(self.contact, Job.STATUS_SUBMITTED))
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(task.pk, self.user)

    def test_start_work_rejected_on_work_complete_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE)
        task = self._task(job)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(task.pk, self.user)

    def test_start_work_allowed_on_approved_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        task = self._task(job)
        result = TaskLifecycleService.start_work(task.pk, self.user)
        self.assertIn('blep', result)

    def test_start_work_allowed_on_in_progress_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS)
        task = self._task(job)
        result = TaskLifecycleService.start_work(task.pk, self.user)
        self.assertIn('blep', result)

    def test_start_work_rejected_on_on_hold_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_ON_HOLD)
        task = self._task(job)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(task.pk, self.user)

    def test_start_work_rejected_on_cancelled_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_CANCELLED)
        task = self._task(job)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(task.pk, self.user)


class CreateHistoricalJobStatusGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact
        self.user = User.objects.get(username='admin')
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=3),
            end_time=now + timedelta(days=1),
        )

    def _task(self, job):
        return Task.objects.create(name='T', job=job, service_price_id=1)

    def _times(self):
        now = timezone.now()
        return now - timedelta(hours=2), now - timedelta(hours=1)

    def test_rejected_on_draft_job(self):
        task = self._task(_job_at(self.contact))
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, task, start, end)

    def test_rejected_on_submitted_job(self):
        task = self._task(_job_at(self.contact, Job.STATUS_SUBMITTED))
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, task, start, end)

    def test_allowed_on_approved_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED)
        task = self._task(job)
        start, end = self._times()
        self.assertIsNotNone(
            BlepService.create_historical(self.user, task, start, end)
        )

    def test_allowed_on_in_progress_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS)
        task = self._task(job)
        start, end = self._times()
        self.assertIsNotNone(
            BlepService.create_historical(self.user, task, start, end)
        )

    def test_allowed_on_work_complete_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE)
        task = self._task(job)
        start, end = self._times()
        self.assertIsNotNone(
            BlepService.create_historical(self.user, task, start, end)
        )

    def test_rejected_on_completed_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE,
                      Job.STATUS_COMPLETED)
        task = self._task(job)
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, task, start, end)

    def test_rejected_on_rejected_job(self):
        task = self._task(_job_at(self.contact, Job.STATUS_REJECTED))
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, task, start, end)

    def test_allowed_on_cancelled_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_CANCELLED)
        task = self._task(job)
        start, end = self._times()
        self.assertIsNotNone(
            BlepService.create_historical(self.user, task, start, end)
        )

    def test_rejected_on_on_hold_job(self):
        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_ON_HOLD)
        task = self._task(job)
        start, end = self._times()
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, task, start, end)


class ActualQtyCancelledJobTest(BaseTestCase):
    """1c: actual_qty can be set on a task whose job is cancelled.

    update_task has no job-status gate, so no code change is needed — this
    test just confirms the invariant stays true."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact

    def _task(self, job):
        from apps.jobs.models import ServicePrice
        scheme = ServicePrice.objects.first()
        return Task.objects.create(name='T', job=job, service_price=scheme)

    def test_actual_qty_settable_on_cancelled_job(self):
        from decimal import Decimal
        from apps.jobs.services import TaskService

        job = _job_at(self.contact, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                      Job.STATUS_CANCELLED)
        task = self._task(job)
        updated = TaskService.update_task(task.pk, actual_qty=Decimal('3.5'))
        self.assertEqual(updated.actual_qty, Decimal('3.5'))
