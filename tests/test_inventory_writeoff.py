"""B5 — write-off.

Zeroes a lot's QOH and books the remainder to qty_wasted, recording the wastage
history entry (so it's never lost). Afterward the lot is a finished lot (hidden)
unless it still has earmarks.
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth.models import Permission
from apps.core.models import AccountingCategory, User, InventoryHistory
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService


class WriteOffServiceTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.lot = InventoryItem.objects.create(
            code='WO1', is_catalog=False, qty_on_hand=Decimal('4.00'),
            accounting_category=self.cat)

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

    def test_write_off_makes_lot_finished(self):
        InventoryService.write_off(self.lot)
        self.lot.refresh_from_db()
        self.assertTrue(self.lot.is_finished_lot)

    def test_write_off_empty_raises(self):
        empty = InventoryItem.objects.create(
            code='WO2', is_catalog=False, qty_on_hand=Decimal('0.00'),
            accounting_category=self.cat)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InventoryService.write_off(empty)


class WriteOffEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.lot = InventoryItem.objects.create(
            code='WOE', is_catalog=False, qty_on_hand=Decimal('3.00'),
            accounting_category=self.cat)

    def _user(self, *atoms):
        u = User.objects.create(username='wo_' + '_'.join(atoms) or 'wo_plain')
        for a in atoms:
            u.user_permissions.add(Permission.objects.get(codename=a))
        return User.objects.get(pk=u.pk)  # reload for perm cache

    def test_financials_can_write_off(self):
        self.client.force_authenticate(self._user('can_manage_financials'))
        resp = self.client.post(f'/api/price-list-items/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 200)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.qty_on_hand, Decimal('0.00'))

    def test_config_can_write_off(self):
        self.client.force_authenticate(self._user('can_manage_config'))
        resp = self.client.post(f'/api/price-list-items/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 200)

    def test_plain_user_forbidden(self):
        self.client.force_authenticate(self._user())
        resp = self.client.post(f'/api/price-list-items/{self.lot.pk}/write-off/')
        self.assertEqual(resp.status_code, 403)
