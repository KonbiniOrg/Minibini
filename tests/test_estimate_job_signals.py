from decimal import Decimal
from django.test import TestCase
from apps.core.models import Configuration, User, AppState
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.estimates.models import Estimate, EstimateLineItem
from apps.invoicing.models import Invoice, InvoiceLineItem


class EstimateSentJobSubmittedTest(TestCase):
    """When an Estimate is sent (draft → open), its Job should move to submitted."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='est_expire_days', value='30')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
            status=Job.STATUS_DRAFT,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-TEST-0001',
            status=Estimate.STATUS_DRAFT,
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )

    def test_job_moves_to_submitted_when_estimate_sent(self):
        self.assertEqual(self.job.status, Job.STATUS_DRAFT)
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_job_stays_submitted_if_already_submitted(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_SUBMITTED)
        self.job.refresh_from_db()
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

    def test_job_not_affected_if_already_approved(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_APPROVED)
        self.job.refresh_from_db()
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_accepted_estimate_skips_double_transition(self):
        """Once sent→submitted works, acceptance should be a single submitted→approved."""
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_SUBMITTED)

        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)


class LastInvoicePaidJobCompletedTest(TestCase):
    """When all Invoices for a Job are paid, the Job should move to completed."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', contact=self.contact,
            status=Job.STATUS_APPROVED,
        )

    def test_job_completed_when_single_invoice_paid(self):
        inv = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv, description='Work', price=Decimal('100.00'))
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
        self.assertIsNotNone(self.job.completed_date)

    def test_job_not_completed_when_one_invoice_still_open(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv1, description='Work', price=Decimal('100.00'))
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv2, description='More work', price=Decimal('200.00'))
        inv1.status = Invoice.STATUS_PAID
        inv1.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_job_completed_when_last_invoice_paid(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_PAID)
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv2, description='More work', price=Decimal('200.00'))
        inv2.status = Invoice.STATUS_PAID
        inv2.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)

    def test_cancelled_invoices_ignored(self):
        inv1 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv1, description='Work', price=Decimal('100.00'))
        inv2 = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0002', status=Invoice.STATUS_CANCELLED)
        inv1.status = Invoice.STATUS_PAID
        inv1.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)

    def test_already_completed_job_not_affected(self):
        Job.objects.filter(pk=self.job.pk).update(status=Job.STATUS_COMPLETED)
        self.job.refresh_from_db()
        inv = Invoice.objects.create(job=self.job, invoice_number='INV-TEST-0001', status=Invoice.STATUS_OPEN)
        InvoiceLineItem.objects.create(invoice=inv, description='Work', price=Decimal('100.00'))
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_COMPLETED)
