"""B5 — write-off.

Zeroes a lot's QOH and books the remainder to qty_wasted, recording the wastage
history entry (so it's never lost). The row always survives — inventory rows are
shop history, retired manually via is_active.
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth.models import Permission
from apps.core.models import AccountingCategory, User, InventoryHistory
from apps.contacts.models import Contact, Business
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem


def _reference(item, po_number):
    """Pin a PROTECT'd line item to `item`. Rows always survive write-off now;
    this keeps the surviving-row assertions grounded in a referenced item."""
    contact = Contact.objects.create(first_name='R', last_name='Ef')
    biz = Business.objects.create(business_name='V', default_contact=contact)
    po = PurchaseOrder.objects.create(
        business=biz, po_number=po_number, status=PurchaseOrder.STATUS_DRAFT)
    PurchaseOrderLineItem.objects.create(
        purchase_order=po, description='x', qty=Decimal('1'),
        price=Decimal('1'), inventory_item=item)


class WriteOffServiceTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.lot = InventoryItem.objects.create(
            code='WO1', qty_on_hand=Decimal('4.00'),
            accounting_category=self.cat)
        _reference(self.lot, 'PO-WO-SVC')  # referenced; survives write-off for inspection

    def test_write_off_zeroes_qoh_and_books_waste(self):
        InventoryService.write_off(self.lot, reason='water damage')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.qty_on_hand, Decimal('0.00'))
        self.assertEqual(self.lot.qty_wasted, Decimal('4.00'))

    def test_write_off_records_wastage_history(self):
        InventoryService.write_off(self.lot, reason='water damage')
        entry = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=self.lot.pk,
            entry_type='action').latest('timestamp')
        self.assertEqual(entry.changes['qty_change'], '-4.00')
        self.assertEqual(entry.text, 'water damage')

    def test_write_off_empties_and_row_survives(self):
        InventoryService.write_off(self.lot)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.qty_on_hand, Decimal('0.00'))
        self.assertTrue(InventoryItem.objects.filter(pk=self.lot.pk).exists())

    def test_write_off_empty_raises(self):
        empty = InventoryItem.objects.create(
            code='WO2', qty_on_hand=Decimal('0.00'),
            accounting_category=self.cat)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InventoryService.write_off(empty)

    def test_partial_write_off_leaves_balance(self):
        InventoryService.write_off(self.lot, Decimal('1.00'), reason='one mis-cut')
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.qty_on_hand, Decimal('3.00'))  # 4 - 1
        self.assertEqual(self.lot.qty_wasted, Decimal('1.00'))

    def test_write_off_more_than_on_hand_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InventoryService.write_off(self.lot, Decimal('99.00'))

    def test_write_off_non_positive_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InventoryService.write_off(self.lot, Decimal('0.00'))


class WriteOffEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.lot = InventoryItem.objects.create(
            code='WOE', qty_on_hand=Decimal('3.00'),
            accounting_category=self.cat)
        _reference(self.lot, 'PO-WO-EP')  # referenced; survives write-off for inspection

    def _user(self, *atoms):
        u = User.objects.create(username='wo_' + '_'.join(atoms) or 'wo_plain')
        for a in atoms:
            u.user_permissions.add(Permission.objects.get(codename=a))
        return User.objects.get(pk=u.pk)  # reload for perm cache

    def test_financials_can_write_off(self):
        self.client.force_authenticate(self._user('can_manage_financials'))
        resp = self.client.post(f'/api/inventory/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 200)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.qty_on_hand, Decimal('0.00'))

    def test_config_can_write_off(self):
        self.client.force_authenticate(self._user('can_manage_config'))
        resp = self.client.post(f'/api/inventory/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 200)

    def test_plain_user_forbidden(self):
        self.client.force_authenticate(self._user())
        resp = self.client.post(f'/api/inventory/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 403)
