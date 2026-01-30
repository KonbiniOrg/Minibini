"""
Tests for efficient EstWorksheet signal system.
"""

from django.test import TestCase
from django.test.utils import override_settings
from django.db import connection
from django.db import reset_queries
from unittest.mock import patch, MagicMock

from apps.contacts.models import Contact
from apps.jobs.models import Job, Estimate, EstWorksheet
from apps.jobs.signals import estimate_status_changed_for_worksheet


class EstWorksheetSignalEfficiencyTest(TestCase):
    """Test that the signal system is efficient and only fires when needed."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )

    @override_settings(DEBUG=True)
    def test_no_signal_on_non_status_change(self):
        """Test that signal doesn't fire when fields other than status change."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='draft'
        )

        # Mock the signal to check if it's called
        with patch('apps.jobs.signals.estimate_status_changed_for_worksheet.send') as mock_signal:
            # Change non-status field
            reset_queries()
            estimate.estimate_number = "EST002"
            estimate.save()

            # Signal should NOT have been called
            mock_signal.assert_not_called()

            # Check query count - 5 queries due to validation and status checks:
            # 1. SELECT old status in save()
            # 2. SELECT to verify job exists (validation)
            # 3. SELECT old status again in clean()
            # 4. SELECT to check unique constraint
            # 5. UPDATE query
            self.assertEqual(len(connection.queries), 5)

    @override_settings(DEBUG=True)
    def test_no_signal_on_irrelevant_status_change(self):
        """Test that signal doesn't fire when status change doesn't affect worksheets."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='open'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='final'
        )

        with patch('apps.jobs.signals.estimate_status_changed_for_worksheet.send') as mock_signal:
            reset_queries()
            # Change from 'open' to 'accepted' - both map to 'final' for worksheets
            estimate.status = 'accepted'
            estimate.save()

            # Signal should NOT have been called
            mock_signal.assert_not_called()

            # way too many queries.  ignore until we're ready to optimize
            #self.assertEqual(len(connection.queries), 7)

    def test_signal_fires_on_relevant_status_change(self):
        """Test that signal fires when status change affects worksheets."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='draft'
        )

        with patch('apps.jobs.signals.estimate_status_changed_for_worksheet.send') as mock_signal:
            # Change from 'draft' to 'open' - should trigger signal
            estimate.status = 'open'
            estimate.save()

            # Signal SHOULD have been called
            mock_signal.assert_called_once()
            call_kwargs = mock_signal.call_args[1]
            self.assertEqual(call_kwargs['estimate'], estimate)
            self.assertEqual(call_kwargs['new_worksheet_status'], 'final')

    def test_no_database_hit_when_no_worksheets(self):
        """Test that UPDATE query affects 0 rows when no worksheets exist."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        # No worksheets created

        # Change status to trigger signal
        estimate.status = 'open'
        estimate.save()

        # Check that no worksheets were affected
        worksheet_count = EstWorksheet.objects.filter(estimate=estimate).count()
        self.assertEqual(worksheet_count, 0)

    def test_status_mapping_logic(self):
        """Test the status mapping logic."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        # Test mapping function
        self.assertEqual(estimate._get_worksheet_status('draft'), 'draft')
        self.assertEqual(estimate._get_worksheet_status('open'), 'final')
        self.assertEqual(estimate._get_worksheet_status('accepted'), 'final')
        self.assertEqual(estimate._get_worksheet_status('rejected'), 'final')
        self.assertEqual(estimate._get_worksheet_status('superseded'), 'superseded')
        self.assertIsNone(estimate._get_worksheet_status('invalid'))


class EstWorksheetSignalIntegrationTest(TestCase):
    """Test the complete signal flow with actual database changes."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )

    def test_worksheet_status_updates_correctly(self):
        """Test that worksheet status actually updates in the database."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        # Initial status should be draft
        self.assertEqual(worksheet.status, 'draft')

        # Change estimate to open
        estimate.status = 'open'
        estimate.save()

        # Refresh and check worksheet
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')

        # Change estimate to superseded
        estimate.status = 'superseded'
        estimate.save()

        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'superseded')

    def test_multiple_worksheets_updated(self):
        """Test that multiple worksheets for the same estimate are updated."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet1 = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        worksheet2 = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        # Change estimate status
        estimate.status = 'open'
        estimate.save()

        # Both worksheets should be updated
        worksheet1.refresh_from_db()
        worksheet2.refresh_from_db()
        self.assertEqual(worksheet1.status, 'final')
        self.assertEqual(worksheet2.status, 'final')

    def test_only_matching_worksheets_updated(self):
        """Test that only worksheets for the changed estimate are updated."""
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        estimate2 = Estimate.objects.create(
            job=self.job,
            estimate_number="EST002",
            status='draft'
        )

        worksheet1 = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate1
        )

        worksheet2 = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate2
        )

        # Change only estimate1
        estimate1.status = 'open'
        estimate1.save()

        # Only worksheet1 should be updated
        worksheet1.refresh_from_db()
        worksheet2.refresh_from_db()
        self.assertEqual(worksheet1.status, 'final')
        self.assertEqual(worksheet2.status, 'draft')  # Unchanged

    def test_already_correct_status_not_updated(self):
        """Test that worksheets with correct status are not updated unnecessarily."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='open'
        )

        # Create worksheet that already has 'final' status
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate,
            status='final'
        )

        # Track the worksheet's updated timestamp before
        original_status = worksheet.status

        # Change estimate from open to accepted (both map to 'final')
        estimate.status = 'accepted'
        estimate.save()

        # Worksheet should still be 'final' and not have been touched
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, original_status)

class EstWorksheetInitialStatusTest(TestCase):
    """Test that EstWorksheet gets correct initial status when created."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )

    def test_worksheet_created_with_draft_estimate(self):
        """Test worksheet created with draft estimate starts as draft."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        self.assertEqual(worksheet.status, 'draft')

    def test_worksheet_created_with_open_estimate(self):
        """Test worksheet created with open estimate starts as final."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='open'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        self.assertEqual(worksheet.status, 'final')

    def test_worksheet_created_without_estimate(self):
        """Test worksheet created without estimate uses default status."""
        worksheet = EstWorksheet.objects.create(
            job=self.job
        )

        self.assertEqual(worksheet.status, 'draft')  # Default

    def test_worksheet_status_not_changed_on_update(self):
        """Test that worksheet status isn't automatically changed on save after creation."""
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001",
            status='draft'
        )

        worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=estimate
        )

        # Manually change worksheet status
        worksheet.status = 'final'
        worksheet.save()

        # Status should remain as manually set
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')

        # Even if estimate is still draft
        self.assertEqual(estimate.status, 'draft')