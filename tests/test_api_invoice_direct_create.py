from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.invoicing.models import Invoice


class InvoiceDirectCreateAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.billable_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )

    def test_direct_create_returns_draft_invoice(self):
        resp = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], Invoice.STATUS_DRAFT)
        self.assertTrue(resp.data['invoice_number'])

    def test_direct_create_is_idempotent_for_existing_draft(self):
        first = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        second = self.client.post('/api/invoices/', {'job': self.billable_job.pk}, format='json')
        self.assertIn(second.status_code, [200, 201])
        self.assertEqual(first.data['invoice_id'], second.data['invoice_id'])
        self.assertEqual(Invoice.objects.filter(job=self.billable_job).count(), 1)

    def test_direct_create_rejected_for_non_billable_job(self):
        draft_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002',
        )
        resp = self.client.post('/api/invoices/', {'job': draft_job.pk}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Invoice.objects.filter(job=draft_job).count(), 0)
