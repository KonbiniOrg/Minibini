"""Tests for creating estimates directly from jobs"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.jobs.models import Job, Estimate
from apps.contacts.models import Contact
from apps.core.models import Configuration


class EstimateCreationFromJobTests(TestCase):
    """Test creating estimates directly from job pages."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

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

    def test_estimate_create_for_job_get(self):
        """Test GET request creates estimate directly and redirects."""
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Should redirect to estimate detail page after creation
        self.assertEqual(response.status_code, 302)

        # Check estimate was created
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)
        self.assertTrue(estimate.estimate_number.startswith('EST-'))
        self.assertEqual(estimate.status, 'draft')
        self.assertEqual(estimate.version, 1)

    def test_estimate_create_for_job_post(self):
        """Test POST request creates estimate directly (same as GET)."""
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.post(url)

        # Check redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Check estimate was created with defaults
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)
        # Verify auto-generated estimate number follows pattern
        self.assertTrue(estimate.estimate_number.startswith('EST-'))
        self.assertEqual(estimate.status, 'draft')
        self.assertEqual(estimate.version, 1)
        self.assertEqual(estimate.job, self.job)

    def test_estimate_versioning(self):
        """Test that versioning works when revising an estimate."""
        # Create first estimate directly
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Get the created estimate and mark it as open
        estimate = Estimate.objects.filter(job=self.job).first()
        estimate_number = estimate.estimate_number  # Store the auto-generated number
        estimate.status = 'open'
        estimate.save()

        # Now revise it to create version 2
        url = reverse('jobs:estimate_revise', args=[estimate.estimate_id])
        response = self.client.post(url)

        # Check both estimates exist with correct versions
        estimates = Estimate.objects.filter(job=self.job, estimate_number=estimate_number).order_by('version')
        self.assertEqual(estimates.count(), 2)
        self.assertEqual(estimates[0].version, 1)
        self.assertEqual(estimates[1].version, 2)

    def test_estimate_number_auto_generated(self):
        """Test that estimate number is auto-generated (not user-provided)."""
        # Create estimate directly
        url = reverse('jobs:estimate_create_for_job', args=[self.job.job_id])
        response = self.client.get(url)

        # Verify estimate was created with auto-generated number
        estimate = Estimate.objects.filter(job=self.job).first()
        self.assertIsNotNone(estimate)
        self.assertTrue(estimate.estimate_number.startswith('EST-'))
        # Verify it follows the pattern EST-YYYY-NNNN
        self.assertRegex(estimate.estimate_number, r'^EST-\d{4}-\d{4}$')