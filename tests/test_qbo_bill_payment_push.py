from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Business, Contact
from apps.core.models import Configuration
from apps.purchasing.models import Bill, BillPayment
from apps.qbo.services import QBOBillSyncService


class BillPaymentPushTests(TestCase):
    """Tests for live QBO BillPayment push. Uses a plain TestCase and
    builds all fixtures inline, following the bill-construction pattern
    from tests/test_qbo_bill_push.py."""

    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        self.contact = Contact.objects.create(first_name='Acme', last_name='Vendor')
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
            qbo_vendor_id='qbo-vendor-1',
        )
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-1',
            status=Bill.STATUS_RECEIVED,
        )
        self.bill.qbo_id = 'qbo-bill-1'
        self.bill.save(update_fields=['qbo_id'])
        self.payment = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
            reference='1234', payment_account_id='35',
        )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_builds_and_marks_synced(self, mock_get_client, mock_log):
        client = MagicMock()
        mock_get_client.return_value = client
        # Patch the SDK BillPayment.save to set an Id.
        with patch('quickbooks.objects.billpayment.BillPayment.save', autospec=True) as mock_save:
            def _save(self, qb=None):
                self.Id = 'qbo-bp-77'
            mock_save.side_effect = _save
            out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(out, 'qbo-bp-77')
        self.assertEqual(self.payment.qbo_id, 'qbo-bp-77')
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_SYNCED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_without_connection_marks_failed(self, mock_get_client):
        mock_get_client.return_value = None
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertIsNone(out)
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_FAILED)
        self.assertIn('No active QBO connection', self.payment.qbo_sync_error)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_without_account_marks_failed(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        self.payment.payment_account_id = ''
        self.payment.save(update_fields=['payment_account_id'])
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_FAILED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_short_circuits_when_already_synced(self, mock_get_client):
        self.payment.qbo_id = 'already'
        self.payment.save(update_fields=['qbo_id'])
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.assertEqual(out, 'already')
        mock_get_client.assert_not_called()
