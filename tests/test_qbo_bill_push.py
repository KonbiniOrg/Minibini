from django.test import TestCase
from apps.purchasing.models import Bill
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class BillQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Bill model."""

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

    def test_bill_has_qbo_id_null_by_default(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        self.assertIsNone(bill.qbo_id)

    def test_bill_has_qbo_payment_status_empty_by_default(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        self.assertEqual(bill.qbo_payment_status, '')

    def test_bill_can_store_qbo_data(self):
        bill = Bill.objects.create(
            business=self.business, vendor_invoice_number='V-001',
        )
        bill.qbo_id = '5555'
        bill.qbo_payment_status = 'Paid'
        bill.save()
        bill.refresh_from_db()
        self.assertEqual(bill.qbo_id, '5555')
        self.assertEqual(bill.qbo_payment_status, 'Paid')
