from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class JobCreateViewTest(TestCase):
    def setUp(self):
        self.client = Client()

        # Create contacts with proper fields
        self.contact1 = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            work_number="555-1234"
        )
        self.contact2 = Contact.objects.create(
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
            mobile_number="555-5678"
        )

        # Create a business with default contact for testing business selection
        self.business1 = Business.objects.create(
            business_name="Test Company Inc",
            default_contact=self.contact1
        )
        self.contact1.business = self.business1
        self.contact1.save()

        # Create another contact for the business
        self.contact3 = Contact.objects.create(
            first_name="Bob",
            last_name="Johnson",
            email="bob.johnson@example.com",
            work_number="555-9999",
            business=self.business1
        )

        self.url = reverse('jobs:create')

        # Create Configuration for number generation
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

    def test_job_create_view_get(self):
        """Test GET request to job creation form"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/job_create.html')
        self.assertContains(response, 'Create New Job')

    def test_job_create_view_get_with_preselected_contact(self):
        """Test GET request with pre-selected contact from query parameter"""
        response = self.client.get(f"{self.url}?contact_id={self.contact1.contact_id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")
        # Check that the form has the contact pre-selected
        form = response.context['form']
        self.assertEqual(form.fields['contact'].initial, self.contact1)

    def test_job_create_view_post_success(self):
        """Test successful POST request to create a new job"""
        before_creation = timezone.now()

        post_data = {
            # job_number is auto-generated, not posted
            'contact': self.contact1.contact_id,
            'description': 'Test job description',
            'customer_po_number': 'PO-12345',
            # due_date is optional
        }

        response = self.client.post(self.url, data=post_data)

        # Check that we redirect to the job detail page
        self.assertEqual(response.status_code, 302)

        # Verify the job was created with auto-generated number
        job = Job.objects.filter(contact=self.contact1).first()
        self.assertIsNotNone(job)

        # Check job number follows pattern JOB-YYYY-####
        self.assertTrue(job.job_number.startswith('JOB-'))
        year = timezone.now().year
        self.assertIn(str(year), job.job_number)

        # Check all required fields
        self.assertEqual(job.contact, self.contact1)
        self.assertEqual(job.description, 'Test job description')
        self.assertEqual(job.customer_po_number, 'PO-12345')

        # Check defaults
        self.assertEqual(job.status, 'draft')  # Must start in draft
        self.assertIsNotNone(job.created_date)  # Must have timestamp
        self.assertGreaterEqual(job.created_date, before_creation)  # Must be current
        self.assertIsNone(job.due_date)
        self.assertIsNone(job.completed_date)

    def test_job_create_with_due_date(self):
        """Test creating a job with a due date"""
        due_date = timezone.now().date() + timezone.timedelta(days=7)

        post_data = {
            # job_number is auto-generated
            'contact': self.contact1.contact_id,
            'description': 'Job with due date',
            'due_date': due_date.strftime('%Y-%m-%d'),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        job = Job.objects.filter(description='Job with due date').first()
        self.assertIsNotNone(job)
        self.assertIsNotNone(job.due_date)
        # Check the date matches (converted to date for comparison)
        self.assertEqual(job.due_date.date(), due_date)

    def test_job_create_missing_contact_fails(self):
        """Test that job creation fails without a contact"""
        post_data = {
            # job_number is auto-generated
            # contact is missing
            'description': 'This should fail',
        }

        response = self.client.post(self.url, data=post_data)

        # Should not redirect (stays on form with errors)
        self.assertEqual(response.status_code, 200)

        # Check form in context has errors
        form = response.context['form']
        self.assertIn('contact', form.errors)

        # Verify job was not created
        self.assertEqual(Job.objects.filter(contact=self.contact1).count(), 0)

    def test_job_number_auto_generated_even_if_missing(self):
        """Test that job number is auto-generated even if not provided in POST"""
        post_data = {
            # job_number is NOT in POST (will be auto-generated)
            'contact': self.contact1.contact_id,
            'description': 'Auto-generated number test',
        }

        response = self.client.post(self.url, data=post_data)

        # Should succeed and redirect
        self.assertEqual(response.status_code, 302)

        # Verify job was created with auto-generated number
        job = Job.objects.filter(description='Auto-generated number test').first()
        self.assertIsNotNone(job)
        self.assertTrue(job.job_number.startswith('JOB-'))

    def test_job_create_from_contact_detail_link(self):
        """Test that the link from contact detail page pre-selects the contact"""
        # Simulate coming from contact detail page
        contact_detail_url = reverse('contacts:contact_detail', args=[self.contact2.contact_id])

        # Get the job creation form with pre-selected contact
        response = self.client.get(f"{self.url}?contact_id={self.contact2.contact_id}",
                                  HTTP_REFERER=contact_detail_url)

        self.assertEqual(response.status_code, 200)

        # Check that the correct contact is pre-selected
        form = response.context['form']
        self.assertEqual(form.fields['contact'].initial, self.contact2)

        # Also verify context has the initial_contact
        self.assertEqual(response.context['initial_contact'], self.contact2)

    def test_job_number_not_in_form(self):
        """Test that job number is not shown in the form (assigned on save)"""
        response = self.client.get(self.url)
        form = response.context['form']

        # Job number should not be in form fields
        self.assertNotIn('job_number', form.fields)
        self.assertNotIn('job_number_preview', form.fields)

    def test_job_create_redirect_to_detail(self):
        """Test that successful creation redirects to job detail page"""
        post_data = {
            # job_number is auto-generated
            'contact': self.contact1.contact_id,
            'description': 'Test redirect',
        }

        response = self.client.post(self.url, data=post_data)

        # Get the created job
        job = Job.objects.filter(description='Test redirect').first()
        self.assertIsNotNone(job)

        # Check redirect URL
        expected_url = reverse('jobs:detail', args=[job.job_id])
        self.assertRedirects(response, expected_url)

    def test_job_always_starts_in_draft_status(self):
        """Test that all new jobs start in draft status regardless of input"""
        # Even if someone tries to set a different status, it should be draft
        post_data = {
            # job_number is auto-generated
            'contact': self.contact1.contact_id,
            'status': 'approved',  # Try to set non-draft status
            'description': 'Status test',
        }

        response = self.client.post(self.url, data=post_data)

        job = Job.objects.filter(description='Status test').first()
        self.assertIsNotNone(job)
        # Must still be draft regardless of attempted status
        self.assertEqual(job.status, 'draft')