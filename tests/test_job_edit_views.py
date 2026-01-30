"""
Tests for Job editing functionality with state-based field restrictions.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class JobEditDraftStatusTest(TestCase):
    """Test editing jobs in Draft status"""

    def setUp(self):
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

        # Create two contacts
        self.contact1 = Contact.objects.create(first_name='Test Customer 1', last_name='', email='test.customer1@test.com')
        self.contact2 = Contact.objects.create(first_name='Test Customer 2', last_name='', email='test.customer2@test.com')

        # Create a draft job
        self.job = Job.objects.create(
            job_number='JOB-2025-0001',
            contact=self.contact1,
            status='draft',
            description='Original description',
            customer_po_number='PO-001',
            due_date=timezone.now().date() + timedelta(days=30)
        )
        self.url = reverse('jobs:edit', args=[self.job.job_id])

    def test_draft_job_can_change_contact(self):
        """Draft jobs can change contact"""
        response = self.client.post(self.url, {
            'contact': self.contact2.contact_id,
            'status': 'draft',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-001',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)  # Redirect on success
        self.job.refresh_from_db()
        self.assertEqual(self.job.contact.contact_id, self.contact2.contact_id)

    def test_draft_job_can_change_status(self):
        """Draft jobs can change status to submitted"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'submitted',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-001',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'submitted')

    def test_draft_job_cannot_change_created_date(self):
        """Draft jobs cannot change created_date (it's immutable)"""
        original_created_date = self.job.created_date
        new_created_date = timezone.now() - timedelta(days=5)
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'draft',
            'created_date': new_created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-001',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        # created_date should not have changed (protected by model)
        self.assertEqual(
            self.job.created_date.strftime('%Y-%m-%d %H:%M'),
            original_created_date.strftime('%Y-%m-%d %H:%M')
        )

    def test_draft_job_can_change_description(self):
        """Draft jobs can change description"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'draft',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Updated description',
            'customer_po_number': 'PO-001',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.description, 'Updated description')

    def test_draft_job_can_change_due_date(self):
        """Draft jobs can change due_date"""
        new_due_date = timezone.now().date() + timedelta(days=60)
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'draft',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-001',
            'due_date': new_due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        # Compare dates only (due_date is stored as datetime)
        self.assertEqual(self.job.due_date.date(), new_due_date)

    def test_draft_job_can_change_customer_po_number(self):
        """Draft jobs can change customer_po_number"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'draft',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-999',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_po_number, 'PO-999')

    def test_draft_job_edit_form_loads(self):
        """GET request shows form for draft job"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertIn('job', response.context)
        # Check that no fields are disabled in draft status
        form = response.context['form']
        self.assertFalse(form.fields['contact'].disabled)
        self.assertFalse(form.fields['created_date'].disabled)


class JobEditApprovedStatusTest(TestCase):
    """Test editing jobs in Approved status"""

    def setUp(self):
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

        # Create two contacts
        self.contact1 = Contact.objects.create(first_name='Test Customer 1', last_name='', email='test.customer1@test.com')
        self.contact2 = Contact.objects.create(first_name='Test Customer 2', last_name='', email='test.customer2@test.com')

        # Create an approved job
        self.job = Job.objects.create(
            job_number='JOB-2025-0002',
            contact=self.contact1,
            status='approved',
            description='Original description',
            customer_po_number='PO-002',
            due_date=timezone.now().date() + timedelta(days=30)
        )
        self.url = reverse('jobs:edit', args=[self.job.job_id])

    def test_approved_job_cannot_change_contact(self):
        """Approved jobs cannot change contact"""
        original_contact = self.job.contact

        response = self.client.post(self.url, {
            'contact': self.contact2.contact_id,
            'status': 'approved',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-002',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.job.refresh_from_db()
        # Contact should not have changed
        self.assertEqual(self.job.contact.contact_id, original_contact.contact_id)

    def test_approved_job_cannot_change_created_date(self):
        """Approved jobs cannot change created_date"""
        original_created_date = self.job.created_date
        new_created_date = timezone.now() - timedelta(days=10)

        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'approved',
            'created_date': new_created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-002',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.job.refresh_from_db()
        # Created date should not have changed (compare to within 1 second)
        self.assertEqual(
            self.job.created_date.strftime('%Y-%m-%d %H:%M'),
            original_created_date.strftime('%Y-%m-%d %H:%M')
        )

    def test_approved_job_can_change_status(self):
        """Approved jobs can change status to completed"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'completed',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-002',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'completed')

    def test_approved_job_can_change_description(self):
        """Approved jobs can change description"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'approved',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Updated description for approved job',
            'customer_po_number': 'PO-002',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.description, 'Updated description for approved job')

    def test_approved_job_can_change_due_date(self):
        """Approved jobs can change due_date"""
        new_due_date = timezone.now().date() + timedelta(days=90)
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'approved',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-002',
            'due_date': new_due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        # Compare dates only (due_date is stored as datetime)
        self.assertEqual(self.job.due_date.date(), new_due_date)

    def test_approved_job_can_change_customer_po_number(self):
        """Approved jobs can change customer_po_number"""
        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'approved',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-NEW-001',
            'due_date': self.job.due_date.strftime('%Y-%m-%d')
        })

        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_po_number, 'PO-NEW-001')

    def test_approved_job_form_has_disabled_fields(self):
        """Form for approved job has contact and created_date disabled"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.fields['contact'].disabled)
        self.assertTrue(form.fields['created_date'].disabled)
        self.assertFalse(form.fields['status'].disabled)
        self.assertFalse(form.fields['description'].disabled)


