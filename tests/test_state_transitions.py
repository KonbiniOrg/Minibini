from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem
from apps.contacts.models import Contact
from apps.core.models import Configuration


class JobStateTransitionTest(TestCase):
    """Test Job state transitions follow the defined workflow paths."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')

    def test_job_starts_in_draft(self):
        """Test that new Jobs start in Draft state."""
        job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        self.assertEqual(job.status, Job.STATUS_DRAFT)

    # Valid transition paths
    def test_draft_to_submitted(self):
        """Test Draft > Submitted transition."""
        job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_SUBMITTED)

    def test_draft_to_rejected(self):
        """Test Draft > Rejected transition."""
        job = Job.objects.create(
            job_number="JOB002",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )
        job.status = Job.STATUS_REJECTED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_REJECTED)

    def test_submitted_to_approved(self):
        """Test Submitted > Approved transition."""
        job = Job.objects.create(
            job_number="JOB003",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_APPROVED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

    def test_submitted_to_rejected(self):
        """Test Submitted > Rejected transition."""
        job = Job.objects.create(
            job_number="JOB004",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_REJECTED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_REJECTED)

    def test_approved_to_completed(self):
        """Test Approved > Work Complete > Completed transition."""
        job = Job.objects.create(
            job_number="JOB005",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        job.status = Job.STATUS_COMPLETED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_COMPLETED)

    def test_approved_to_cancelled(self):
        """Test Approved > Cancelled transition."""
        job = Job.objects.create(
            job_number="JOB006",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_CANCELLED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_CANCELLED)

    # Invalid transition paths - these should raise ValidationError
    def test_draft_to_completed_invalid(self):
        """Test that Draft cannot transition directly to Completed."""
        job = Job.objects.create(
            job_number="JOB010",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )
        job.status = Job.STATUS_COMPLETED
        with self.assertRaises(ValidationError):
            job.save()

    def test_draft_to_cancelled_invalid(self):
        """Test that Draft cannot transition directly to Cancelled."""
        job = Job.objects.create(
            job_number="JOB011",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )
        job.status = Job.STATUS_CANCELLED
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_completed_invalid(self):
        """Test that Submitted cannot transition directly to Completed."""
        job = Job.objects.create(
            job_number="JOB012",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_COMPLETED
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_cancelled_invalid(self):
        """Test that Submitted cannot transition directly to Cancelled."""
        job = Job.objects.create(
            job_number="JOB013",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_CANCELLED
        with self.assertRaises(ValidationError):
            job.save()

    def test_rejected_to_any_invalid(self):
        """Test that Rejected is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB014",
            contact=self.contact,
            status=Job.STATUS_REJECTED
        )
        for status in [Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED, Job.STATUS_CANCELLED]:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to rejected

    def test_completed_to_any_invalid(self):
        """Test that Completed is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB015",
            contact=self.contact,
            status=Job.STATUS_COMPLETED
        )
        for status in [Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_REJECTED, Job.STATUS_CANCELLED]:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to completed

    def test_cancelled_to_any_invalid(self):
        """Test that Cancelled is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB016",
            contact=self.contact,
            status=Job.STATUS_CANCELLED
        )
        for status in [Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_REJECTED, Job.STATUS_COMPLETED]:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to cancelled

    def test_approved_to_draft_invalid(self):
        """Test that Approved cannot go back to Draft."""
        job = Job.objects.create(
            job_number="JOB017",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_DRAFT
        with self.assertRaises(ValidationError):
            job.save()

    def test_approved_to_submitted_invalid(self):
        """Test that Approved cannot go back to Submitted."""
        job = Job.objects.create(
            job_number="JOB018",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_SUBMITTED
        with self.assertRaises(ValidationError):
            job.save()

    def test_approved_to_rejected_invalid(self):
        """Test that Approved cannot transition to Rejected."""
        job = Job.objects.create(
            job_number="JOB019",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_REJECTED
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_draft_invalid(self):
        """Test that Submitted cannot go back to Draft."""
        job = Job.objects.create(
            job_number="JOB020",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_DRAFT
        with self.assertRaises(ValidationError):
            job.save()

    def test_full_valid_path_to_completed(self):
        """Test full path: Draft > Submitted > Approved > Completed."""
        job = Job.objects.create(
            job_number="JOB100",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )

        job.status = Job.STATUS_SUBMITTED
        job.save()
        self.assertEqual(job.status, Job.STATUS_SUBMITTED)

        job.status = Job.STATUS_APPROVED
        job.save()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)

        job.status = Job.STATUS_COMPLETED
        job.save()
        self.assertEqual(job.status, Job.STATUS_COMPLETED)

    def test_full_valid_path_to_cancelled(self):
        """Test full path: Draft > Submitted > Approved > Cancelled."""
        job = Job.objects.create(
            job_number="JOB101",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )

        job.status = Job.STATUS_SUBMITTED
        job.save()
        self.assertEqual(job.status, Job.STATUS_SUBMITTED)

        job.status = Job.STATUS_APPROVED
        job.save()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

        job.status = Job.STATUS_CANCELLED
        job.save()
        self.assertEqual(job.status, Job.STATUS_CANCELLED)

    def test_path_draft_to_rejected(self):
        """Test path: Draft > Rejected."""
        job = Job.objects.create(
            job_number="JOB102",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )

        job.status = Job.STATUS_REJECTED
        job.save()
        self.assertEqual(job.status, Job.STATUS_REJECTED)

    def test_path_submitted_to_rejected(self):
        """Test path: Draft > Submitted > Rejected."""
        job = Job.objects.create(
            job_number="JOB103",
            contact=self.contact,
            status=Job.STATUS_DRAFT
        )

        job.status = Job.STATUS_SUBMITTED
        job.save()
        self.assertEqual(job.status, Job.STATUS_SUBMITTED)

        job.status = Job.STATUS_REJECTED
        job.save()
        self.assertEqual(job.status, Job.STATUS_REJECTED)

    # Job Date Field Tests
    def test_created_date_set_on_creation(self):
        """Test that created_date is set when Job is created."""
        before_creation = timezone.now()
        job = Job.objects.create(
            job_number="JOB200",
            contact=self.contact
        )
        after_creation = timezone.now()

        self.assertIsNotNone(job.created_date)
        self.assertGreaterEqual(job.created_date, before_creation)
        self.assertLessEqual(job.created_date, after_creation)

    def test_created_date_immutable(self):
        """Test that created_date cannot be changed after creation."""
        job = Job.objects.create(
            job_number="JOB201",
            contact=self.contact
        )
        original_date = job.created_date

        # Try to change it
        new_date = timezone.now() + timedelta(days=10)
        job.created_date = new_date
        job.save()

        job.refresh_from_db()
        self.assertEqual(job.created_date, original_date)

    def test_start_date_set_when_approved(self):
        """Test that start_date is set when Job moves to approved status."""
        job = Job.objects.create(
            job_number="JOB202",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        self.assertIsNone(job.start_date)

        before_transition = timezone.now()
        job.status = Job.STATUS_APPROVED
        job.save()
        after_transition = timezone.now()

        job.refresh_from_db()
        self.assertIsNotNone(job.start_date)
        self.assertGreaterEqual(job.start_date, before_transition)
        self.assertLessEqual(job.start_date, after_transition)

    def test_start_date_immutable(self):
        """Test that start_date cannot be changed once set."""
        job = Job.objects.create(
            job_number="JOB203",
            contact=self.contact,
            status=Job.STATUS_SUBMITTED
        )
        job.status = Job.STATUS_APPROVED
        job.save()
        job.refresh_from_db()

        original_start_date = job.start_date

        # Try to change it
        job.start_date = timezone.now() + timedelta(days=5)
        job.save()

        job.refresh_from_db()
        self.assertEqual(job.start_date, original_start_date)

    def test_completed_date_set_when_completed(self):
        """Test that completed_date is set when Job moves to completed status."""
        job = Job.objects.create(
            job_number="JOB204",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        self.assertIsNone(job.completed_date)

        job.status = Job.STATUS_WORK_COMPLETE
        job.save()

        before_transition = timezone.now()
        job.status = Job.STATUS_COMPLETED
        job.save()
        after_transition = timezone.now()

        job.refresh_from_db()
        self.assertIsNotNone(job.completed_date)
        self.assertGreaterEqual(job.completed_date, before_transition)
        self.assertLessEqual(job.completed_date, after_transition)

    def test_completed_date_set_when_cancelled(self):
        """Test that completed_date is set when Job moves to cancelled status."""
        job = Job.objects.create(
            job_number="JOB205",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        self.assertIsNone(job.completed_date)

        before_transition = timezone.now()
        job.status = Job.STATUS_CANCELLED
        job.save()
        after_transition = timezone.now()

        job.refresh_from_db()
        self.assertIsNotNone(job.completed_date)
        self.assertGreaterEqual(job.completed_date, before_transition)
        self.assertLessEqual(job.completed_date, after_transition)

    def test_completed_date_immutable(self):
        """Test that completed_date cannot be changed once set."""
        job = Job.objects.create(
            job_number="JOB206",
            contact=self.contact,
            status=Job.STATUS_APPROVED
        )
        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        job.status = Job.STATUS_COMPLETED
        job.save()
        job.refresh_from_db()

        original_completed_date = job.completed_date

        # Try to change it
        job.completed_date = timezone.now() + timedelta(days=10)
        job.save()

        job.refresh_from_db()
        self.assertEqual(job.completed_date, original_completed_date)

    def test_due_date_can_be_changed(self):
        """Test that due_date can be changed by users with permissions."""
        job = Job.objects.create(
            job_number="JOB207",
            contact=self.contact
        )

        # Set initial due_date
        initial_due_date = timezone.now() + timedelta(days=30)
        job.due_date = initial_due_date
        job.save()

        job.refresh_from_db()
        self.assertEqual(job.due_date, initial_due_date)

        # Change due_date
        new_due_date = timezone.now() + timedelta(days=60)
        job.due_date = new_due_date
        job.save()

        job.refresh_from_db()
        self.assertEqual(job.due_date, new_due_date)


class EstimateStateTransitionTest(TestCase):
    """Test Estimate state transitions and date field handling."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact
        )
        # Set default expiration days in Configuration
        Configuration.objects.create(
            key='est_expire_days',
            value='30'
        )

    def _add_estimate_line_item(self, estimate):
        EstimateLineItem.objects.create(estimate=estimate, description='Test item', price=Decimal('100.00'))

    def test_estimate_starts_in_draft(self):
        """Test that new Estimates start in Draft state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001"
        )
        self.assertEqual(estimate.status, Estimate.STATUS_DRAFT)

    def test_created_date_set_on_creation(self):
        """Test that created_date is set when Estimate is created."""
        before_creation = timezone.now()
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001"
        )
        after_creation = timezone.now()

        self.assertIsNotNone(estimate.created_date)
        self.assertGreaterEqual(estimate.created_date, before_creation)
        self.assertLessEqual(estimate.created_date, after_creation)

    def test_created_date_immutable(self):
        """Test that created_date cannot be changed after creation."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001"
        )
        original_date = estimate.created_date

        # Try to change it
        new_date = timezone.now() + timedelta(days=10)
        estimate.created_date = new_date
        estimate.save()

        estimate.refresh_from_db()
        self.assertEqual(estimate.created_date, original_date)

    # Valid transition paths
    def test_draft_to_open(self):
        """Test Draft > Open transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST002",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

    def test_draft_to_superseded_invalid(self):
        """Test that Draft cannot transition directly to Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST003",
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_SUPERSEDED
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_draft_to_expired_invalid(self):
        """Test that Draft cannot transition directly to Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST004",
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_EXPIRED
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_draft_to_rejected(self):
        """Test Draft > Rejected transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST005",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)
        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_REJECTED)

    def test_open_to_accepted(self):
        """Test Open > Accepted transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST006",
            status=Estimate.STATUS_OPEN
        )
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_ACCEPTED)

    def test_open_to_rejected(self):
        """Test Open > Rejected transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST007",
            status=Estimate.STATUS_OPEN
        )
        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_REJECTED)

    def test_open_to_superseded(self):
        """Test Open > Superseded transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST008",
            status=Estimate.STATUS_OPEN
        )
        estimate.status = Estimate.STATUS_SUPERSEDED
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_SUPERSEDED)

    def test_open_to_expired(self):
        """Test Open > Expired transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST009",
            status=Estimate.STATUS_OPEN
        )
        estimate.status = Estimate.STATUS_EXPIRED
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_EXPIRED)

    # Date field tests
    def test_sent_date_set_when_moving_to_open(self):
        """Test that sent_date is set when transitioning to Open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST010",
            status=Job.STATUS_DRAFT
        )
        self.assertIsNone(estimate.sent_date)
        self._add_estimate_line_item(estimate)

        before_transition = timezone.now()
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        after_transition = timezone.now()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.sent_date)
        self.assertGreaterEqual(estimate.sent_date, before_transition)
        self.assertLessEqual(estimate.sent_date, after_transition)

    def test_sent_date_immutable(self):
        """Test that sent_date cannot be changed once set."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST011",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.refresh_from_db()

        original_sent_date = estimate.sent_date

        # Try to change it
        estimate.sent_date = timezone.now() + timedelta(days=5)
        estimate.save()

        estimate.refresh_from_db()
        self.assertEqual(estimate.sent_date, original_sent_date)

    def test_expiration_date_set_when_moving_to_open(self):
        """Test that expiration_date is set when transitioning to Open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST012",
            status=Job.STATUS_DRAFT
        )
        self.assertIsNone(estimate.expiration_date)
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.expiration_date)
        # Should be ~30 days from now (based on Configuration)
        expected_expiration = timezone.now() + timedelta(days=30)
        time_diff = abs((estimate.expiration_date - expected_expiration).total_seconds())
        self.assertLess(time_diff, 10)  # Within 10 seconds

    def test_expiration_date_can_be_changed(self):
        """Test that expiration_date can be changed by users with permissions."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST013",
            status=Estimate.STATUS_OPEN
        )

        new_expiration = timezone.now() + timedelta(days=60)
        estimate.expiration_date = new_expiration
        estimate.save()

        estimate.refresh_from_db()
        time_diff = abs((estimate.expiration_date - new_expiration).total_seconds())
        self.assertLess(time_diff, 1)

    def test_closed_date_set_when_accepted(self):
        """Test that closed_date is set when transitioning to Accepted."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST014",
            status=Estimate.STATUS_OPEN
        )
        self.assertIsNone(estimate.closed_date)

        before_transition = timezone.now()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()
        after_transition = timezone.now()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)
        self.assertGreaterEqual(estimate.closed_date, before_transition)
        self.assertLessEqual(estimate.closed_date, after_transition)

    def test_closed_date_set_when_rejected(self):
        """Test that closed_date is set when transitioning to Rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST015",
            status=Estimate.STATUS_OPEN
        )

        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_set_when_superseded(self):
        """Test that closed_date is set when transitioning to Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST016",
            status=Estimate.STATUS_OPEN  # Must start from open, not draft
        )

        estimate.status = Estimate.STATUS_SUPERSEDED
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_set_when_expired(self):
        """Test that closed_date is set when transitioning to Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST017",
            status=Estimate.STATUS_OPEN  # Must start from open, not draft
        )

        estimate.status = Estimate.STATUS_EXPIRED
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_immutable(self):
        """Test that closed_date cannot be changed once set."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST018",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)
        # Must go through 'open' first
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()
        estimate.refresh_from_db()

        original_closed_date = estimate.closed_date

        # Try to change it
        estimate.closed_date = timezone.now() + timedelta(days=10)
        estimate.save()

        estimate.refresh_from_db()
        self.assertEqual(estimate.closed_date, original_closed_date)

    # Invalid transition paths
    def test_draft_to_accepted_invalid(self):
        """Test that Draft cannot transition directly to Accepted."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST020",
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_ACCEPTED
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_open_to_draft_invalid(self):
        """Test that Open cannot go back to Draft."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST021",
            status=Estimate.STATUS_OPEN
        )
        estimate.status = Estimate.STATUS_DRAFT
        with self.assertRaises(ValidationError):
            estimate.save()


    def test_accepted_to_any_invalid(self):
        """Test that Accepted is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST024",
            status=Estimate.STATUS_ACCEPTED
        )
        for status in [Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN, Estimate.STATUS_REJECTED, Estimate.STATUS_EXPIRED, Estimate.STATUS_SUPERSEDED]:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_rejected_to_any_invalid(self):
        """Test that Rejected is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST025",
            status=Job.STATUS_REJECTED
        )
        for status in [Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED, Estimate.STATUS_EXPIRED, Estimate.STATUS_SUPERSEDED]:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_expired_to_any_invalid(self):
        """Test that Expired is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST026",
            status=Estimate.STATUS_EXPIRED
        )
        for status in [Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED, Estimate.STATUS_SUPERSEDED]:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_superseded_to_any_invalid(self):
        """Test that Superseded is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST027",
            status=Estimate.STATUS_SUPERSEDED
        )
        for status in [Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED, Estimate.STATUS_REJECTED, Estimate.STATUS_EXPIRED]:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    # Valid full paths
    def test_full_path_draft_to_open_to_accepted(self):
        """Test full path: Draft > Open > Accepted."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST100",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_ACCEPTED)
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_rejected(self):
        """Test full path: Draft > Open > Rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST101",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_REJECTED)
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_superseded(self):
        """Test full path: Draft > Open > Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST102",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = Estimate.STATUS_SUPERSEDED
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_SUPERSEDED)
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_expired(self):
        """Test full path: Draft > Open > Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST103",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = Estimate.STATUS_EXPIRED
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_EXPIRED)
        self.assertIsNotNone(estimate.closed_date)

    def test_path_draft_to_rejected(self):
        """Test path: Draft > Rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST104",
            status=Job.STATUS_DRAFT
        )
        self._add_estimate_line_item(estimate)

        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()
        self.assertEqual(estimate.status, Estimate.STATUS_REJECTED)
        self.assertIsNotNone(estimate.closed_date)
