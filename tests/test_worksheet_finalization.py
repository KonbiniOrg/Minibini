"""
Test that worksheets are properly finalized after generating estimates.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, Estimate, EstWorksheet, Task, TaskTemplate, TaskMapping
from apps.core.models import Configuration
from apps.contacts.models import Contact
from apps.jobs.services import EstimateGenerationService
from decimal import Decimal

User = get_user_model()


class WorksheetFinalizationTests(TestCase):
    """Test that worksheets are finalized when generating estimates."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.client = Client()

        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass')

        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create task mapping for test
        self.task_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='TEST',
            breakdown_of_task='Test task',
            line_item_name='Test Labor',
            line_item_description='Test labor description'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            units='hours',
            rate=Decimal('50.00')
        )

        # Create draft worksheet
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        # Add a task to the worksheet
        self.task = Task.objects.create(
            est_worksheet=self.worksheet,
            template=self.task_template,
            name='Test Task',
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.0')
        )

    def test_worksheet_marked_final_after_generating_estimate(self):
        """Test that worksheet is marked as final after generating an estimate."""
        # Verify worksheet starts as draft
        self.assertEqual(self.worksheet.status, 'draft')

        # Generate estimate via POST request
        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url, follow=True)

        # Check response redirects to estimate detail
        self.assertEqual(response.status_code, 200)

        # Reload worksheet from database
        self.worksheet.refresh_from_db()

        # Verify worksheet is now final
        self.assertEqual(self.worksheet.status, 'final')

        # Verify an estimate was created
        estimates = Estimate.objects.filter(job=self.job)
        self.assertEqual(estimates.count(), 1)

    def test_cannot_generate_estimate_from_final_worksheet(self):
        """Test that generating an estimate from a final worksheet is rejected."""
        # Mark worksheet as final
        self.worksheet.status = 'final'
        self.worksheet.save()

        # Attempt to generate estimate
        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot generate estimate from a final worksheet' in str(m) for m in messages))

        # Verify no estimate was created
        estimates = Estimate.objects.filter(job=self.job)
        self.assertEqual(estimates.count(), 0)

    def test_cannot_generate_estimate_from_superseded_worksheet(self):
        """Test that generating an estimate from a superseded worksheet is rejected."""
        # Mark worksheet as superseded
        self.worksheet.status = 'superseded'
        self.worksheet.save()

        # Attempt to generate estimate
        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot generate estimate from a superseded worksheet' in str(m) for m in messages))

        # Verify no estimate was created
        estimates = Estimate.objects.filter(job=self.job)
        self.assertEqual(estimates.count(), 0)

    def test_generate_estimate_link_hidden_for_final_worksheet(self):
        """Test that the Generate Estimate link is hidden for final worksheets."""
        # Mark worksheet as final
        self.worksheet.status = 'final'
        self.worksheet.save()

        # Get worksheet detail page
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that Generate Estimate link is not present
        self.assertNotContains(response, 'Generate Estimate')

        # Check that Revise Worksheet button is present instead
        self.assertContains(response, 'Revise Worksheet')

    def test_generate_estimate_link_visible_for_draft_worksheet(self):
        """Test that the Generate Estimate link is visible for draft worksheets."""
        # Worksheet is already draft from setUp
        self.assertEqual(self.worksheet.status, 'draft')

        # Get worksheet detail page
        url = reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check that Generate Estimate link is present
        self.assertContains(response, 'Generate Estimate')

        # Check that Revise Worksheet button is not present
        self.assertNotContains(response, '<button type="submit">Revise Worksheet</button>')

    def test_cannot_generate_multiple_estimates_from_same_worksheet(self):
        """Test that a worksheet cannot generate multiple estimates."""
        # Generate first estimate
        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response1 = self.client.post(url, follow=True)

        # Check first estimate was created
        self.assertEqual(response1.status_code, 200)
        estimates = Estimate.objects.filter(job=self.job)
        self.assertEqual(estimates.count(), 1)

        # Reload worksheet
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.status, 'final')

        # Attempt to generate second estimate
        response2 = self.client.post(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response2,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response2.wsgi_request._messages)
        self.assertTrue(any('Cannot generate estimate from a final worksheet' in str(m) for m in messages))

        # Verify still only one estimate exists
        estimates = Estimate.objects.filter(job=self.job)
        self.assertEqual(estimates.count(), 1)

    def test_get_request_shows_confirmation_page_for_draft(self):
        """Test that GET request shows confirmation page for draft worksheet."""
        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/estworksheet_generate_estimate.html')

        # Worksheet should still be draft
        self.worksheet.refresh_from_db()
        self.assertEqual(self.worksheet.status, 'draft')

    def test_get_request_rejected_for_final_worksheet(self):
        """Test that GET request is rejected for final worksheet."""
        # Mark worksheet as final
        self.worksheet.status = 'final'
        self.worksheet.save()

        url = reverse('jobs:estworksheet_generate_estimate', args=[self.worksheet.est_worksheet_id])
        response = self.client.get(url)

        # Should redirect back to worksheet detail
        self.assertRedirects(
            response,
            reverse('jobs:estworksheet_detail', args=[self.worksheet.est_worksheet_id])
        )

        # Check for error message
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('Cannot generate estimate from a final worksheet' in str(m) for m in messages))


