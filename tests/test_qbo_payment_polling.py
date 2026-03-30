from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.qbo.services import QBOPaymentPollingService


class PaymentPollingTest(TestCase):
    """Test QBO payment status polling."""

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
        self.job = Job.objects.create(contact=self.contact, job_number='JOB-2026-0001')

    def _create_synced_invoice(self, qbo_id='100'):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_id = qbo_id
        inv.save()
        return inv

    @patch('apps.qbo.services.QBOService.get_client')
    def test_polls_unpaid_invoices(self, mock_get_client):
        """poll_all checks QBO for invoices with qbo_id that aren't fully paid."""
        inv = self._create_synced_invoice(qbo_id='100')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_inv = MagicMock()
        mock_qbo_inv.Balance = 0
        mock_qbo_inv.TotalAmt = 500.00

        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=mock_qbo_inv):
            stats = QBOPaymentPollingService.poll_all()

        inv.refresh_from_db()
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, Decimal('500.00'))
        self.assertEqual(stats['updated'], 1)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_partial_payment(self, mock_get_client):
        """Detects partial payment (Balance > 0 but less than TotalAmt)."""
        inv = self._create_synced_invoice(qbo_id='101')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_inv = MagicMock()
        mock_qbo_inv.Balance = 200.00
        mock_qbo_inv.TotalAmt = 500.00

        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=mock_qbo_inv):
            QBOPaymentPollingService.poll_all()

        inv.refresh_from_db()
        self.assertEqual(inv.qbo_payment_status, 'Partial')
        self.assertEqual(inv.qbo_amount_paid, Decimal('300.00'))

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_invoices_without_qbo_id(self, mock_get_client):
        """Invoices not synced to QBO are skipped."""
        Invoice.objects.create(job=self.job)  # no qbo_id

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        stats = QBOPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_already_paid_invoices(self, mock_get_client):
        """Invoices already marked as paid are skipped."""
        inv = self._create_synced_invoice(qbo_id='100')
        inv.qbo_payment_status = 'Paid'
        inv.save()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        stats = QBOPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    def test_poll_all_no_connection(self):
        """poll_all returns error stats if no QBO connection."""
        self._create_synced_invoice()
        stats = QBOPaymentPollingService.poll_all()
        self.assertIn('error', stats)
