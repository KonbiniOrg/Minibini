from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
from apps.jobs.models import Job, Estimate
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
        self.assertEqual(job.status, 'draft')

    # Valid transition paths
    def test_draft_to_submitted(self):
        """Test Draft > Submitted transition."""
        job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            status='draft'
        )
        job.status = 'submitted'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'submitted')

    def test_draft_to_rejected(self):
        """Test Draft > Rejected transition."""
        job = Job.objects.create(
            job_number="JOB002",
            contact=self.contact,
            status='draft'
        )
        job.status = 'rejected'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'rejected')

    def test_submitted_to_approved(self):
        """Test Submitted > Approved transition."""
        job = Job.objects.create(
            job_number="JOB003",
            contact=self.contact,
            status='submitted'
        )
        job.status = 'approved'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'approved')

    def test_submitted_to_rejected(self):
        """Test Submitted > Rejected transition."""
        job = Job.objects.create(
            job_number="JOB004",
            contact=self.contact,
            status='submitted'
        )
        job.status = 'rejected'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'rejected')

    def test_approved_to_completed(self):
        """Test Approved > Completed transition."""
        job = Job.objects.create(
            job_number="JOB005",
            contact=self.contact,
            status='approved'
        )
        job.status = 'completed'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')

    def test_approved_to_cancelled(self):
        """Test Approved > Cancelled transition."""
        job = Job.objects.create(
            job_number="JOB006",
            contact=self.contact,
            status='approved'
        )
        job.status = 'cancelled'
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')

    # Invalid transition paths - these should raise ValidationError
    def test_draft_to_completed_invalid(self):
        """Test that Draft cannot transition directly to Completed."""
        job = Job.objects.create(
            job_number="JOB010",
            contact=self.contact,
            status='draft'
        )
        job.status = 'completed'
        with self.assertRaises(ValidationError):
            job.save()

    def test_draft_to_cancelled_invalid(self):
        """Test that Draft cannot transition directly to Cancelled."""
        job = Job.objects.create(
            job_number="JOB011",
            contact=self.contact,
            status='draft'
        )
        job.status = 'cancelled'
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_completed_invalid(self):
        """Test that Submitted cannot transition directly to Completed."""
        job = Job.objects.create(
            job_number="JOB012",
            contact=self.contact,
            status='submitted'
        )
        job.status = 'completed'
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_cancelled_invalid(self):
        """Test that Submitted cannot transition directly to Cancelled."""
        job = Job.objects.create(
            job_number="JOB013",
            contact=self.contact,
            status='submitted'
        )
        job.status = 'cancelled'
        with self.assertRaises(ValidationError):
            job.save()

    def test_rejected_to_any_invalid(self):
        """Test that Rejected is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB014",
            contact=self.contact,
            status='rejected'
        )
        for status in ['draft', 'submitted', 'approved', 'completed', 'cancelled']:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to rejected

    def test_completed_to_any_invalid(self):
        """Test that Completed is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB015",
            contact=self.contact,
            status='completed'
        )
        for status in ['draft', 'submitted', 'approved', 'rejected', 'cancelled']:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to completed

    def test_cancelled_to_any_invalid(self):
        """Test that Cancelled is a terminal state and cannot transition."""
        job = Job.objects.create(
            job_number="JOB016",
            contact=self.contact,
            status='cancelled'
        )
        for status in ['draft', 'submitted', 'approved', 'rejected', 'completed']:
            job.status = status
            with self.assertRaises(ValidationError):
                job.save()
            job.refresh_from_db()  # Reset to cancelled

    def test_approved_to_draft_invalid(self):
        """Test that Approved cannot go back to Draft."""
        job = Job.objects.create(
            job_number="JOB017",
            contact=self.contact,
            status='approved'
        )
        job.status = 'draft'
        with self.assertRaises(ValidationError):
            job.save()

    def test_approved_to_submitted_invalid(self):
        """Test that Approved cannot go back to Submitted."""
        job = Job.objects.create(
            job_number="JOB018",
            contact=self.contact,
            status='approved'
        )
        job.status = 'submitted'
        with self.assertRaises(ValidationError):
            job.save()

    def test_approved_to_rejected_invalid(self):
        """Test that Approved cannot transition to Rejected."""
        job = Job.objects.create(
            job_number="JOB019",
            contact=self.contact,
            status='approved'
        )
        job.status = 'rejected'
        with self.assertRaises(ValidationError):
            job.save()

    def test_submitted_to_draft_invalid(self):
        """Test that Submitted cannot go back to Draft."""
        job = Job.objects.create(
            job_number="JOB020",
            contact=self.contact,
            status='submitted'
        )
        job.status = 'draft'
        with self.assertRaises(ValidationError):
            job.save()

    def test_full_valid_path_to_completed(self):
        """Test full path: Draft > Submitted > Approved > Completed."""
        job = Job.objects.create(
            job_number="JOB100",
            contact=self.contact,
            status='draft'
        )

        job.status = 'submitted'
        job.save()
        self.assertEqual(job.status, 'submitted')

        job.status = 'approved'
        job.save()
        self.assertEqual(job.status, 'approved')

        job.status = 'completed'
        job.save()
        self.assertEqual(job.status, 'completed')

    def test_full_valid_path_to_cancelled(self):
        """Test full path: Draft > Submitted > Approved > Cancelled."""
        job = Job.objects.create(
            job_number="JOB101",
            contact=self.contact,
            status='draft'
        )

        job.status = 'submitted'
        job.save()
        self.assertEqual(job.status, 'submitted')

        job.status = 'approved'
        job.save()
        self.assertEqual(job.status, 'approved')

        job.status = 'cancelled'
        job.save()
        self.assertEqual(job.status, 'cancelled')

    def test_path_draft_to_rejected(self):
        """Test path: Draft > Rejected."""
        job = Job.objects.create(
            job_number="JOB102",
            contact=self.contact,
            status='draft'
        )

        job.status = 'rejected'
        job.save()
        self.assertEqual(job.status, 'rejected')

    def test_path_submitted_to_rejected(self):
        """Test path: Draft > Submitted > Rejected."""
        job = Job.objects.create(
            job_number="JOB103",
            contact=self.contact,
            status='draft'
        )

        job.status = 'submitted'
        job.save()
        self.assertEqual(job.status, 'submitted')

        job.status = 'rejected'
        job.save()
        self.assertEqual(job.status, 'rejected')

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
            status='submitted'
        )
        self.assertIsNone(job.start_date)

        before_transition = timezone.now()
        job.status = 'approved'
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
            status='submitted'
        )
        job.status = 'approved'
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
            status='approved'
        )
        self.assertIsNone(job.completed_date)

        before_transition = timezone.now()
        job.status = 'completed'
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
            status='approved'
        )
        self.assertIsNone(job.completed_date)

        before_transition = timezone.now()
        job.status = 'cancelled'
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
            status='approved'
        )
        job.status = 'completed'
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

    def test_estimate_starts_in_draft(self):
        """Test that new Estimates start in Draft state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001"
        )
        self.assertEqual(estimate.status, 'draft')

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
            status='draft'
        )
        estimate.status = 'open'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'open')

    def test_draft_to_superseded_invalid(self):
        """Test that Draft cannot transition directly to Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST003",
            status='draft'
        )
        estimate.status = 'superseded'
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_draft_to_expired_invalid(self):
        """Test that Draft cannot transition directly to Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST004",
            status='draft'
        )
        estimate.status = 'expired'
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_draft_to_rejected(self):
        """Test Draft > Rejected transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST005",
            status='draft'
        )
        estimate.status = 'rejected'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'rejected')

    def test_open_to_accepted(self):
        """Test Open > Accepted transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST006",
            status='open'
        )
        estimate.status = 'accepted'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'accepted')

    def test_open_to_rejected(self):
        """Test Open > Rejected transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST007",
            status='open'
        )
        estimate.status = 'rejected'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'rejected')

    def test_open_to_superseded(self):
        """Test Open > Superseded transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST008",
            status='open'
        )
        estimate.status = 'superseded'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'superseded')

    def test_open_to_expired(self):
        """Test Open > Expired transition."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST009",
            status='open'
        )
        estimate.status = 'expired'
        estimate.save()
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'expired')

    # Date field tests
    def test_sent_date_set_when_moving_to_open(self):
        """Test that sent_date is set when transitioning to Open."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST010",
            status='draft'
        )
        self.assertIsNone(estimate.sent_date)

        before_transition = timezone.now()
        estimate.status = 'open'
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
            status='draft'
        )
        estimate.status = 'open'
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
            status='draft'
        )
        self.assertIsNone(estimate.expiration_date)

        estimate.status = 'open'
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
            status='open'
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
            status='open'
        )
        self.assertIsNone(estimate.closed_date)

        before_transition = timezone.now()
        estimate.status = 'accepted'
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
            status='open'
        )

        estimate.status = 'rejected'
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_set_when_superseded(self):
        """Test that closed_date is set when transitioning to Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST016",
            status='open'  # Must start from open, not draft
        )

        estimate.status = 'superseded'
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_set_when_expired(self):
        """Test that closed_date is set when transitioning to Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST017",
            status='open'  # Must start from open, not draft
        )

        estimate.status = 'expired'
        estimate.save()

        estimate.refresh_from_db()
        self.assertIsNotNone(estimate.closed_date)

    def test_closed_date_immutable(self):
        """Test that closed_date cannot be changed once set."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST018",
            status='draft'
        )
        # Must go through 'open' first
        estimate.status = 'open'
        estimate.save()
        estimate.status = 'accepted'
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
            status='draft'
        )
        estimate.status = 'accepted'
        with self.assertRaises(ValidationError):
            estimate.save()

    def test_open_to_draft_invalid(self):
        """Test that Open cannot go back to Draft."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST021",
            status='open'
        )
        estimate.status = 'draft'
        with self.assertRaises(ValidationError):
            estimate.save()


    def test_accepted_to_any_invalid(self):
        """Test that Accepted is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST024",
            status='accepted'
        )
        for status in ['draft', 'open', 'rejected', 'expired', 'superseded']:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_rejected_to_any_invalid(self):
        """Test that Rejected is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST025",
            status='rejected'
        )
        for status in ['draft', 'open', 'accepted', 'expired', 'superseded']:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_expired_to_any_invalid(self):
        """Test that Expired is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST026",
            status='expired'
        )
        for status in ['draft', 'open', 'accepted', 'rejected', 'superseded']:
            estimate.status = status
            with self.assertRaises(ValidationError):
                estimate.save()
            estimate.refresh_from_db()

    def test_superseded_to_any_invalid(self):
        """Test that Superseded is a terminal state."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST027",
            status='superseded'
        )
        for status in ['draft', 'open', 'accepted', 'rejected', 'expired']:
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
            status='draft'
        )

        estimate.status = 'open'
        estimate.save()
        self.assertEqual(estimate.status, 'open')
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = 'accepted'
        estimate.save()
        self.assertEqual(estimate.status, 'accepted')
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_rejected(self):
        """Test full path: Draft > Open > Rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST101",
            status='draft'
        )

        estimate.status = 'open'
        estimate.save()
        self.assertEqual(estimate.status, 'open')

        estimate.status = 'rejected'
        estimate.save()
        self.assertEqual(estimate.status, 'rejected')
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_superseded(self):
        """Test full path: Draft > Open > Superseded."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST102",
            status='draft'
        )

        estimate.status = 'open'
        estimate.save()
        self.assertEqual(estimate.status, 'open')
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = 'superseded'
        estimate.save()
        self.assertEqual(estimate.status, 'superseded')
        self.assertIsNotNone(estimate.closed_date)

    def test_full_path_draft_to_open_to_expired(self):
        """Test full path: Draft > Open > Expired."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST103",
            status='draft'
        )

        estimate.status = 'open'
        estimate.save()
        self.assertEqual(estimate.status, 'open')
        self.assertIsNotNone(estimate.sent_date)
        self.assertIsNotNone(estimate.expiration_date)

        estimate.status = 'expired'
        estimate.save()
        self.assertEqual(estimate.status, 'expired')
        self.assertIsNotNone(estimate.closed_date)

    def test_path_draft_to_rejected(self):
        """Test path: Draft > Rejected."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST104",
            status='draft'
        )

        estimate.status = 'rejected'
        estimate.save()
        self.assertEqual(estimate.status, 'rejected')
        self.assertIsNotNone(estimate.closed_date)
