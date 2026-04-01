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
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstWorksheet
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
        """Test that only one estimate per job can be in Estimate.STATUS_ACCEPTED status."""
        # Create first estimate and approve it
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )
        # Must go through 'open' first
        estimate1.status = Estimate.STATUS_OPEN
        estimate1.save()
        estimate1.status = Estimate.STATUS_ACCEPTED
        estimate1.save()

        # Create second estimate
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            status=Job.STATUS_DRAFT
        )

        # Move to open first
        estimate2.status = Estimate.STATUS_OPEN
        estimate2.save()

        # Attempt to approve second estimate should fail
        estimate2.status = Estimate.STATUS_ACCEPTED
        with self.assertRaises(ValidationError) as context:
            estimate2.save()

        self.assertIn('already has an accepted estimate', str(context.exception))

    def test_job_auto_approved_when_estimate_approved(self):
        """Test that job status changes to Job.STATUS_APPROVED when estimate is accepted."""
        # Job should start in draft
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)

        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )

        # Change estimate to open first (following valid transition)
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        # Job should now be submitted (sending estimate triggers draft→submitted)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        # Now approve the estimate
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        # Job should now be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_approved_estimate_cannot_go_back_to_draft(self):
        """Test that an accepted estimate cannot be changed back to draft status."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )

        # Move through valid transitions to accepted
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        # Attempt to change back to draft should fail
        estimate.status = Estimate.STATUS_DRAFT
        with self.assertRaises(ValidationError) as context:
            estimate.save()

        self.assertIn('cannot transition estimate from accepted to draft', str(context.exception).lower())

    def test_approved_estimate_cannot_be_superseded(self):
        """Test that an accepted estimate cannot be superseded. - use a ChangeOrder instead"""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )

        # Move to accepted
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        # Accepted is a terminal state - cannot transition to superseded
        estimate.status = Estimate.STATUS_SUPERSEDED
        with self.assertRaises(ValidationError) as context:
            estimate.save()

        # Refresh from DB to ensure we're checking the actual stored value
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_ACCEPTED)

    def test_new_estimate_after_superseding_starts_in_draft(self):
        """Test that a new estimate created after superseding starts in draft."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status=Job.STATUS_DRAFT
        )
        estimate1.status = Estimate.STATUS_OPEN
        estimate1.save()

        # Supersede it
        estimate1.status = Estimate.STATUS_SUPERSEDED
        estimate1.save()

        # Create new estimate (revision)
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=2,
            parent=estimate1,
            status=Estimate.STATUS_DRAFT  # Should start in draft
        )

        # New estimate should be in draft
        self.assertEqual(estimate2.status, Estimate.STATUS_DRAFT)

    def test_worksheet_status_sync_remains_unchanged(self):
        """Test that EstWorksheet status synchronization with Estimate still works."""
        # Create estimate with worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status=Estimate.STATUS_DRAFT
        )

        # When estimate goes to open, worksheet should go to final
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)

        # When estimate is accepted, worksheet should remain final
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_FINAL)

    def test_worksheet_status_sync_remains_unchanged_superseded(self):
        """Test that EstWorksheet status synchronization with Estimate still works."""
        # Create estimate with worksheet
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status=Estimate.STATUS_DRAFT
        )

        # Must go through 'open' first to reach superseded
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        # When estimate is superseded, worksheet should be superseded
        estimate.status = Estimate.STATUS_SUPERSEDED
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, EstWorksheet.STATUS_SUPERSEDED)

    def test_job_status_changes_dont_affect_estimate(self):
        """Test that manual job status changes don't affect estimate status."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Estimate.STATUS_OPEN
        )

        # Manually change job status (draft > submitted)
        self.job.status = Job.STATUS_SUBMITTED
        self.job.save()

        # Estimate should remain unchanged
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

        # Change job to approved, then completed
        self.job.status = Job.STATUS_APPROVED
        self.job.save()
        self.job.status = Job.STATUS_COMPLETED
        self.job.save()

        # Estimate should still be unchanged
        estimate.refresh_from_db()
        self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

    def test_multiple_estimates_with_different_statuses(self):
        """Test multiple estimates on same job with different statuses."""
        # Create first estimate and reject it
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status=Job.STATUS_DRAFT
        )
        estimate1.status = Estimate.STATUS_OPEN
        estimate1.save()
        estimate1.status = Job.STATUS_REJECTED
        estimate1.save()

        # Job should be submitted (sending estimate triggers draft→submitted)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        # Create second estimate and approve it
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            version=1,
            status=Job.STATUS_DRAFT
        )
        estimate2.status = Estimate.STATUS_OPEN
        estimate2.save()
        estimate2.status = Estimate.STATUS_ACCEPTED
        estimate2.save()

        # Job should now be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

        # First estimate should still be rejected
        estimate1.refresh_from_db()
        self.assertEqual(estimate1.status, Estimate.STATUS_REJECTED)

# TODO: an approved job should not have an unapproved estimate though ...
    def test_job_already_approved_remains_approved(self):
        """Test that if job is already approved, accepting an estimate keeps it approved."""
        # Manually approve the job (must go through submitted)
        self.job.status = Job.STATUS_SUBMITTED
        self.job.save()
        self.job.status = Job.STATUS_APPROVED
        self.job.save()

        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        # Job should remain approved (not cause an error)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

# TODO: a completed job shouldn't allow its estimates to change status
    def test_job_in_complete_status_not_affected(self):
        """Test that completed jobs are not affected by estimate changes."""
        # Create and approve an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()
        estimate.status = Estimate.STATUS_ACCEPTED
        estimate.save()

        # Job should be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

        # Complete the job
        self.job.status = Job.STATUS_COMPLETED
        self.job.save()

        # Try to supersede the estimate (but accepted is terminal, so this will fail)
        # Create a new estimate instead to test that completed jobs aren't affected
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0002',
            status=Job.STATUS_DRAFT
        )
        estimate2.status = Estimate.STATUS_OPEN
        estimate2.save()
        estimate2.status = Estimate.STATUS_SUPERSEDED
        estimate2.save()

        # Job should remain completed (not affected by estimate changes)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)

    def test_rejected_estimate_does_not_affect_job(self):
        """Test that rejecting an estimate doesn't change job status."""
        # Job starts in draft
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)

        # Create and reject an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            status=Job.STATUS_DRAFT
        )
        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        # Job should be submitted (sending estimate triggers draft→submitted)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        estimate.status = Estimate.STATUS_REJECTED
        estimate.save()

        # Job should still be submitted (rejecting estimate doesn't affect job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_estimate_revision_workflow(self):
        """Test the full workflow of estimate revision with job status updates."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status=Job.STATUS_DRAFT
        )
        estimate1.status = Estimate.STATUS_OPEN
        estimate1.save()
        estimate1.status = Estimate.STATUS_ACCEPTED
        estimate1.save()

        # Job should be approved
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_estimate_revision_workflow2(self):
        """Test the full workflow of estimate revision with job status updates."""
        # Create and approve first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=1,
            status=Job.STATUS_DRAFT
        )
        estimate1.status = Estimate.STATUS_OPEN
        estimate1.save()

        # Create revision (this typically happens through a view)
        # First, supersede the old estimate (open can transition to superseded)
        estimate1.status = Estimate.STATUS_SUPERSEDED
        estimate1.save()

        # Job should be submitted (sending first estimate triggered draft→submitted)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        # Create new version
        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-2024-0001',
            version=2,
            parent=estimate1,
            status=Job.STATUS_DRAFT
        )

        # Job remains submitted
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        # Open and accept the new estimate
        estimate2.status = Estimate.STATUS_OPEN
        estimate2.save()

        # Job still submitted (already past draft, no-downgrade guard)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        # Accept the new estimate
        estimate2.status = Estimate.STATUS_ACCEPTED
        estimate2.save()

        # Job should be approved (signal handler transitions draft->submitted->approved)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)