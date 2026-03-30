from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.purchasing.models import Bill
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.qbo.services import QBOBillPaymentPollingService


class BillPaymentPollingTest(TestCase):
    """Test QBO payment status polling for bills."""

    def setUp(self):
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@vendor.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co', default_contact=self.contact,
        )

    def _create_synced_bill(self, qbo_id='200'):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        bill.qbo_id = qbo_id
        bill.save()
        return bill

    @patch('apps.qbo.services.QBOService.get_client')
    def test_polls_unpaid_bills(self, mock_get_client):
        bill = self._create_synced_bill()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_qbo_bill = MagicMock()
        mock_qbo_bill.Balance = 0
        mock_qbo_bill.TotalAmt = 250.00
        with patch('apps.qbo.services.QBOBillPaymentPollingService._fetch_qbo_bill',
                   return_value=mock_qbo_bill):
            stats = QBOBillPaymentPollingService.poll_all()
        bill.refresh_from_db()
        self.assertEqual(bill.qbo_payment_status, 'Paid')
        self.assertEqual(stats['updated'], 1)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_already_paid(self, mock_get_client):
        bill = self._create_synced_bill()
        bill.qbo_payment_status = 'Paid'
        bill.save()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_marks_unpaid_when_balance_remains(self, mock_get_client):
        bill = self._create_synced_bill()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_qbo_bill = MagicMock()
        mock_qbo_bill.Balance = 100.00
        mock_qbo_bill.TotalAmt = 250.00
        with patch('apps.qbo.services.QBOBillPaymentPollingService._fetch_qbo_bill',
                   return_value=mock_qbo_bill):
            stats = QBOBillPaymentPollingService.poll_all()
        bill.refresh_from_db()
        self.assertEqual(bill.qbo_payment_status, 'Unpaid')

    def test_returns_error_without_connection(self):
        self._create_synced_bill()
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertIn('error', stats)
