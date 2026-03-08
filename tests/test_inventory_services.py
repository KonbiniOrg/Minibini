"""Tests for inventory app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError


class InventoryServiceTest(TestCase):
    """Tests for InventoryService create/update methods."""

    def test_create_item(self):
        """Create a new PriceListItem via service."""
        pli = InventoryService.create_item(
            code='MAT-001', description='Steel plate', units='sheets',
            purchase_price=Decimal('50.00'), selling_price=Decimal('75.00'),
        )
        self.assertEqual(pli.code, 'MAT-001')
        self.assertEqual(pli.description, 'Steel plate')
        self.assertEqual(pli.units, 'sheets')
        self.assertEqual(pli.purchase_price, Decimal('50.00'))
        self.assertEqual(pli.selling_price, Decimal('75.00'))
        self.assertIsNotNone(pli.pk)

    def test_create_item_with_defaults(self):
        """Create with minimal args — defaults should apply."""
        pli = InventoryService.create_item(code='MAT-002', description='Bolts')
        self.assertEqual(pli.purchase_price, Decimal('0.00'))
        self.assertEqual(pli.selling_price, Decimal('0.00'))
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))
        self.assertTrue(pli.is_active)
        self.assertFalse(pli.is_inventoried)

    def test_create_item_inventoried(self):
        """Create an inventoried item with initial stock."""
        pli = InventoryService.create_item(
            code='INV-001', description='Lumber', units='bd ft',
            is_inventoried=True, qty_on_hand=Decimal('100.00'),
        )
        self.assertTrue(pli.is_inventoried)
        self.assertEqual(pli.qty_on_hand, Decimal('100.00'))

    def test_update_item(self):
        """Update an existing PriceListItem by PK."""
        pli = PriceListItem.objects.create(
            code='MAT-001', description='Steel', units='sheets',
        )
        updated = InventoryService.update_item(
            pli.pk, description='Stainless steel', selling_price=Decimal('80.00'),
        )
        self.assertEqual(updated.description, 'Stainless steel')
        self.assertEqual(updated.selling_price, Decimal('80.00'))
        self.assertEqual(updated.code, 'MAT-001')  # unchanged

    def test_update_item_persists(self):
        """Update should be persisted to database."""
        pli = PriceListItem.objects.create(code='MAT-001', description='Steel')
        InventoryService.update_item(pli.pk, description='Aluminum')
        refreshed = PriceListItem.objects.get(pk=pli.pk)
        self.assertEqual(refreshed.description, 'Aluminum')

    def test_update_item_not_found(self):
        """Updating a nonexistent PK raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            InventoryService.update_item(99999, description='Nope')
