"""Tests for inventory app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError


class InventoryServiceTest(TestCase):
    """Tests for InventoryService create/update methods."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]

    def test_create_item(self):
        """Create a new InventoryItem via service."""
        pli = InventoryService.create_item(
            code='MAT-001', description='Steel plate', units='sheet',
            purchase_price=Decimal('50.00'), selling_price=Decimal('75.00'),
            accounting_category=self.category,
        )
        self.assertEqual(pli.code, 'MAT-001')
        self.assertEqual(pli.description, 'Steel plate')
        self.assertEqual(pli.units, 'sheet')
        self.assertEqual(pli.purchase_price, Decimal('50.00'))
        self.assertEqual(pli.selling_price, Decimal('75.00'))
        self.assertIsNotNone(pli.pk)

    def test_create_item_with_defaults(self):
        """Create with minimal args — defaults should apply."""
        pli = InventoryService.create_item(code='MAT-002', description='Bolts', accounting_category=self.category)
        self.assertEqual(pli.purchase_price, Decimal('0.00'))
        self.assertEqual(pli.selling_price, Decimal('0.00'))
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))
        self.assertTrue(pli.is_active)

    def test_create_item_inventoried(self):
        """Create an inventoried item with initial stock."""
        pli = InventoryService.create_item(
            code='INV-001', description='Lumber', units='bd ft',
            qty_on_hand=Decimal('100.00'),
            accounting_category=self.category,
        )
        self.assertEqual(pli.qty_on_hand, Decimal('100.00'))

    def test_update_item(self):
        """Update an existing InventoryItem by PK."""
        pli = InventoryItem.objects.create(
            code='MAT-001', description='Steel', units='sheet',
            accounting_category=self.category,
        )
        updated = InventoryService.update_item(
            pli.pk, description='Stainless steel', selling_price=Decimal('80.00'),
        )
        self.assertEqual(updated.description, 'Stainless steel')
        self.assertEqual(updated.selling_price, Decimal('80.00'))
        self.assertEqual(updated.code, 'MAT-001')  # unchanged

    def test_update_item_persists(self):
        """Update should be persisted to database."""
        pli = InventoryItem.objects.create(code='MAT-001', description='Steel', accounting_category=self.category)
        InventoryService.update_item(pli.pk, description='Aluminum')
        refreshed = InventoryItem.objects.get(pk=pli.pk)
        self.assertEqual(refreshed.description, 'Aluminum')

    def test_update_item_not_found(self):
        """Updating a nonexistent PK raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            InventoryService.update_item(99999, description='Nope')




class InventoryMarkupTest(TestCase):
    """Phase B0: markup-config drives selling_price at creation only."""

    def setUp(self):
        from apps.core.models import Configuration
        self.category = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})

    def test_markup_applied_when_selling_unset(self):
        pli = InventoryService.create_item(
            code='MK-1', purchase_price=Decimal('100.00'),
            accounting_category=self.category)
        self.assertEqual(pli.selling_price, Decimal('125.00'))

    def test_explicit_selling_respected(self):
        pli = InventoryService.create_item(
            code='MK-2', purchase_price=Decimal('100.00'),
            selling_price=Decimal('150.00'), accounting_category=self.category)
        self.assertEqual(pli.selling_price, Decimal('150.00'))

    def test_update_does_not_reapply_markup(self):
        pli = InventoryService.create_item(
            code='MK-3', purchase_price=Decimal('100.00'),
            accounting_category=self.category)  # selling -> 125
        updated = InventoryService.update_item(
            pli.pk, purchase_price=Decimal('200.00'))
        self.assertEqual(updated.selling_price, Decimal('125.00'))  # unchanged

    def test_zero_markup_sell_equals_cost(self):
        from apps.core.models import Configuration
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '0'})
        pli = InventoryService.create_item(
            code='MK-4', purchase_price=Decimal('100.00'),
            accounting_category=self.category)
        self.assertEqual(pli.selling_price, Decimal('100.00'))

    def test_unset_config_defaults_to_zero_markup(self):
        from apps.core.models import Configuration
        Configuration.objects.filter(
            key='default_material_markup_percent').delete()
        pli = InventoryService.create_item(
            code='MK-5', purchase_price=Decimal('80.00'),
            accounting_category=self.category)
        self.assertEqual(pli.selling_price, Decimal('80.00'))
