from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.purchasing.models import PurchaseOrder, Bill, BillLineItem
from apps.api.purchasing.serializers import BillSerializer, PurchaseOrderSerializer


class BillPoBillingSerializerTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        self.contact = Contact.objects.create(first_name='Acme', last_name='Co', email='c@acme.com')
        self.b = Business.objects.create(business_name='Acme', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.po = PurchaseOrder.objects.create(business=self.b, status=PurchaseOrder.STATUS_ISSUED)

    def _bill(self, vendor_invoice_number, total, status=Bill.STATUS_RECEIVED, po=None):
        bill = Bill.objects.create(
            business=self.b,
            purchase_order=po if po is not None else self.po,
            vendor_invoice_number=vendor_invoice_number,
            status=status,
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='x',
            qty=Decimal('1'), price=Decimal(str(total)),
            units='none', accounting_category=self.ac,
        )
        return bill

    def test_other_bills_listed(self):
        first = self._bill('A', '50.00')
        second = self._bill('B', '30.00')
        data = BillSerializer(second).data
        self.assertIn('po_billing', data)
        self.assertIsNotNone(data['po_billing'])
        other_bills = data['po_billing']['other_bills']
        self.assertEqual(len(other_bills), 1)
        self.assertEqual(other_bills[0]['vendor_invoice_number'], 'A')
        self.assertEqual(other_bills[0]['bill_id'], first.pk)
        self.assertEqual(other_bills[0]['status'], Bill.STATUS_RECEIVED)
        self.assertEqual(other_bills[0]['total'], '50.00')

    def test_cancelled_bills_excluded_from_other_bills(self):
        cancelled = self._bill('C', '10.00', status=Bill.STATUS_CANCELLED)
        bill = self._bill('D', '20.00')
        data = BillSerializer(bill).data
        other_bills = data['po_billing']['other_bills']
        self.assertEqual(len(other_bills), 0)

    def test_po_fully_billed_flag(self):
        from apps.purchasing.models import PurchaseOrderLineItem
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, line_number=1, description='x',
            qty=Decimal('1'), price=Decimal('100.00'), units='none',
            accounting_category=self.ac,
        )
        bill = self._bill('E', '100.00')
        data = BillSerializer(bill).data
        self.assertTrue(data['po_billing']['po_fully_billed'])

    def test_po_billing_none_when_no_po(self):
        bill = Bill.objects.create(
            business=self.b,
            purchase_order=None,
            vendor_invoice_number='Z',
            status=Bill.STATUS_RECEIVED,
        )
        data = BillSerializer(bill).data
        self.assertIsNone(data['po_billing'])

    def test_self_excluded_from_other_bills(self):
        bill = self._bill('F', '25.00')
        data = BillSerializer(bill).data
        other_bills = data['po_billing']['other_bills']
        self.assertEqual(len(other_bills), 0)


class PurchaseOrderBilledFieldsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        self.contact = Contact.objects.create(first_name='Sup', last_name='Co', email='s@co.com')
        self.b = Business.objects.create(business_name='Supplier', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='SUP', name='Supplies')
        from apps.purchasing.models import PurchaseOrderLineItem
        self.po = PurchaseOrder.objects.create(business=self.b, status=PurchaseOrder.STATUS_ISSUED)
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, line_number=1, description='y',
            qty=Decimal('2'), price=Decimal('100.00'), units='none',
            accounting_category=self.ac,
        )

    def _bill(self, total, status=Bill.STATUS_RECEIVED):
        bill = Bill.objects.create(
            business=self.b, purchase_order=self.po,
            vendor_invoice_number='INV', status=status,
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='y',
            qty=Decimal('1'), price=Decimal(str(total)),
            units='none', accounting_category=self.ac,
        )
        return bill

    def test_po_total_in_serializer(self):
        data = PurchaseOrderSerializer(self.po).data
        self.assertEqual(data['po_total'], '200.00')

    def test_billed_total_in_serializer(self):
        self._bill('120.00')
        data = PurchaseOrderSerializer(self.po).data
        self.assertEqual(data['billed_total'], '120.00')

    def test_is_fully_billed_in_serializer(self):
        self._bill('200.00')
        data = PurchaseOrderSerializer(self.po).data
        self.assertTrue(data['is_fully_billed'])

    def test_is_not_fully_billed(self):
        self._bill('100.00')
        data = PurchaseOrderSerializer(self.po).data
        self.assertFalse(data['is_fully_billed'])
