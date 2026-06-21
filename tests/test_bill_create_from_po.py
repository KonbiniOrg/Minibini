from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.purchasing.models import (
    PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem)

User = get_user_model()


class BillCreateFromPoTest(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        self.user = User.objects.create_user(username='fin', password='x')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.contact = Contact.objects.create(
            first_name='A', last_name='B', email='a@b.com')
        self.biz = Business.objects.create(
            business_name='Acme', default_contact=self.contact)
        self.ac = AccountingCategory.objects.create(code='MAT', name='Mat')
        self.po = PurchaseOrder.objects.create(
            business=self.biz, status=PurchaseOrder.STATUS_ISSUED)
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, line_number=1, description='Widget',
            qty=Decimal('2'), price=Decimal('25.00'), units='ea',
            accounting_category=self.ac)

    def test_create_from_po_without_invoice_number_copies_lines_and_vendor(self):
        # The reported bug: a draft bill from a PO has no invoice number yet.
        resp = self.client.post(
            '/api/bills/', {'purchase_order': self.po.po_id}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        bill = Bill.objects.get(pk=resp.data['bill_id'])
        self.assertEqual(bill.business_id, self.biz.pk)
        self.assertEqual(bill.vendor_invoice_number, '')
        lines = list(BillLineItem.objects.filter(bill=bill))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].description, 'Widget')
        self.assertEqual(lines[0].qty, Decimal('2'))
        self.assertEqual(lines[0].price, Decimal('25.00'))

    def test_create_from_po_keeps_typed_invoice_number(self):
        resp = self.client.post(
            '/api/bills/',
            {'purchase_order': self.po.po_id,
             'vendor_invoice_number': 'REAL-123'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        bill = Bill.objects.get(pk=resp.data['bill_id'])
        self.assertEqual(bill.vendor_invoice_number, 'REAL-123')
