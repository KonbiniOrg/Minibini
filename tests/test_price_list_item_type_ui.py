"""Tests for AccountingCategory in PriceListItem CRUD."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import AccountingCategory
from apps.inventory.models import PriceListItem


class PriceListItemTypeUITest(TestCase):
    """Tests for AccountingCategory in PriceListItem forms."""

    @classmethod
    def setUpTestData(cls):
        cls.product_type, _ = AccountingCategory.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.service_type, _ = AccountingCategory.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': True}
        )
        # Create an inactive type to verify it's not shown
        cls.inactive_type, _ = AccountingCategory.objects.get_or_create(
            code='INACTIVE',
            defaults={'name': 'Inactive Type', 'taxable': False, 'is_active': False}
        )

    def setUp(self):
        self.client = Client()

    def test_create_form_includes_accounting_category(self):
        """Test that create form shows AccountingCategory field."""
        response = self.client.get(reverse('inventory:price_list_item_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')

    def test_create_form_shows_only_active_types(self):
        """Test that only active AccountingCategorys are shown in the form."""
        response = self.client.get(reverse('inventory:price_list_item_add'))
        self.assertEqual(response.status_code, 200)
        # Active types should be in the form
        self.assertContains(response, 'Product')
        self.assertContains(response, 'Service')
        # Inactive type should NOT be in the form
        self.assertNotContains(response, 'Inactive Type')

    def test_create_with_accounting_category(self):
        """Test creating PriceListItem with AccountingCategory."""
        response = self.client.post(reverse('inventory:price_list_item_add'), {
            'code': 'TEST-001',
            'units': 'ea',
            'description': 'Test Product',
            'purchase_price': '50.00',
            'selling_price': '100.00',
            'qty_on_hand': '10',
            'qty_sold': '0',
            'qty_wasted': '0',
            'accounting_category': self.product_type.pk,
        })
        # Should redirect to list on success
        self.assertEqual(response.status_code, 302)
        item = PriceListItem.objects.filter(code='TEST-001').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.accounting_category, self.product_type)

    def test_edit_form_includes_accounting_category(self):
        """Test that edit form shows AccountingCategory field with current value."""
        item = PriceListItem.objects.create(
            code='EDIT-001',
            description='Edit Test',
            selling_price=Decimal('75.00'),
            accounting_category=self.service_type
        )
        response = self.client.get(
            reverse('inventory:price_list_item_edit', args=[item.price_list_item_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounting_category')
        # The current type should be selected
        self.assertContains(response, f'selected>{self.service_type.name}<', html=False)

    def test_edit_updates_accounting_category(self):
        """Test updating AccountingCategory on existing PriceListItem."""
        item = PriceListItem.objects.create(
            code='UPDATE-001',
            description='Update Test',
            selling_price=Decimal('75.00'),
            accounting_category=self.product_type
        )
        response = self.client.post(
            reverse('inventory:price_list_item_edit', args=[item.price_list_item_id]),
            {
                'code': 'UPDATE-001',
                'units': 'ea',
                'description': 'Update Test',
                'purchase_price': '0.00',
                'selling_price': '75.00',
                'qty_on_hand': '0',
                'qty_sold': '0',
                'qty_wasted': '0',
                'accounting_category': self.service_type.pk,
            }
        )
        # Should redirect to list on success
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.accounting_category, self.service_type)

    def test_create_without_accounting_category_rejected(self):
        """Test that accounting_category is required."""
        response = self.client.post(reverse('inventory:price_list_item_add'), {
            'code': 'NO-TYPE-001',
            'units': 'ea',
            'description': 'No Type Product',
            'purchase_price': '50.00',
            'selling_price': '100.00',
            'qty_on_hand': '10',
            'qty_sold': '0',
            'qty_wasted': '0',
            # No accounting_category field
        })
        # Should NOT redirect - form should show error
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(PriceListItem.objects.filter(code='NO-TYPE-001').exists())
