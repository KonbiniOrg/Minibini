from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory


class OpenForJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.approved_job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.draft_job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002')
        self.rejected_job = Job.objects.create(contact=self.contact, status=Job.STATUS_REJECTED, job_number='JOB-2026-0003')

    def test_creates_draft_when_none_exists(self):
        invoice = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.approved_job)

    def test_returns_existing_draft(self):
        first = InvoiceWizardService.open_for_job(self.approved_job)
        second = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(first.pk, second.pk)

    def test_creates_new_draft_alongside_sent_invoice(self):
        # A non-draft invoice on the job doesn't block creating a new draft
        Invoice.objects.create(job=self.approved_job, status=Invoice.STATUS_OPEN)
        draft = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(draft.status, Invoice.STATUS_DRAFT)
        self.assertEqual(Invoice.objects.filter(job=self.approved_job).count(), 2)

    def test_refuses_draft_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.draft_job)

    def test_refuses_rejected_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.rejected_job)
