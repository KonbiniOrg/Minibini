from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job


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
