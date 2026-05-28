from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.jobs.models import Job


class JobOnHoldTransitionTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        # Fixture job starts as draft; advance to approved via valid transitions.
        self.job.status = Job.STATUS_SUBMITTED
        self.job.save()
        self.job.status = Job.STATUS_APPROVED
        self.job.save()
        self.job.refresh_from_db()

    def _set_status(self, status):
        self.job.status = status
        self.job.save()
        self.job.refresh_from_db()

    def test_approved_to_on_hold(self):
        self._set_status(Job.STATUS_ON_HOLD)
        self.assertEqual(self.job.status, Job.STATUS_ON_HOLD)

    def test_in_progress_to_on_hold_and_back(self):
        self._set_status(Job.STATUS_IN_PROGRESS)
        self._set_status(Job.STATUS_ON_HOLD)
        self._set_status(Job.STATUS_IN_PROGRESS)
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_on_hold_to_cancelled(self):
        self._set_status(Job.STATUS_ON_HOLD)
        self._set_status(Job.STATUS_CANCELLED)
        self.assertEqual(self.job.status, Job.STATUS_CANCELLED)

    def test_hold_reason_cleared_on_resume(self):
        self.job.status = Job.STATUS_ON_HOLD
        self.job.hold_reason = 'CO in negotiation'
        self.job.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.hold_reason, 'CO in negotiation')
        self._set_status(Job.STATUS_APPROVED)
        self.assertEqual(self.job.hold_reason, '')

    def test_draft_cannot_go_on_hold(self):
        # Roll back to draft via cancellation (approved → cancelled), then
        # use a separate job in DRAFT state.  The simplest path is to reach a
        # fresh draft-state job from the fixture's second job (JOB-2024-0002 is
        # completed — terminal). So we use first() which is already mutated;
        # instead, create a minimal draft job and assert on_hold is rejected.
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        from apps.core.models import Configuration
        # job_number must be unique; use a recognisable value.
        draft_job = Job.objects.create(
            job_number='JOB-TEST-ONHOLD-DRAFT',
            contact=contact,
            status=Job.STATUS_DRAFT,
        )
        draft_job.status = Job.STATUS_ON_HOLD
        with self.assertRaises(ValidationError):
            draft_job.save()
