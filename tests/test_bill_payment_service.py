from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.contacts.models import Business, Contact
from apps.core.history import HistoryContext, set_history_context
from apps.core.models import AccountingCategory, PurchasingHistory
from apps.purchasing.models import Bill, BillLineItem, BillPayment
from apps.purchasing.services import BillPaymentService


class BillPaymentServiceTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Acme', last_name='Steel', email='c@acme.com')
        self.business = Business.objects.create(business_name='Acme Steel', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-1',
            status=Bill.STATUS_RECEIVED,
        )
        BillLineItem.objects.create(
            bill=self.bill, line_number=1, description='Steel',
            qty=Decimal('2'), price=Decimal('100.00'),
            units='none', accounting_category=self.ac,
        )

    def test_record_payment_partial_then_full(self):
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('50.00'),
            payment_date=timezone.now(),
            reference='4471',
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('150.00'),
            payment_date=timezone.now(),
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)

    def test_record_payment_writes_history_on_bill(self):
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('200.00'),
            payment_date=timezone.now(),
        )
        self.assertTrue(PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk,
            entry_type='action').exists())

    def test_cannot_pay_draft_bill(self):
        draft = Bill.objects.create(
            business=self.business, vendor_invoice_number='D', status=Bill.STATUS_DRAFT)
        with self.assertRaises(ValidationError):
            BillPaymentService.record_payment(
                draft, amount=Decimal('10.00'),
                payment_date=timezone.now())

    def test_delete_payment_recomputes(self):
        """(a) No qbo_id → deletes locally, bill status recomputed."""
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('200.00'),
            payment_date=timezone.now())
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)
        BillPaymentService.delete_payment(p.pk)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)

    def test_delete_payment_no_qbo_id_no_qbo_call(self):
        """(c) No qbo_id → deletes locally with no QBO call."""
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('50.00'),
            payment_date=timezone.now())
        # Ensure no qbo_id
        self.assertFalse(p.qbo_id)
        with patch('apps.qbo.services.QBOBillSyncService.void_bill_payment') as mock_void:
            BillPaymentService.delete_payment(p.pk)
        mock_void.assert_not_called()
        self.assertFalse(BillPayment.objects.filter(pk=p.pk).exists())

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_payment_with_qbo_id_success(self, mock_void):
        """(a) QBO void succeeds → payment deleted + bill status recomputed."""
        p = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('200.00'), payment_date=timezone.now(),
            qbo_id='qbo-bp-ok', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        self.bill.status = Bill.STATUS_PAID_IN_FULL
        self.bill.save()
        BillPaymentService.delete_payment(p.pk)
        mock_void.assert_called_once()
        self.assertFalse(BillPayment.objects.filter(pk=p.pk).exists())
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_payment_qbo_failure_raises_validation_error(self, mock_void):
        """(b) QBO void FAILS → ValidationError raised, payment still exists, sync_failed committed."""
        mock_void.side_effect = Exception('QBO is unreachable')
        p = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('200.00'), payment_date=timezone.now(),
            qbo_id='qbo-bp-fail', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        with self.assertRaises(ValidationError) as ctx:
            BillPaymentService.delete_payment(p.pk)
        self.assertIn('QuickBooks', str(ctx.exception))
        # Payment still exists
        self.assertTrue(BillPayment.objects.filter(pk=p.pk).exists())
        # sync_failed was committed (not rolled back by the atomic block)
        p.refresh_from_db()
        self.assertEqual(p.qbo_sync_status, BillPayment.SYNC_FAILED)
        # bill status NOT recomputed — remains STATUS_RECEIVED (recompute_payment_status never ran)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)

    def test_update_payment_raises_on_cancelled_bill(self):
        """Gate: update_payment must reject payments on a cancelled bill."""
        # Create a payment directly so we can put the bill into cancelled state
        payment = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'),
            payment_date=timezone.now(),
        )
        self.bill.status = Bill.STATUS_CANCELLED
        self.bill.save()
        with self.assertRaises(ValidationError):
            BillPaymentService.update_payment(payment.pk, amount=Decimal('75.00'))

    def test_update_payment_partial_to_full(self):
        """Happy path: updating a partial payment to the full amount recomputes to paid_in_full."""
        # Bill total = 2 * 100.00 = 200.00
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)
        BillPaymentService.update_payment(p.pk, amount=Decimal('200.00'))
        p.refresh_from_db()
        self.assertEqual(p.amount, Decimal('200.00'))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)


