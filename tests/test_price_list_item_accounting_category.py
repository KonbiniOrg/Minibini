"""
Tests for InventoryItem.accounting_category field - TDD approach.
Testing linking InventoryItem to AccountingCategory for catalog items.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from apps.core.models import AccountingCategory
from apps.inventory.models import InventoryItem


class InventoryItemAccountingCategoryTest(TestCase):
    """Tests for accounting_category field on InventoryItem model."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.product_type, _ = AccountingCategory.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.freight_type, _ = AccountingCategory.objects.get_or_create(
            code='FRT',
            defaults={'name': 'Freight', 'taxable': True}
        )

    def test_accounting_category_required(self):
        """Test that accounting_category is required."""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            InventoryItem.objects.create(
                code='ITEM-001',
                description='Test Item',
                selling_price=Decimal('100.00')
            )

    def test_accounting_category_can_be_assigned(self):
        """Test that accounting_category can be assigned."""
        item = InventoryItem.objects.create(
            code='ITEM-002',
            description='Product Item',
            selling_price=Decimal('50.00'),
            accounting_category=self.product_type
        )

        self.assertEqual(item.accounting_category, self.product_type)

    def test_accounting_category_can_be_updated(self):
        """Test that accounting_category can be updated."""
        item = InventoryItem.objects.create(
            code='ITEM-003',
            description='Updateable Item',
            selling_price=Decimal('75.00'),
            accounting_category=self.product_type
        )

        item.accounting_category = self.freight_type
        item.save()

        item.refresh_from_db()
        self.assertEqual(item.accounting_category, self.freight_type)

    def test_accounting_category_protect_on_delete(self):
        """Test that deleting a AccountingCategory is protected if InventoryItems reference it."""
        test_type = AccountingCategory.objects.create(
            code='TST',
            name='Test Type'
        )

        InventoryItem.objects.create(
            code='ITEM-004',
            description='Protected Item',
            selling_price=Decimal('25.00'),
            accounting_category=test_type
        )

        with self.assertRaises(ProtectedError):
            test_type.delete()

    def test_accounting_category_related_name(self):
        """Test that AccountingCategory has access to related InventoryItems."""
        item1 = InventoryItem.objects.create(
            code='ITEM-005',
            description='Product 1',
            selling_price=Decimal('10.00'),
            accounting_category=self.product_type
        )
        item2 = InventoryItem.objects.create(
            code='ITEM-006',
            description='Product 2',
            selling_price=Decimal('20.00'),
            accounting_category=self.product_type
        )

        product_items = self.product_type.price_list_items.all()
        self.assertEqual(product_items.count(), 2)
        self.assertIn(item1, product_items)
        self.assertIn(item2, product_items)
