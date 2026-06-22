# tests/test_qbo_bill_payment_push.py
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from apps.contacts.models import Business, Contact
from apps.purchasing.models import Bill, BillPayment
from apps.qbo.services import QBOBillSyncService


class PushBillPaymentStubTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Acme', last_name='Vendor')
        self.business = Business.objects.create(business_name='Acme', default_contact=self.contact)
        self.bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='INV-1',
            status=Bill.STATUS_RECEIVED)
        self.payment = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('10.00'),
            payment_date=timezone.now())

    @patch('apps.qbo.services.QBOService.get_client', return_value=None)
    def test_no_connection_is_noop(self, _mock):
        self.assertIsNone(QBOBillSyncService.push_bill_payment(self.payment))
