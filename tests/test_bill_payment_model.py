from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, QBOSyncable
from apps.purchasing.models import Bill, BillLineItem, BillPayment


class BillPaymentSyncFieldsTests(TestCase):
    def test_billpayment_inherits_qbosyncable(self):
        self.assertTrue(issubclass(BillPayment, QBOSyncable))

    def test_new_payment_defaults_pending(self):
        bp = BillPayment()
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_PENDING)
        self.assertEqual(bp.qbo_id, '')
        self.assertEqual(bp.payment_account_id, '')

    def test_has_payment_account_field(self):
        names = {f.name for f in BillPayment._meta.get_fields()}
        self.assertIn('payment_account_id', names)
        self.assertIn('qbo_id', names)
        self.assertNotIn('qbo_payment_id', names)
        self.assertNotIn('method', names)


class BillPaymentModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Acme', last_name='Steel', email='contact@acme.com'
        )
        self.business = Business.objects.create(
            business_name='Acme Steel', default_contact=self.contact
        )
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

    def test_total_amount_paid_balance(self):
        self.assertEqual(self.bill.total, Decimal('200.00'))
        self.assertEqual(self.bill.amount_paid, Decimal('0.00'))
        self.assertEqual(self.bill.balance, Decimal('200.00'))

    def test_payment_drives_status(self):
        BillPayment.objects.create(
            bill=self.bill, amount=Decimal('200.00'),
            payment_date=timezone.now(),
            reference='4471',
        )
        self.bill.recompute_payment_status()
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)
        self.assertIsNotNone(self.bill.paid_date)

    def test_partial_then_reversal_moves_status_backward(self):
        p = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'),
            payment_date=timezone.now(),
        )
        self.bill.recompute_payment_status()
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)
        p.delete()
        self.bill.recompute_payment_status()
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)
        self.assertIsNone(self.bill.paid_date)

    def test_recompute_payment_status_no_op_on_non_payment_statuses(self):
        """recompute_payment_status() must not alter status on draft/cancelled/refunded bills."""
        contact = Contact.objects.create(
            first_name='Bolt', last_name='Supplier', email='bolt@sup.com'
        )
        business = Business.objects.create(
            business_name='Bolt Supplier', default_contact=contact
        )
        # Create a bill directly in cancelled status (no status-machine path needed).
        cancelled_bill = Bill.objects.create(
            business=business, vendor_invoice_number='INV-CANCEL',
            status=Bill.STATUS_CANCELLED,
        )
        cancelled_bill.recompute_payment_status()
        cancelled_bill.refresh_from_db()
        self.assertEqual(cancelled_bill.status, Bill.STATUS_CANCELLED)
