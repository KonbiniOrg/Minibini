"""
Tests for the synchronization between Estimate and Job statuses.

Business Rules:
1. Only one Estimate per job may be approved (accepted)
2. When an Estimate is approved, the Job should automatically be approved
3. An approved Estimate cannot go back to Draft (but can be superseded)
4. When an approved Estimate is superseded, the new Estimate starts in Draft and the Job becomes Blocked
5. All existing EstWorksheet-Estimate status links remain unchanged
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from apps.jobs.models import Job, Estimate, EstWorksheet
from apps.contacts.models import Contact
from apps.core.models import User


class EstimateJobStatusSyncTest(TestCase):
    """Test the synchronization between Estimate and Job statuses."""

    def setUp(self):
        """Set up test data."""
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Customer',
            last_name='',
            email='customer@example.com'
        )

        # Create a test job
        self.job = Job.objects.create(
            job_number='TEST-2024-0001',
            contact=self.contact,
            description='Test job for status sync'
        )

    def test_only_one_approved_estimate_per_job(self):
        """Test that only one estimate per job can be in 'accepted' status."""
        # Create first estimate and approve it
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )
        # Must go through 'open' first
        estimate1.status = 'open'
        estimate1.save()
        estimate1.status = 'accepted'
        estimate1.save()

        # Create second estimate
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            status='draft'
        )

        # Move to open first
        estimate2.status = 'open'
        estimate2.save()

        # Attempt to approve second estimate should fail
        estimate2.status = 'accepted'
        with self.assertRaises(ValidationError) as context:
            estimate2.save()

        self.assertIn('already has an accepted estimate', str(context.exception))

    def test_job_auto_approved_when_estimate_approved(self):
        """Test that job status changes to 'approved' when estimate is accepted."""
        # Job should start in draft
        self.assertEqual(self.job.status, 'draft')

        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )

        # Change estimate to open first (following valid transition)
        estimate.status = 'open'
        estimate.save()

        # Job should still be draft
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        # Now approve the estimate
        estimate.status = 'accepted'
        estimate.save()

        # Job should now be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')

    def test_approved_estimate_cannot_go_back_to_draft(self):
        """Test that an accepted estimate cannot be changed back to draft status."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )

        # Move through valid transitions to accepted
        estimate.status = 'open'
        estimate.save()
        estimate.status = 'accepted'
        estimate.save()

        # Attempt to change back to draft should fail
        estimate.status = 'draft'
        with self.assertRaises(ValidationError) as context:
            estimate.save()

        self.assertIn('cannot transition estimate from accepted to draft', str(context.exception).lower())

    def test_approved_estimate_cannot_be_superseded(self):
        """Test that an accepted estimate cannot be superseded. - use a ChangeOrder instead"""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )

        # Move to accepted
        estimate.status = 'open'
        estimate.save()
        estimate.status = 'accepted'
        estimate.save()

        # Accepted is a terminal state - cannot transition to superseded
        estimate.status = 'superseded'
        with self.assertRaises(ValidationError) as context:
            estimate.save()

        # Refresh from DB to ensure we're checking the actual stored value
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'accepted')

    def test_new_estimate_after_superseding_starts_in_draft(self):
        """Test that a new estimate created after superseding starts in draft."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status='draft'
        )
        estimate1.status = 'open'
        estimate1.save()

        # Supersede it
        estimate1.status = 'superseded'
        estimate1.save()

        # Create new estimate (revision)
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=2,
            parent=estimate1,
            status='draft'  # Should start in draft
        )

        # New estimate should be in draft
        self.assertEqual(estimate2.status, 'draft')

    def test_worksheet_status_sync_remains_unchanged(self):
        """Test that EstWorksheet status synchronization with Estimate still works."""
        # Create estimate with worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='draft'
        )

        # When estimate goes to open, worksheet should go to final
        estimate.status = 'open'
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')

        # When estimate is accepted, worksheet should remain final
        estimate.status = 'accepted'
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')

    def test_worksheet_status_sync_remains_unchanged_superseded(self):
        """Test that EstWorksheet status synchronization with Estimate still works."""
        # Create estimate with worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='draft'
        )

        # Must go through 'open' first to reach superseded
        estimate.status = 'open'
        estimate.save()

        # When estimate is superseded, worksheet should be superseded
        estimate.status = 'superseded'
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'superseded')

    def test_job_status_changes_dont_affect_estimate(self):
        """Test that manual job status changes don't affect estimate status."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='open'
        )

        # Manually change job status (draft > submitted)
        self.job.status = 'submitted'
        self.job.save()

        # Estimate should remain unchanged
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'open')

        # Change job to approved, then completed
        self.job.status = 'approved'
        self.job.save()
        self.job.status = 'completed'
        self.job.save()

        # Estimate should still be unchanged
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, 'open')

    def test_multiple_estimates_with_different_statuses(self):
        """Test multiple estimates on same job with different statuses."""
        # Create first estimate and reject it
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status='draft'
        )
        estimate1.status = 'open'
        estimate1.save()
        estimate1.status = 'rejected'
        estimate1.save()

        # Job should still be draft (rejection doesn't auto-update job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        # Create second estimate and approve it
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            version=1,
            status='draft'
        )
        estimate2.status = 'open'
        estimate2.save()
        estimate2.status = 'accepted'
        estimate2.save()

        # Job should now be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')

        # First estimate should still be rejected
        estimate1.refresh_from_db()
        self.assertEqual(estimate1.status, 'rejected')