class JobEditRejectedStatusTest(TestCase):
    """Test editing jobs in Rejected status"""

    def setUp(self):
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

        # Create two contacts
        self.contact1 = Contact.objects.create(first_name='Test Customer 1', last_name='', email='test.customer1@test.com')
        self.contact2 = Contact.objects.create(first_name='Test Customer 2', last_name='', email='test.customer2@test.com')

        # Create a rejected job
        self.job = Job.objects.create(
            job_number='JOB-2025-0005',
            contact=self.contact1,
            status='rejected',
            description='Original description',
            customer_po_number='PO-005'
        )
        self.url = reverse('jobs:edit', args=[self.job.job_id])

    def test_rejected_job_cannot_change_status(self):
        """Rejected jobs cannot change status (terminal state)"""
        original_status = self.job.status

        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'draft',  # Try to change status back to draft
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-005',
        })

        # The form should show an error (status code 200) instead of redirecting (302)
        # because rejected is a terminal state
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, original_status)  # Status should not change

    def test_rejected_job_cannot_change_contact(self):
        """Rejected jobs cannot change contact"""
        original_contact = self.job.contact

        response = self.client.post(self.url, {
            'contact': self.contact2.contact_id,
            'status': 'rejected',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-005',
        })

        self.job.refresh_from_db()
        self.assertEqual(self.job.contact.contact_id, original_contact.contact_id)

    def test_rejected_job_cannot_change_description(self):
        """Rejected jobs cannot change description"""
        original_description = self.job.description

        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'rejected',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Attempted to change description',
            'customer_po_number': 'PO-005',
        })

        self.job.refresh_from_db()
        self.assertEqual(self.job.description, original_description)

    def test_rejected_job_cannot_change_customer_po_number(self):
        """Rejected jobs cannot change customer_po_number"""
        original_po = self.job.customer_po_number

        response = self.client.post(self.url, {
            'contact': self.contact1.contact_id,
            'status': 'rejected',
            'created_date': self.job.created_date.strftime('%Y-%m-%dT%H:%M'),
            'description': 'Original description',
            'customer_po_number': 'PO-CHANGED',
        })

        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_po_number, original_po)

    def test_rejected_job_form_all_fields_disabled_except_status(self):
        """Form for rejected job has all fields disabled except status"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.fields['contact'].disabled)
        self.assertTrue(form.fields['created_date'].disabled)
        self.assertTrue(form.fields['description'].disabled)
        self.assertTrue(form.fields['customer_po_number'].disabled)
        self.assertTrue(form.fields['due_date'].disabled)
        self.assertFalse(form.fields['status'].disabled)


class JobEditCompleteStatusTest(TestCase):
    """Test editing jobs in Complete status"""

    def setUp(self):
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

        # Create contact
        self.contact1 = Contact.objects.create(first_name='Test Customer 1', last_name='', email='test.customer1@test.com')

        # Create a completed job
        self.job = Job.objects.create(
            job_number='JOB-2025-0006',
            contact=self.contact1,
            status='completed',
            description='Completed job',
            completed_date=timezone.now()
        )
        self.url = reverse('jobs:edit', args=[self.job.job_id])

    def test_complete_job_all_fields_disabled(self):
        """Complete jobs have all fields disabled"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.fields['contact'].disabled)
        self.assertTrue(form.fields['created_date'].disabled)
        self.assertTrue(form.fields['description'].disabled)
        self.assertTrue(form.fields['customer_po_number'].disabled)
        self.assertTrue(form.fields['due_date'].disabled)
        self.assertTrue(form.fields['status'].disabled)
