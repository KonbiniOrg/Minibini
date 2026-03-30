from decimal import Decimal
from django.test import TestCase
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.pdf import generate_job_statement_pdf
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class JobStatementPDFTest(TestCase):
    """Test job statement PDF generation."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
        )
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001', name='Widget Assembly')
        self.invoice = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=2, price=Decimal('100.00'),
            description='CNC part A', accounting_category=self.cat_cnc,
        )

    def test_generates_pdf_bytes(self):
        """generate_job_statement_pdf returns bytes."""
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)

    def test_pdf_starts_with_pdf_header(self):
        """PDF output starts with %PDF magic bytes."""
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_pdf_generation_succeeds(self):
        """PDF should be generatable without errors."""
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertIsNotNone(pdf_bytes)
