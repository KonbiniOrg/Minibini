from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.contacts.models import Business, Contact
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
            payment_date=timezone.now(), method=BillPayment.METHOD_CHECK,
            reference='4471',
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('150.00'),
            payment_date=timezone.now(), method=BillPayment.METHOD_CHECK,
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)

    def test_record_payment_writes_history_on_bill(self):
        BillPaymentService.record_payment(
            self.bill, amount=Decimal('200.00'),
            payment_date=timezone.now(), method=BillPayment.METHOD_CHECK,
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
                payment_date=timezone.now(), method=BillPayment.METHOD_CHECK)

    def test_delete_payment_recomputes(self):
        p = BillPaymentService.record_payment(
            self.bill, amount=Decimal('200.00'),
            payment_date=timezone.now(), method=BillPayment.METHOD_CHECK)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PAID_IN_FULL)
        BillPaymentService.delete_payment(p.pk)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)
