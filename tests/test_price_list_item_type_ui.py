"""Tests for LineItemType in PriceListItem CRUD."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType
from apps.invoicing.models import PriceListItem


class PriceListItemTypeUITest(TestCase):
    """Tests for LineItemType in PriceListItem forms."""

    @classmethod
    def setUpTestData(cls):
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': True}
        )
        # Create an inactive type to verify it's not shown
        cls.inactive_type, _ = LineItemType.objects.get_or_create(
            code='INACTIVE',
            defaults={'name': 'Inactive Type', 'taxable': False, 'is_active': False}
        )

    def setUp(self):
        self.client = Client()

    def test_create_form_includes_line_item_type(self):
        """Test that create form shows LineItemType field."""
        response = self.client.get(reverse('invoicing:price_list_item_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')

    def test_create_form_shows_only_active_types(self):
        """Test that only active LineItemTypes are shown in the form."""
        response = self.client.get(reverse('invoicing:price_list_item_add'))
        self.assertEqual(response.status_code, 200)
        # Active types should be in the form
        self.assertContains(response, 'Product')
        self.assertContains(response, 'Service')
        # Inactive type should NOT be in the form
        self.assertNotContains(response, 'Inactive Type')

    def test_create_with_line_item_type(self):
        """Test creating PriceListItem with LineItemType."""
        response = self.client.post(reverse('invoicing:price_list_item_add'), {
            'code': 'TEST-001',
            'units': 'each',
            'description': 'Test Product',
            'purchase_price': '50.00',
            'selling_price': '100.00',
            'qty_on_hand': '10',
            'qty_sold': '0',
            'qty_wasted': '0',
            'line_item_type': self.product_type.pk,
        })
        # Should redirect to list on success
        self.assertEqual(response.status_code, 302)
        item = PriceListItem.objects.filter(code='TEST-001').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.line_item_type, self.product_type)

    def test_edit_form_includes_line_item_type(self):
        """Test that edit form shows LineItemType field with current value."""
        item = PriceListItem.objects.create(
            code='EDIT-001',
            description='Edit Test',
            selling_price=Decimal('75.00'),
            line_item_type=self.service_type
        )
        response = self.client.get(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'line_item_type')
        # The current type should be selected
        self.assertContains(response, f'selected>{self.service_type.name}<', html=False)

    def test_edit_updates_line_item_type(self):
        """Test updating LineItemType on existing PriceListItem."""
        item = PriceListItem.objects.create(
            code='UPDATE-001',
            description='Update Test',
            selling_price=Decimal('75.00'),
            line_item_type=self.product_type
        )
        response = self.client.post(
            reverse('invoicing:price_list_item_edit', args=[item.price_list_item_id]),
            {
                'code': 'UPDATE-001',
                'units': '',
                'description': 'Update Test',
                'purchase_price': '0.00',
                'selling_price': '75.00',
                'qty_on_hand': '0',
                'qty_sold': '0',
                'qty_wasted': '0',
                'line_item_type': self.service_type.pk,
            }
        )
        # Should redirect to list on success
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.line_item_type, self.service_type)

    def test_create_without_line_item_type_allowed(self):
        """Test that line_item_type is optional (for now)."""
        response = self.client.post(reverse('invoicing:price_list_item_add'), {
            'code': 'NO-TYPE-001',
            'units': 'each',
            'description': 'No Type Product',
            'purchase_price': '50.00',
            'selling_price': '100.00',
            'qty_on_hand': '10',
            'qty_sold': '0',
            'qty_wasted': '0',
            # No line_item_type field
        })
        # Should redirect to list on success
        self.assertEqual(response.status_code, 302)
        item = PriceListItem.objects.filter(code='NO-TYPE-001').first()
        self.assertIsNotNone(item)
        self.assertIsNone(item.line_item_type)
