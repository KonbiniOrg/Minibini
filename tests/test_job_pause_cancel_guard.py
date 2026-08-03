"""Guard: holding (JobService.hold_job) or cancelling (update_job) is
rejected while any open Blep (end_time__isnull=True) exists on the job's
tasks."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Blep, Job, RateScheme, Task
from apps.jobs.services import JobService


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
    t = Task(name='Guard-Test Task', job=job)
    t.stamp_from_scheme(RateScheme.objects.get(pk=1))
    t.save()
    return t


class OpenBlepBlocksHoldTest(BaseTestCase):
    """hold_job / cancel raise ValidationError while an open blep exists."""

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

    def test_hold_blocked_while_open_blep_exists(self):
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        with self.assertRaises(ValidationError) as cm:
            JobService.hold_job(self.job.pk, 'pause for CO')
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

    def test_hold_allowed_after_blep_closed(self):
        blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        blep.end_time = timezone.now()
        blep.save()
        held = JobService.hold_job(self.job.pk, 'pause for CO')
        self.assertTrue(held.on_hold)

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
        """Advancing to work_complete is NOT blocked even if there's an open
        blep — the guard is narrow."""
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        self.task.status = Task.STATUS_COMPLETE
        self.task.save()
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_WORK_COMPLETE)
        self.assertEqual(updated.status, Job.STATUS_WORK_COMPLETE)

    def test_no_blep_hold_succeeds(self):
        held = JobService.hold_job(self.job.pk, 'pause for CO')
        self.assertTrue(held.on_hold)

    def test_no_blep_cancelled_succeeds(self):
        updated = JobService.update_job(self.job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(updated.status, Job.STATUS_CANCELLED)

    def test_closed_blep_only_hold_succeeds(self):
        """A blep with a non-null end_time must not block the hold."""
        Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now() - timezone.timedelta(hours=1),
            end_time=timezone.now(),
        )
        held = JobService.hold_job(self.job.pk, 'pause for CO')
        self.assertTrue(held.on_hold)
