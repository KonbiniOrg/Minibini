from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder


class OrderStockTest(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        cat = AccountingCategory.objects.create(name='c')
        self.item = InventoryItem.objects.create(
            code='SHEET-3', accounting_category=cat,
            qty_on_hand=Decimal('1'), purchase_price=Decimal('10'),
        )

    def test_creates_draft_po_with_unlinked_line(self):
        po, li = InventoryService.order_stock(self.item, Decimal('5'))
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertEqual(li.inventory_item_id, self.item.pk)
        self.assertEqual(li.qty, Decimal('5'))
        self.assertIsNone(li.task_id)
        self.assertIsNone(li.linked_material)

    def test_appends_to_given_draft(self):
        po, _ = InventoryService.order_stock(self.item, Decimal('2'))
        po2, li2 = InventoryService.order_stock(self.item, Decimal('3'), po=po)
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.count(), 2)

    def test_refuses_non_draft_po(self):
        po, _ = InventoryService.order_stock(self.item, Decimal('2'))
        PurchaseOrder.objects.filter(pk=po.pk).update(
            status=PurchaseOrder.STATUS_ISSUED)
        po.refresh_from_db()
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('1'), po=po)

    def test_refuses_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('0'))
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('-1'))
