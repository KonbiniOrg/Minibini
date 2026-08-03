from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.core.models import User
from apps.jobs.models import Blep, Job, RateScheme, Task
from apps.jobs.services import JobService


class JobOnHoldFlagModelTests(FixtureTestCase):
    """on_hold is an orthogonal flag on Job — not a status. The model owns:
    the field, its default, hold_reason clearing on release, and the removal
    of 'on_hold' from the status choices/transitions."""

    def _make_job(self, status):
        contact = Contact.objects.first()
        job = Job.objects.create(
            job_number=f'JOB-TEST-HOLDFLAG-{status}',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        # Walk valid transitions to the requested status.
        path = {
            Job.STATUS_DRAFT: [],
            Job.STATUS_SUBMITTED: [Job.STATUS_SUBMITTED],
            Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
            Job.STATUS_IN_PROGRESS: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
            ],
        }[status]
        for step in path:
            job.status = step
            job.save()
        job.refresh_from_db()
        return job

    def test_on_hold_defaults_false(self):
        job = self._make_job(status=Job.STATUS_APPROVED)
        self.assertFalse(job.on_hold)

    def test_status_on_hold_constant_gone(self):
        self.assertFalse(hasattr(Job, 'STATUS_ON_HOLD'))

    def test_on_hold_string_not_a_valid_status(self):
        job = self._make_job(status=Job.STATUS_APPROVED)
        job.status = 'on_hold'
        with self.assertRaises(ValidationError):
            job.save()

    def test_hold_reason_cleared_when_flag_drops(self):
        job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        job.on_hold = True
        job.hold_reason = 'waiting on CO'
        job.save()
        job.on_hold = False
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.hold_reason, '')

    def test_hold_reason_kept_while_held(self):
        job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        job.on_hold = True
        job.hold_reason = 'waiting on CO'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.hold_reason, 'waiting on CO')

    def test_held_job_keeps_underlying_status(self):
        job = self._make_job(status=Job.STATUS_IN_PROGRESS)
        job.on_hold = True
        job.hold_reason = 'x'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)
        self.assertTrue(job.on_hold)


class JobHoldReleaseServiceTests(FixtureTestCase):
    """JobService.hold_job / release_job semantics, and update_job's
    while-held status gate."""

    def _make_job(self, status, suffix=''):
        contact = Contact.objects.first()
        job = Job.objects.create(
            job_number=f'JOB-TEST-HOLDSVC-{status}{suffix}',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        path = {
            Job.STATUS_DRAFT: [],
            Job.STATUS_SUBMITTED: [Job.STATUS_SUBMITTED],
            Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
            Job.STATUS_IN_PROGRESS: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
            ],
            Job.STATUS_WORK_COMPLETE: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                Job.STATUS_WORK_COMPLETE,
            ],
        }[status]
        for step in path:
            job.status = step
            job.save()
        job.refresh_from_db()
        return job

    def _draft_co_for(self, job):
        from apps.estimates.models import ChangeOrder, Estimate
        estimate = Estimate.objects.first()
        return ChangeOrder.objects.create(
            job=job, estimate=estimate, status=ChangeOrder.STATUS_DRAFT,
        )

    # --- hold_job ---

    def test_hold_from_approved(self):
        job = self._make_job(Job.STATUS_APPROVED)
        held = JobService.hold_job(job.pk, 'customer rethink')
        self.assertTrue(held.on_hold)
        self.assertEqual(held.hold_reason, 'customer rethink')
        self.assertEqual(held.status, Job.STATUS_APPROVED)

    def test_hold_from_in_progress(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        held = JobService.hold_job(job.pk, 'change order')
        self.assertTrue(held.on_hold)
        self.assertEqual(held.status, Job.STATUS_IN_PROGRESS)

    def test_hold_rejected_on_draft(self):
        job = self._make_job(Job.STATUS_DRAFT)
        with self.assertRaises(ValidationError):
            JobService.hold_job(job.pk, 'reason')

    def test_hold_rejected_on_submitted(self):
        job = self._make_job(Job.STATUS_SUBMITTED)
        with self.assertRaises(ValidationError):
            JobService.hold_job(job.pk, 'reason')

    def test_hold_rejected_on_work_complete(self):
        job = self._make_job(Job.STATUS_WORK_COMPLETE)
        with self.assertRaises(ValidationError):
            JobService.hold_job(job.pk, 'reason')

    def test_hold_rejected_when_already_held(self):
        job = self._make_job(Job.STATUS_APPROVED)
        JobService.hold_job(job.pk, 'first')
        with self.assertRaises(ValidationError):
            JobService.hold_job(job.pk, 'second')

    def test_hold_rejected_without_reason(self):
        job = self._make_job(Job.STATUS_APPROVED)
        with self.assertRaises(ValidationError):
            JobService.hold_job(job.pk, '   ')

    def test_hold_rejected_with_open_blep(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        task = Task(name='T', job=job)
        task.stamp_from_scheme(RateScheme.objects.get(pk=1))
        task.save()
        user = User.objects.get(username='admin')
        Blep.objects.create(
            user=user, task=task, start_time=timezone.now(), end_time=None,
        )
        with self.assertRaises(ValidationError) as cm:
            JobService.hold_job(job.pk, 'pause')
        self.assertIn('open time entry', str(cm.exception))

    # --- release_job ---

    def test_release_clears_flag_and_reason(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        JobService.hold_job(job.pk, 'pause')
        released = JobService.release_job(job.pk)
        self.assertFalse(released.on_hold)
        self.assertEqual(released.hold_reason, '')
        self.assertEqual(released.status, Job.STATUS_IN_PROGRESS)

    def test_release_rejected_when_not_held(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        with self.assertRaises(ValidationError):
            JobService.release_job(job.pk)

    def test_release_blocked_by_draft_change_order(self):
        job = self._make_job(Job.STATUS_APPROVED)
        JobService.hold_job(job.pk, 'CO editing')
        self._draft_co_for(job)
        with self.assertRaises(ValidationError) as cm:
            JobService.release_job(job.pk)
        self.assertIn('change order', str(cm.exception))

    # --- update_job while held ---

    def test_status_change_blocked_while_held(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        JobService.hold_job(job.pk, 'pause')
        with self.assertRaises(ValidationError):
            JobService.update_job(job.pk, status=Job.STATUS_WORK_COMPLETE)

    def test_non_status_edit_allowed_while_held(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        JobService.hold_job(job.pk, 'pause')
        updated = JobService.update_job(job.pk, description='new text')
        self.assertEqual(updated.description, 'new text')
        self.assertTrue(updated.on_hold)

    def test_cancel_while_held_clears_flag(self):
        job = self._make_job(Job.STATUS_IN_PROGRESS)
        JobService.hold_job(job.pk, 'pause')
        cancelled = JobService.update_job(job.pk, status=Job.STATUS_CANCELLED)
        self.assertEqual(cancelled.status, Job.STATUS_CANCELLED)
        self.assertFalse(cancelled.on_hold)

    def test_cancel_while_held_blocked_by_live_co(self):
        job = self._make_job(Job.STATUS_APPROVED)
        JobService.hold_job(job.pk, 'CO editing')
        self._draft_co_for(job)
        with self.assertRaises(ValidationError):
            JobService.update_job(job.pk, status=Job.STATUS_CANCELLED)