class BillPaymentHistoryTest(TestCase):
    """Tests for BillPayment lifecycle history entries on the bill timeline."""

    def setUp(self):
        from apps.core.models import User
        self.user = User.objects.create_user(username='histtest', password='x')
        self.contact = Contact.objects.create(first_name='Test', last_name='Vendor', email='v@test.com')
        self.business = Business.objects.create(business_name='Test Vendor', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='TST', name='Test')
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='HIST-1',
            status=Bill.STATUS_RECEIVED,
        )
        BillLineItem.objects.create(
            bill=self.bill, line_number=1, description='Widget',
            qty=Decimal('1'), price=Decimal('100.00'),
            units='none', accounting_category=self.ac,
        )
        # Set request context so record_action attributes to this user
        set_history_context(HistoryContext(user=self.user))

    def tearDown(self):
        set_history_context(None)

    def test_record_payment_writes_action_attributed_to_context_user(self):
        """record_payment writes a 'Payment recorded' action row on the bill, attributed to the context user."""
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
        )
        rows = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk,
            entry_type='action',
        )
        self.assertTrue(rows.exists(), 'No action history row found for record_payment')
        action_row = rows.order_by('-pk').first()
        self.assertEqual(action_row.user, self.user)
        self.assertTrue(
            action_row.changes.get('_action', '').startswith('Payment recorded'),
            f"Expected '_action' starting with 'Payment recorded', got: {action_row.changes.get('_action')}"
        )

    def test_update_payment_writes_action_on_bill(self):
        """update_payment writes a 'Payment edited' action row on the bill."""
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('50.00'),
            payment_date=timezone.now(),
        )
        initial_count = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        ).count()
        BillPaymentService.update_payment(p.pk, amount=Decimal('75.00'))
        rows = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        )
        self.assertEqual(rows.count(), initial_count + 1, 'Expected one additional action row after update_payment')
        edit_row = rows.order_by('-pk').first()
        self.assertTrue(
            edit_row.changes.get('_action', '').startswith('Payment edited'),
            f"Expected '_action' starting with 'Payment edited', got: {edit_row.changes.get('_action')}"
        )

    def test_delete_payment_writes_action_on_success_path(self):
        """delete_payment writes a 'Payment deleted' action row on the bill (success path only)."""
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
        )
        initial_count = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        ).count()
        BillPaymentService.delete_payment(p.pk)
        rows = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        )
        self.assertEqual(rows.count(), initial_count + 1, 'Expected one additional action row after delete_payment')
        delete_row = rows.order_by('-pk').first()
        self.assertTrue(
            delete_row.changes.get('_action', '').startswith('Payment deleted'),
            f"Expected '_action' starting with 'Payment deleted', got: {delete_row.changes.get('_action')}"
        )

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_payment_no_history_on_qbo_failure(self, mock_void):
        """delete_payment does NOT write a history entry when the delete is refused (QBO failure)."""
        mock_void.side_effect = Exception('QBO is unreachable')
        p = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('100.00'), payment_date=timezone.now(),
            qbo_id='qbo-fail', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        self.bill.status = Bill.STATUS_PAID_IN_FULL
        self.bill.save()
        count_before = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        ).count()
        with self.assertRaises(Exception):
            BillPaymentService.delete_payment(p.pk)
        count_after = PurchasingHistory.objects.filter(
            object_type='bill', object_id=self.bill.pk, entry_type='action',
        ).count()
        self.assertEqual(count_before, count_after, 'No history row should be written when delete is refused')
