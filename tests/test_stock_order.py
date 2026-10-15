from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class OrderStockTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        cat = AccountingCategory.objects.create(name='c')
        self.item = InventoryItem.objects.create(
            code='SHEET-3', accounting_category=cat,
            qty_on_hand=Decimal('1'), purchase_price=Decimal('10'),
        )

    def test_creates_draft_po_with_unlinked_line(self):
        po, li = InventoryService.order_stock(self.item, line={'qty': Decimal('5')})
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertEqual(li.inventory_item_id, self.item.pk)
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10'))
        self.assertIsNone(li.task_id)
        self.assertIsNone(li.linked_material)

    def test_line_overrides_and_po_fields(self):
        c = Contact.objects.create(first_name='V', last_name='V', phones=[{'number': '5', 'label': 'work'}])
        b = Business.objects.create(business_name='B', default_contact=c)
        po, li = InventoryService.order_stock(
            self.item, po_fields={'business': b},
            line={'qty': Decimal('2'), 'price': Decimal('9.50'), 'vendor_sku': 'S-3', 'units': 'sheet'})
        self.assertEqual(po.business_id, b.pk)
        self.assertEqual((li.price, li.vendor_sku, li.units), (Decimal('9.50'), 'S-3', 'sheet'))

    def test_appends_to_given_draft(self):
        po, _ = InventoryService.order_stock(self.item, line={'qty': Decimal('2')})
        po2, li2 = InventoryService.order_stock(self.item, po=po, line={'qty': Decimal('3')})
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.count(), 2)

    def test_refuses_non_draft_po(self):
        po, _ = InventoryService.order_stock(self.item, line={'qty': Decimal('2')})
        PurchaseOrder.objects.filter(pk=po.pk).update(status=PurchaseOrder.STATUS_ISSUED)
        po.refresh_from_db()
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, po=po, line={'qty': Decimal('1')})

    def test_refuses_missing_or_non_positive_quantity(self):
        for line in (None, {}, {'qty': Decimal('0')}, {'qty': Decimal('-1')}):
            with self.assertRaises(ValidationError):
                InventoryService.order_stock(self.item, line=line)


class OrderStockApiTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        cat = AccountingCategory.objects.create(name='c2')
        self.item = InventoryItem.objects.create(code='SHEET-4', accounting_category=cat, purchase_price=Decimal('10'))
        c = Contact.objects.create(first_name='V', last_name='V', phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='B2', default_contact=c)
        self.user = User.objects.create_user('stock_fin', password='p')
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f'/api/inventory/{self.item.pk}/order/'

    def test_po_mode_creates_po_and_line(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk},
                                        'line': {'qty': '3', 'vendor_sku': 'S-4'}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        po = PurchaseOrder.objects.get(pk=r.json()['po_id'])
        self.assertEqual(po.business_id, self.business.pk)
        self.assertEqual(po.purchaseorderlineitem_set.get().vendor_sku, 'S-4')

    def test_po_id_mode_appends(self):
        po = PurchaseOrderService.create_po(business=self.business)
        r = self.client.post(self.url, {'po_id': po.pk, 'line': {'qty': '1'}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['po_id'], po.pk)

    def test_qty_is_required_for_stock(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('line', r.json())
        r = self.client.post(self.url, {'po': {'business': self.business.pk}, 'line': {}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('qty', r.json()['line'])

    def test_line_inventory_item_refused(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk},
                                        'line': {'qty': '1', 'inventory_item': self.item.pk}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('inventory_item', r.json()['line'])

    def test_worker_forbidden(self):
        self.client.force_authenticate(User.objects.create_user('stock_worker', password='p'))
        r = self.client.post(self.url, {'po': {'business': self.business.pk}, 'line': {'qty': '1'}}, format='json')
        self.assertEqual(r.status_code, 403)
