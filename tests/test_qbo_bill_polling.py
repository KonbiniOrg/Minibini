from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.purchasing.models import Bill, BillPayment
from apps.contacts.models import Contact, Business
from apps.qbo.services import QBOBillPaymentPollingService


class BillPaymentPollingTest(TestCase):
    """Test QBO clearance polling for BillPayments (per-payment, not per-bill)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Smith',
            email='jane@vendor.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co', default_contact=self.contact,
        )
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )

    def _create_bill_payment(self, qbo_id='', cleared_date=None):
        from django.utils import timezone
        return BillPayment.objects.create(
            bill=self.bill,
            amount='100.00',
            payment_date=timezone.now(),
            qbo_id=qbo_id,
            cleared_date=cleared_date,
        )

    def test_returns_error_without_connection(self):
        self._create_bill_payment(qbo_id='qbp-1')
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertIn('error', stats)
        self.assertEqual(stats['error'], 'No active QBO connection')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_payments_without_qbo_id(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        self._create_bill_payment(qbo_id='')
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_already_cleared_payments(self, mock_get_client):
        from django.utils import timezone
        mock_get_client.return_value = MagicMock()
        self._create_bill_payment(qbo_id='qbp-1', cleared_date=timezone.now())
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_checks_pending_payments_with_qbo_id(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        self._create_bill_payment(qbo_id='qbp-1')
        self._create_bill_payment(qbo_id='qbp-2')
        stats = QBOBillPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 2)
        self.assertEqual(stats['cleared'], 0)
        self.assertEqual(stats['errors'], [])
