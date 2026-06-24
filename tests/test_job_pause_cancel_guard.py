"""Guard: JobService.update_job rejects on_hold/cancelled transitions while
any open Blep (end_time__isnull=True) exists on the job's tasks."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Blep, Job, Task
from apps.jobs.services import JobService, TaskLifecycleService


def _make_job(contact, *statuses):
    """Create a Job and advance it through each given status in order."""
    job = Job.objects.create(
        job_number=f'J-PAUSEGUARD-{timezone.now().timestamp()}',
        contact=contact,
        status=Job.STATUS_DRAFT,
    )
    for s in statuses:
        job.status = s
        job.save()
    return job


def _make_task(job):
    return Task.objects.create(name='Guard-Test Task', job=job, service_price_id=1)


class OpenBlepBlocksOnHoldTest(BaseTestCase):
    """update_job raises ValidationError when moving to on_hold with an open blep."""

    def setUp(self):
        super().setUp()
        self.contact = Job.objects.first().contact
        self.user = User.objects.get(username='admin')
        self.job = _make_job(
            self.contact,
            Job.STATUS_SUBMITTED,
            Job.STATUS_APPROVED,
            Job.STATUS_IN_PROGRESS,
        )
        self.task = _make_task(self.job)

    def test_on_hold_blocked_while_open_blep_exists(self):
        # Create an open blep directly (end_time=None)
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        with self.assertRaises(ValidationError) as cm:
            JobService.update_job(self.job.pk, status=Job.STATUS_ON_HOLD)
        self.assertIn('open time entry', str(cm.exception))

    def test_cancelled_blocked_while_open_blep_exists(self):
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        with self.assertRaises(ValidationError) as cm:
            JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertIn('open time entry', str(cm.exception))

    def test_on_hold_allowed_after_blep_closed(self):
        blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        # Close the blep
        blep.end_time = timezone.now()
        blep.save()
        # Should succeed now
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_ON_HOLD)
        self.assertEqual(updated.status, Job.STATUS_ON_HOLD)

    def test_cancelled_allowed_after_blep_closed(self):
        blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        blep.end_time = timezone.now()
        blep.save()
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(updated.status, Job.STATUS_CANCELLED)

    def test_non_hold_cancel_status_not_blocked_by_open_blep(self):
        """Advancing to work_complete (or another non-hold/cancel status) is
        NOT blocked even if there's an open blep — the guard is narrow."""
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        # work_complete has its own guard (loose materials), but the blep guard
        # must not interfere; stop the task first so work_complete check passes
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()
        # No loose materials on this job, so work_complete should succeed
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_WORK_COMPLETE)
        self.assertEqual(updated.status, Job.STATUS_WORK_COMPLETE)

    def test_no_blep_on_hold_succeeds(self):
        """Sanity: transition works fine when there is no open blep at all."""
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_ON_HOLD)
        self.assertEqual(updated.status, Job.STATUS_ON_HOLD)

    def test_no_blep_cancelled_succeeds(self):
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(updated.status, Job.STATUS_CANCELLED)

    def test_closed_blep_only_on_hold_succeeds(self):
        """A blep with a non-null end_time must not block the transition."""
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now() - timezone.timedelta(hours=1),
            end_time=timezone.now(),
        )
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_ON_HOLD)
        self.assertEqual(updated.status, Job.STATUS_ON_HOLD)
