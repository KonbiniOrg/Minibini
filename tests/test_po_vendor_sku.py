# tests/test_po_vendor_sku.py
"""vendor_sku on PO lines (spec 2026-10-14 §3): stored, editable on drafts
through the line PATCH, exposed with the item code on the line serializer,
and printed as Code / SKU columns on the PDF (blank for freeform lines and
for minted LOT-* lots, which are not vendor codes)."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.pdf import generate_purchase_order_pdf


class VendorSkuTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATSKU')
        c = Contact.objects.create(first_name='V', last_name='V',
                                   phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='Rugby', default_contact=c)
        c.business = self.business
        c.save()
        self.item = InventoryItem.objects.create(
            code='BB34P', description='3/4 Baltic Birch', accounting_category=self.cat,
            purchase_price=Decimal('62.40'), units='sheet')
        self.lot = InventoryItem.objects.create(
            code='LOT-77', description='minted', accounting_category=self.cat,
            purchase_price=Decimal('1.00'))
        self.po = PurchaseOrder.objects.create(business=self.business, contact=c)
        self.user = User.objects.create_user('sku_admin', password='p', is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_default_is_blank(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        self.assertEqual(li.vendor_sku, '')

    def test_line_create_accepts_vendor_sku_and_serializes_item_code(self):
        r = self.client.post(f'/api/purchase-orders/{self.po.pk}/line-items/', {
            'description': 'ply', 'qty': 2, 'price': '62.40',
            'inventory_item': self.item.pk, 'vendor_sku': 'BB34P-48',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['vendor_sku'], 'BB34P-48')
        self.assertEqual(r.json()['item_code'], 'BB34P')

    def test_line_patch_edits_vendor_sku(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{li.pk}/',
            {'vendor_sku': 'X-1'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        li.refresh_from_db()
        self.assertEqual(li.vendor_sku, 'X-1')

    def test_freeform_line_has_null_item_code(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        r = self.client.get(f'/api/purchase-orders/{self.po.pk}/line-items/')
        row = next(x for x in r.json() if x['line_item_id'] == li.pk)
        self.assertIsNone(row['item_code'])
        self.assertEqual(row['vendor_sku'], '')

    @patch('apps.purchasing.pdf.HTML')
    def test_pdf_prints_code_and_sku_columns(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b'%PDF-x'
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, inventory_item=self.item, description='ply',
            qty=1, price=Decimal('62.40'), vendor_sku='BB34P-48')
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='freight', qty=1, price=Decimal('10.00'))
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, inventory_item=self.lot, description='lot line',
            qty=1, price=Decimal('1.00'))
        generate_purchase_order_pdf(self.po)
        html = mock_html.call_args.kwargs['string']
        self.assertIn('<th>Code</th>', html)
        self.assertIn('<th>SKU</th>', html)
        self.assertIn('BB34P-48', html)
        self.assertIn('>BB34P<', html)
        self.assertNotIn('LOT-77', html)
