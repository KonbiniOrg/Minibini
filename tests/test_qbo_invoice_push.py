from django.test import TestCase
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class InvoiceQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Invoice model."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(job_number='JOB-2026-0001', contact=self.contact)

    def test_invoice_has_qbo_id(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_id, '')

    def test_invoice_has_qbo_payment_status(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_payment_status, '')

    def test_invoice_has_qbo_amount_paid(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.qbo_amount_paid)

    def test_invoice_can_store_qbo_data(self):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_id = '12345'
        inv.qbo_payment_status = 'Paid'
        inv.qbo_amount_paid = 4250.00
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.qbo_id, '12345')
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, 4250.00)

    def test_customer_business_chain(self):
        """Can traverse Invoice → Job → Contact → Business."""
        inv = Invoice.objects.create(job=self.job)
        business = inv.job.contact.business
        self.assertEqual(business.business_name, 'Acme Corp')
