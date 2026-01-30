"""Tests for estimate creation and revision controls."""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.jobs.models import Job, Estimate, EstimateLineItem
from apps.core.models import Configuration
from apps.contacts.models import Contact
from apps.invoicing.models import PriceListItem


class EstimateCreationControlTests(TestCase):
    """Test that only one estimate can be created per job."""

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

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

    def test_can_create_first_estimate(self):
        """Test that first estimate can be created for a job."""
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should create directly and redirect to estimate detail
        self.assertEqual(response.status_code, 302)

        # Estimate should be created with defaults
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.estimate_number, 'EST-2025-0001')
        self.assertEqual(estimate.status, 'draft')
        self.assertEqual(estimate.version, 1)

    def test_cannot_create_second_estimate_draft(self):
        """Test that second estimate cannot be created when draft exists."""
        # Create first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='draft'
        )

        # Try to create second estimate
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should redirect to existing estimate
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[estimate1.estimate_id]))

    def test_cannot_create_second_estimate_open(self):
        """Test that second estimate cannot be created when open estimate exists."""
        # Create first estimate
        estimate1 = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='open'
        )

        # Try to create second estimate
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should redirect to existing estimate
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[estimate1.estimate_id]))

    def test_can_create_estimate_after_superseded(self):
        """Test that new estimate can be created if only superseded exists."""
        # Create superseded estimate
        superseded = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='superseded',
            closed_date=timezone.now()
        )

        # Should be able to create new estimate directly
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should create directly and redirect to estimate detail
        self.assertEqual(response.status_code, 302)

        # New estimate should be created
        new_estimate = Estimate.objects.filter(job=self.job).exclude(status='superseded').first()
        self.assertIsNotNone(new_estimate)
        self.assertEqual(new_estimate.status, 'draft')

    def test_job_detail_shows_create_button_when_no_estimates(self):
        """Test job detail shows create button when no estimates exist."""
        url = reverse('jobs:detail', args=[self.job.job_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Estimate')

    def test_job_detail_hides_create_button_when_estimate_exists(self):
        """Test job detail hides create button when estimate exists."""
        # Create an estimate
        estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='draft'
        )

        url = reverse('jobs:detail', args=[self.job.job_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create New Estimate')


class EstimateRevisionTests(TestCase):
    """Test estimate revision functionality."""

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

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

        # Create an estimate
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-001',
            version=1,
            status='open'
        )

        # Create some line items
        self.price_list_item = PriceListItem.objects.create(
            code='ITEM001',
            units='hour',
            description='Test Item',
            purchase_price=50.00,
            selling_price=100.00
        )

        self.line_item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            price_list_item=self.price_list_item,
            line_number=1,
            qty=5.0,
            units='hour',
            description='Line Item 1',
            price_currency=100.00
        )

        self.line_item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_number=2,
            qty=10.0,
            units='each',
            description='Line Item 2',
            price_currency=50.00
        )

    def test_revise_confirmation_page(self):
        """Test that revise confirmation page shows correctly."""
        url = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Revise Estimate')
        self.assertContains(response, 'EST-001')
        self.assertContains(response, 'v2')  # Next version

    def test_can_revise_open_estimate(self):
        """Test that open estimate can be revised."""
        url = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Should redirect to new estimate
        self.assertEqual(response.status_code, 302)

        # Check new estimate created
        new_estimate = Estimate.objects.filter(
            job=self.job,
            parent=self.estimate
        ).first()

        self.assertIsNotNone(new_estimate)
        self.assertEqual(new_estimate.estimate_number, 'EST-001')
        self.assertEqual(new_estimate.version, 2)
        self.assertEqual(new_estimate.status, 'draft')

        # Check parent marked as superseded
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, 'superseded')
        self.assertIsNotNone(self.estimate.closed_date)

    def test_cannot_revise_draft_estimate(self):
        """Test that draft estimate cannot be revised."""
        # Create a draft estimate (can't transition from open to draft)
        draft_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-002',
            version=1,
            status='draft'
        )

        url = reverse('jobs:estimate_revise', args=[draft_estimate.estimate_id])
        response = self.client.post(url)

        # Should redirect back to estimate
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('jobs:estimate_detail', args=[draft_estimate.estimate_id]))

        # No new estimate should be created
        new_estimate = Estimate.objects.filter(
            job=self.job,
            parent=draft_estimate
        ).first()
        self.assertIsNone(new_estimate)

        # Original should remain draft
        draft_estimate.refresh_from_db()
        self.assertEqual(draft_estimate.status, 'draft')

    def test_line_items_copied_during_revision(self):
        """Test that line items are copied to new revision."""
        url = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        response = self.client.post(url)

        # Get new estimate
        new_estimate = Estimate.objects.filter(
            job=self.job,
            parent=self.estimate
        ).first()

        # Check line items were copied
        new_line_items = EstimateLineItem.objects.filter(estimate=new_estimate)
        self.assertEqual(new_line_items.count(), 2)

        # Check details match
        new_li1 = new_line_items.filter(line_number=1).first()
        self.assertIsNotNone(new_li1)
        self.assertEqual(new_li1.qty, 5.0)
        self.assertEqual(new_li1.units, 'hour')
        self.assertEqual(new_li1.description, 'Line Item 1')
        self.assertEqual(new_li1.price_currency, 100.00)

        new_li2 = new_line_items.filter(line_number=2).first()
        self.assertIsNotNone(new_li2)
        self.assertEqual(new_li2.qty, 10.0)
        self.assertEqual(new_li2.units, 'each')
        self.assertEqual(new_li2.description, 'Line Item 2')
        self.assertEqual(new_li2.price_currency, 50.00)

    def test_revise_button_shows_for_non_draft(self):
        """Test that revise button shows for non-draft estimates."""
        url = reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Revise Estimate')

    def test_revise_button_hidden_for_draft(self):
        """Test that revise button is hidden for draft estimates."""
        # Create a draft estimate (can't transition from open to draft)
        draft_estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-003',
            version=1,
            status='draft'
        )

        url = reverse('jobs:estimate_detail', args=[draft_estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Revise Estimate')

    def test_revise_button_hidden_for_superseded(self):
        """Test that revise button is hidden for superseded estimates."""
        self.estimate.status = 'superseded'
        self.estimate.save()

        url = reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Revise Estimate')

    def test_parent_child_relationships(self):
        """Test that parent-child relationships are properly maintained."""
        # Create first revision
        url = reverse('jobs:estimate_revise', args=[self.estimate.estimate_id])
        self.client.post(url)

        rev1 = Estimate.objects.filter(
            job=self.job,
            version=2
        ).first()

        # Mark rev1 as open and create another revision
        rev1.status = 'open'
        rev1.save()

        url = reverse('jobs:estimate_revise', args=[rev1.estimate_id])
        self.client.post(url)

        rev2 = Estimate.objects.filter(
            job=self.job,
            version=3
        ).first()

        # Check relationships
        self.assertEqual(rev1.parent, self.estimate)
        self.assertEqual(rev2.parent, rev1)

        # Check versions
        self.assertEqual(self.estimate.version, 1)
        self.assertEqual(rev1.version, 2)
        self.assertEqual(rev2.version, 3)

        # Check statuses
        self.estimate.refresh_from_db()
        rev1.refresh_from_db()

        self.assertEqual(self.estimate.status, 'superseded')
        self.assertEqual(rev1.status, 'superseded')
        self.assertEqual(rev2.status, 'draft')


class EstimateWorkflowIntegrationTests(TestCase):
    """Test the complete estimate workflow with creation and revision."""

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

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test@example.com'
        )

        # Create a job
        self.job = Job.objects.create(
            job_number='TEST001',
            description='Test Job',
            contact=self.contact
        )

    def test_complete_workflow(self):
        """Test complete workflow from creation through multiple revisions."""
        # Step 1: Create first estimate directly
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should redirect after creation
        self.assertEqual(response.status_code, 302)

        estimate_v1 = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate_v1)
        self.assertEqual(estimate_v1.version, 1)
        self.assertEqual(estimate_v1.status, 'draft')

        # Step 2: Try to create another - should redirect
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        # Step 3: Mark as open
        estimate_v1.status = 'open'
        estimate_v1.save()

        # Step 4: Revise the estimate
        url = reverse('jobs:estimate_revise', args=[estimate_v1.estimate_id])
        response = self.client.post(url)

        estimate_v2 = Estimate.objects.filter(job=self.job, version=2).first()
        self.assertIsNotNone(estimate_v2)
        self.assertEqual(estimate_v2.status, 'draft')
        self.assertEqual(estimate_v2.parent, estimate_v1)

        # Step 5: Check original is superseded
        estimate_v1.refresh_from_db()
        self.assertEqual(estimate_v1.status, 'superseded')

        # Step 6: Cannot create new estimate while v2 exists
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)