# TODO: an approved job should not have an unapproved estimate though ...
    def test_job_already_approved_remains_approved(self):
        """Test that if job is already approved, accepting an estimate keeps it approved."""
        # Manually approve the job (must go through submitted)
        self.job.status = 'submitted'
        self.job.save()
        self.job.status = 'approved'
        self.job.save()

        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )
        estimate.status = 'open'
        estimate.save()
        estimate.status = 'accepted'
        estimate.save()

        # Job should remain approved (not cause an error)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')

# TODO: a completed job shouldn't allow its estimates to change status
    def test_job_in_complete_status_not_affected(self):
        """Test that completed jobs are not affected by estimate changes."""
        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )
        estimate.status = 'open'
        estimate.save()
        estimate.status = 'accepted'
        estimate.save()

        # Job should be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')

        # Complete the job
        self.job.status = 'completed'
        self.job.save()

        # Try to supersede the estimate (but accepted is terminal, so this will fail)
        # Create a new estimate instead to test that completed jobs aren't affected
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            status='draft'
        )
        estimate2.status = 'open'
        estimate2.save()
        estimate2.status = 'superseded'
        estimate2.save()

        # Job should remain completed (not affected by estimate changes)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'completed')

    def test_rejected_estimate_does_not_affect_job(self):
        """Test that rejecting an estimate doesn't change job status."""
        # Job starts in draft
        self.assertEqual(self.job.status, 'draft')

        # Create and reject an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status='draft'
        )
        estimate.status = 'open'
        estimate.save()

        # Job is still draft (no signal handler for open->submitted transition)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        estimate.status = 'rejected'
        estimate.save()

        # Job should still be draft (rejecting estimate doesn't affect job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

    def test_estimate_revision_workflow(self):
        """Test the full workflow of estimate revision with job status updates."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status='draft'
        )
        estimate1.status = 'open'
        estimate1.save()
        estimate1.status = 'accepted'
        estimate1.save()

        # Job should be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')

    def test_estimate_revision_workflow2(self):
        """Test the full workflow of estimate revision with job status updates."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status='draft'
        )
        estimate1.status = 'open'
        estimate1.save()

        # Create revision (this typically happens through a view)
        # First, supersede the old estimate (open can transition to superseded)
        estimate1.status = 'superseded'
        estimate1.save()

        # Job should still be draft (no signal handler for superseding non-accepted estimates)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        # Create new version
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=2,
            parent=estimate1,
            status='draft'
        )

        # Job remains draft
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        # Open and accept the new estimate
        estimate2.status = 'open'
        estimate2.save()

        # Job still draft (no signal for open state)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'draft')

        # Accept the new estimate
        estimate2.status = 'accepted'
        estimate2.save()

        # Job should be approved (signal handler transitions draft->submitted->approved)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'approved')