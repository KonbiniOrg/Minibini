"""
Tests for PriceListItem.line_item_type field - TDD approach.
Testing linking PriceListItem to LineItemType for catalog items.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from apps.core.models import LineItemType
from apps.invoicing.models import PriceListItem


class PriceListItemLineItemTypeTest(TestCase):
    """Tests for line_item_type field on PriceListItem model."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.freight_type, _ = LineItemType.objects.get_or_create(
            code='FRT',
            defaults={'name': 'Freight', 'taxable': True}
        )

    def test_line_item_type_nullable_initially(self):
        """Test that line_item_type is nullable (for migration strategy)."""
        item = PriceListItem.objects.create(
            code='ITEM-001',
            description='Test Item',
            selling_price=Decimal('100.00')
        )

        self.assertIsNone(item.line_item_type)

    def test_line_item_type_can_be_assigned(self):
        """Test that line_item_type can be assigned."""
        item = PriceListItem.objects.create(
            code='ITEM-002',
            description='Product Item',
            selling_price=Decimal('50.00'),
            line_item_type=self.product_type
        )

        self.assertEqual(item.line_item_type, self.product_type)

    def test_line_item_type_can_be_updated(self):
        """Test that line_item_type can be updated."""
        item = PriceListItem.objects.create(
            code='ITEM-003',
            description='Updateable Item',
            selling_price=Decimal('75.00'),
            line_item_type=self.product_type
        )

        item.line_item_type = self.freight_type
        item.save()

        item.refresh_from_db()
        self.assertEqual(item.line_item_type, self.freight_type)

    def test_line_item_type_protect_on_delete(self):
        """Test that deleting a LineItemType is protected if PriceListItems reference it."""
        test_type = LineItemType.objects.create(
            code='TST',
            name='Test Type'
        )

        PriceListItem.objects.create(
            code='ITEM-004',
            description='Protected Item',
            selling_price=Decimal('25.00'),
            line_item_type=test_type
        )

        with self.assertRaises(ProtectedError):
            test_type.delete()

    def test_line_item_type_related_name(self):
        """Test that LineItemType has access to related PriceListItems."""
        item1 = PriceListItem.objects.create(
            code='ITEM-005',
            description='Product 1',
            selling_price=Decimal('10.00'),
            line_item_type=self.product_type
        )
        item2 = PriceListItem.objects.create(
            code='ITEM-006',
            description='Product 2',
            selling_price=Decimal('20.00'),
            line_item_type=self.product_type
        )

        product_items = self.product_type.price_list_items.all()
        self.assertEqual(product_items.count(), 2)
        self.assertIn(item1, product_items)
        self.assertIn(item2, product_items)
