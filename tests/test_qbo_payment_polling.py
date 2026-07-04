from decimal import Decimal
from apps.core.models import JobHistory
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, ScheduledProcessRun, AppState
from apps.qbo.services import QBOPaymentPollingService


class PaymentPollingTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe', email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(business_name='Acme Corp', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001')
        # Move the job to 'approved' so invoice-paid completion has a valid path.
        JobService.update_job(self.job.pk, status=Job.STATUS_SUBMITTED)
        JobService.update_job(self.job.pk, status=Job.STATUS_APPROVED)

    def _open_invoice(self, qbo_id='100'):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        inv.qbo_id = qbo_id
        inv.save()
        return inv

    def _qbo(self, total, balance):
        m = MagicMock()
        m.TotalAmt = total
        m.Balance = balance
        return m

    @patch('apps.qbo.services.QBOService.get_client')
    def test_full_payment_marks_paid_and_caches(self, mock_get_client):
        inv = self._open_invoice('100')
        mock_get_client.return_value = MagicMock()
        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=self._qbo(500.00, 0)):
            stats = QBOPaymentPollingService.poll_all()
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_PAID)
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, Decimal('500.00'))
        self.assertIsNotNone(inv.closed_date)
        self.assertEqual(stats['transitioned'], 1)
        self.assertTrue(JobHistory.objects.filter(
            object_type='invoice', object_id=inv.pk,
            changes__status__new=Invoice.STATUS_PAID,
        ).exists())
        # A paid invoice does not auto-complete a job whose work never
        # happened (no tasks; completion gate requires finished work — see
        # tests/test_completion_gate.py). The polling mechanics above are this
        # test's subject; completion is covered once the job's work is done:
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_partial_payment_marks_partly_paid(self, mock_get_client):
        inv = self._open_invoice('101')
        mock_get_client.return_value = MagicMock()
        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=self._qbo(500.00, 200.00)):
            QBOPaymentPollingService.poll_all()
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_PARTLY_PAID)
        self.assertEqual(inv.qbo_payment_status, 'Partial')
        self.assertEqual(inv.qbo_amount_paid, Decimal('300.00'))

    @patch('apps.qbo.services.QBOService.get_client')
    def test_unpaid_leaves_status_open(self, mock_get_client):
        inv = self._open_invoice('102')
        mock_get_client.return_value = MagicMock()
        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=self._qbo(500.00, 500.00)):
            QBOPaymentPollingService.poll_all()
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.STATUS_OPEN)
        self.assertEqual(inv.qbo_payment_status, 'Unpaid')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_draft_and_paid_invoices_not_polled(self, mock_get_client):
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)  # draft, no qbo_id
        paid = self._open_invoice('103')
        paid.status = Invoice.STATUS_PAID
        paid.save()
        mock_get_client.return_value = MagicMock()
        stats = QBOPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    def test_no_connection_returns_error_stats(self):
        self._open_invoice('104')
        stats = QBOPaymentPollingService.poll_all()
        self.assertIn('error', stats)


class PollCommandTest(TestCase):
    def test_no_connection_records_skipped(self):
        from django.core.management import call_command
        call_command('poll_qbo_payments')
        run = ScheduledProcessRun.objects.get(process_name='poll_qbo_payments')
        self.assertEqual(run.outcome, 'skipped')
