from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.purchasing.models import (
    PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem)


class PoBillingTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        self.contact = Contact.objects.create(first_name='Acme', last_name='Co', email='c@acme.com')
        self.b = Business.objects.create(business_name='Acme', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Materials')
        self.po = PurchaseOrder.objects.create(business=self.b, status=PurchaseOrder.STATUS_ISSUED)
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, line_number=1, description='x',
            qty=Decimal('2'), price=Decimal('100.00'), units='none',
            accounting_category=self.ac)

    def _bill(self, total, status=Bill.STATUS_RECEIVED):
        bill = Bill.objects.create(business=self.b, purchase_order=self.po,
                                   vendor_invoice_number='I', status=status)
        BillLineItem.objects.create(bill=bill, line_number=1, description='x',
                                    qty=Decimal('1'), price=Decimal(str(total)),
                                    units='none', accounting_category=self.ac)
        return bill

    def test_po_total(self):
        self.assertEqual(self.po.po_total, Decimal('200.00'))

    def test_billed_total_excludes_cancelled(self):
        self._bill('120.00')
        self._bill('80.00', status=Bill.STATUS_CANCELLED)
        self.assertEqual(self.po.billed_total, Decimal('120.00'))
        self.assertFalse(self.po.is_fully_billed)

    def test_is_fully_billed_at_coverage(self):
        self._bill('200.00')
        self.assertTrue(self.po.is_fully_billed)

    def test_serializer_exposes_linked_bills(self):
        from apps.api.purchasing.serializers import PurchaseOrderSerializer
        bill = self._bill('120.00')
        data = PurchaseOrderSerializer(self.po).data
        self.assertEqual(len(data['bills']), 1)
        self.assertEqual(data['bills'][0]['bill_id'], bill.bill_id)
        self.assertEqual(data['bills'][0]['vendor_invoice_number'], 'I')

    def test_serializer_bills_empty_when_none(self):
        from apps.api.purchasing.serializers import PurchaseOrderSerializer
        data = PurchaseOrderSerializer(self.po).data
        self.assertEqual(data['bills'], [])
