from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.contacts.models import Business, Contact
from apps.core.models import Configuration
from apps.purchasing.models import Bill, BillPayment
from apps.purchasing.services import BillPaymentService


class BillPaymentLifecycleTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        contact = Contact.objects.create(first_name='Acme', last_name='Vendor')
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=contact,
            qbo_vendor_id='qbo-vendor-1',
        )
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-LC-1',
            status=Bill.STATUS_RECEIVED,
        )
        self.bill.qbo_id = 'qbo-bill-1'
        self.bill.save(update_fields=['qbo_id'])

    @patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
    def test_edit_synced_payment_resyncs(self, mock_push, mock_update):
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-1', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.update_payment(pay.pk, amount='75.00')
        mock_update.assert_called_once()
        mock_push.assert_not_called()

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_synced_payment_voids(self, mock_void):
        """Successful QBO void → payment deleted and bill status recomputed."""
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-2', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.delete_payment(pay.pk)
        mock_void.assert_called_once()
        # Payment must be gone
        self.assertFalse(BillPayment.objects.filter(pk=pay.pk).exists())

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_synced_payment_raises_on_qbo_failure(self, mock_void):
        """QBO void raises → ValidationError propagated, row kept as sync_failed."""
        mock_void.side_effect = Exception('QBO is down')
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-fail', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        with self.assertRaises(ValidationError):
            BillPaymentService.delete_payment(pay.pk)
        # Row must still exist
        self.assertTrue(BillPayment.objects.filter(pk=pay.pk).exists())
        pay.refresh_from_db()
        self.assertEqual(pay.qbo_sync_status, BillPayment.SYNC_FAILED)


class BillPaymentRetryTests(TestCase):
    """Tests for BillPaymentService.retry — dispatch on qbo_pending_op."""

    def setUp(self):
        contact = Contact.objects.create(first_name='Retry', last_name='Vendor')
        business = Business.objects.create(business_name='Retry Corp', default_contact=contact,
                                           qbo_vendor_id='qbo-v-retry')
        self.bill = Bill.objects.create(
            business=business, vendor_invoice_number='INV-R-1',
            status=Bill.STATUS_RECEIVED,
        )
        self.bill.qbo_id = 'qbo-bill-retry'
        self.bill.save(update_fields=['qbo_id'])

    def _payment(self, *, qbo_id=''):
        return BillPayment.objects.create(
            bill=self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id=qbo_id,
            qbo_sync_status=BillPayment.SYNC_SYNCED if qbo_id else BillPayment.SYNC_PENDING,
        )

    @patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
    def test_retry_failed_update_calls_update(self, mock_push, mock_update):
        """LOAD-BEARING: OP_UPDATE with qbo_id → update called, push NOT called."""
        pay = self._payment(qbo_id='q1')
        pay.qbo_sync_status = BillPayment.SYNC_FAILED
        pay.qbo_pending_op = BillPayment.OP_UPDATE
        pay.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
        BillPaymentService.retry(pay.pk)
        mock_update.assert_called_once()
        mock_push.assert_not_called()

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_retry_failed_delete_voids_and_removes(self, mock_void):
        """OP_DELETE retry → delete_payment re-run; payment row gone on success."""
        pay = self._payment(qbo_id='q2')
        pay.qbo_sync_status = BillPayment.SYNC_FAILED
        pay.qbo_pending_op = BillPayment.OP_DELETE
        pay.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
        result = BillPaymentService.retry(pay.pk)
        mock_void.assert_called_once()
        self.assertIsNone(result)
        self.assertFalse(BillPayment.objects.filter(pk=pay.pk).exists())

    @patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
    def test_retry_failed_create_calls_push(self, mock_push, mock_update):
        """OP_CREATE (no qbo_id) → push_bill_payment called, update NOT called."""
        pay = self._payment(qbo_id='')
        pay.qbo_sync_status = BillPayment.SYNC_FAILED
        pay.qbo_pending_op = BillPayment.OP_CREATE
        pay.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
        BillPaymentService.retry(pay.pk)
        mock_push.assert_called_once()
        mock_update.assert_not_called()

    def test_retry_non_failed_raises(self):
        """Calling retry on a non-failed payment raises ValidationError."""
        pay = self._payment(qbo_id='q3')
        pay.qbo_sync_status = BillPayment.SYNC_SYNCED
        pay.save(update_fields=['qbo_sync_status'])
        with self.assertRaises(ValidationError):
            BillPaymentService.retry(pay.pk)


class VoidBillPaymentTests(TestCase):
    """Unit tests for QBOBillSyncService.void_bill_payment — now raises on failure."""

    def setUp(self):
        contact = Contact.objects.create(first_name='V', last_name='Vendor')
        business = Business.objects.create(business_name='V Corp', default_contact=contact)
        bill = Bill.objects.create(
            business=business, vendor_invoice_number='INV-V-1',
            status=Bill.STATUS_RECEIVED,
        )
        self.payment = BillPayment.objects.create(
            bill=bill, amount=Decimal('100.00'), payment_date=timezone.now(),
            qbo_id='qbo-bp-10', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )

    def test_void_no_qbo_id_is_noop(self):
        """No qbo_id → returns immediately without any call."""
        from apps.qbo.services import QBOBillSyncService
        self.payment.qbo_id = ''
        self.payment.save(update_fields=['qbo_id'])
        # Should not raise
        QBOBillSyncService.void_bill_payment(self.payment)

    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_void_no_client_raises(self, _):
        """No active QBO connection → ValueError raised."""
        from apps.qbo.services import QBOBillSyncService
        with self.assertRaises(ValueError):
            QBOBillSyncService.void_bill_payment(self.payment)

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOService.log_sync')
    def test_void_success(self, mock_log, mock_get_client):
        """QBO delete succeeds → log success and return normally."""
        from apps.qbo.services import QBOBillSyncService
        client = MagicMock()
        mock_get_client.return_value = client
        with patch('quickbooks.objects.billpayment.BillPayment.get') as mock_get:
            qbo_obj = MagicMock()
            mock_get.return_value = qbo_obj
            QBOBillSyncService.void_bill_payment(self.payment)
        qbo_obj.delete.assert_called_once_with(qb=client)
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['status'], 'success')
        self.assertEqual(call_kwargs['action'], 'delete')

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.qbo.services.QBOService.log_sync')
    def test_void_sdk_failure_raises(self, mock_log, mock_get_client):
        """SDK raises → log failed and re-raise."""
        from apps.qbo.services import QBOBillSyncService
        client = MagicMock()
        mock_get_client.return_value = client
        with patch('quickbooks.objects.billpayment.BillPayment.get') as mock_get:
            mock_get.side_effect = RuntimeError('network timeout')
            with self.assertRaises(RuntimeError):
                QBOBillSyncService.void_bill_payment(self.payment)
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        self.assertEqual(call_kwargs['status'], 'failed')