class WorksheetEstimateIntegrationTests(TestCase):
    """Test the integration between worksheets and estimates."""

    def setUp(self):
        """Set up test data."""
        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='contact@test.com'
        )

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-TEST-001',
            contact=self.contact,
            status='approved'
        )

        # Create task mapping
        self.task_mapping = TaskMapping.objects.create(
            step_type='labor',
            mapping_strategy='direct',
            task_type_id='TEST',
            breakdown_of_task='Test task',
            line_item_name='Test Labor',
            line_item_description='Test labor description'
        )

        # Create task template
        self.task_template = TaskTemplate.objects.create(
            template_name='Test Template',
            task_mapping=self.task_mapping,
            units='hours',
            rate=Decimal('50.00')
        )

        self.service = EstimateGenerationService()

    def test_worksheet_workflow_from_draft_to_final(self):
        """Test the complete workflow from draft worksheet to final with estimate."""
        # Create draft worksheet
        worksheet = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=1
        )

        # Add task
        Task.objects.create(
            est_worksheet=worksheet,
            template=self.task_template,
            name='Test Task',
            units='hours',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.0')
        )

        # Verify worksheet is draft
        self.assertEqual(worksheet.status, 'draft')

        # Generate estimate using service
        estimate = self.service.generate_estimate_from_worksheet(worksheet)

        # Manually mark worksheet as final (simulating what the view does)
        worksheet.status = 'final'
        worksheet.save()

        # Verify worksheet is final
        worksheet.refresh_from_db()
        self.assertEqual(worksheet.status, 'final')

        # Verify estimate was created
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.job, self.job)

        # Verify line items were created
        self.assertGreater(estimate.estimatelineitem_set.count(), 0)

    def test_revised_worksheet_can_generate_new_estimate(self):
        """Test that a revised worksheet (from a final one) can generate a new estimate."""
        # Create and finalize first worksheet
        worksheet_v1 = EstWorksheet.objects.create(
            job=self.job,
            status='final',
            version=1
        )

        # Create revised worksheet
        worksheet_v2 = EstWorksheet.objects.create(
            job=self.job,
            status='draft',
            version=2,
            parent=worksheet_v1
        )

        # Add task to v2
        Task.objects.create(
            est_worksheet=worksheet_v2,
            template=self.task_template,
            name='Test Task v2',
            units='hours',
            rate=Decimal('60.00'),
            est_qty=Decimal('3.0')
        )

        # Generate estimate from v2
        estimate = self.service.generate_estimate_from_worksheet(worksheet_v2)

        # Verify estimate was created
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.job, self.job)

        # Mark v2 as final
        worksheet_v2.status = 'final'
        worksheet_v2.save()

        # Verify v2 is final
        worksheet_v2.refresh_from_db()
        self.assertEqual(worksheet_v2.status, 'final')