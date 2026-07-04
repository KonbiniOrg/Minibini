"""
Test that GET /api/bills/?purchase_order=<id> filters to only bills on that PO.
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.purchasing.models import PurchaseOrder, Bill, BillLineItem

User = get_user_model()


class BillPurchaseOrderFilterTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')

        self.user = User.objects.create_user(username='viewer', password='x')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.contact = Contact.objects.create(
            first_name='Acme', last_name='Steel', email='c@acme.com')
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Materials')

        # Two POs
        self.poA = PurchaseOrder.objects.create(
            business=self.business, status=PurchaseOrder.STATUS_ISSUED)
        self.poB = PurchaseOrder.objects.create(
            business=self.business, status=PurchaseOrder.STATUS_ISSUED)

        # Bill on each PO
        self.billA = self._bill('INV-A', '100.00', self.poA)
        self.billB = self._bill('INV-B', '200.00', self.poB)

    def _bill(self, vendor_invoice_number, total, po):
        bill = Bill.objects.create(
            business=self.business,
            purchase_order=po,
            vendor_invoice_number=vendor_invoice_number,
            status=Bill.STATUS_RECEIVED,
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='item',
            qty=Decimal('1'), price=Decimal(total),
            units='none', accounting_category=self.ac,
        )
        return bill

    def test_filter_by_purchase_order_returns_only_that_pos_bills(self):
        """?purchase_order=poA must return only billA, not billB."""
        resp = self.client.get(f'/api/bills/?purchase_order={self.poA.pk}')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        ids = [b['bill_id'] for b in results]
        self.assertIn(self.billA.pk, ids)
        self.assertNotIn(self.billB.pk, ids)

    def test_filter_by_other_po_returns_only_that_pos_bills(self):
        """?purchase_order=poB must return only billB, not billA."""
        resp = self.client.get(f'/api/bills/?purchase_order={self.poB.pk}')
        self.assertEqual(resp.status_code, 200)
        results = resp.data.get('results', resp.data)
        ids = [b['bill_id'] for b in results]
        self.assertIn(self.billB.pk, ids)
        self.assertNotIn(self.billA.pk, ids)
