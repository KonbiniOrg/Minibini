from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import AccountingCategory
from apps.inventory.models import PriceListItem
from apps.inventory.forms import PriceListItemForm


class PriceListItemViewsTest(TestCase):
    """Test suite for PriceListItem views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]

        # Create test price list items
        self.item1 = PriceListItem.objects.create(
            code="TEST001",
            units="ea",
            description="Test item 1 description",
            purchase_price=Decimal('10.00'),
            selling_price=Decimal('15.00'),
            qty_on_hand=Decimal('100.00'),
            qty_sold=Decimal('25.00'),
            qty_wasted=Decimal('2.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

        self.item2 = PriceListItem.objects.create(
            code="TEST002",
            units="ea",
            description="Test item 2 description",
            purchase_price=Decimal('20.00'),
            selling_price=Decimal('30.00'),
            qty_on_hand=Decimal('50.00'),
            qty_sold=Decimal('10.00'),
            qty_wasted=Decimal('1.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

    def test_price_list_item_list_view(self):
        """Test the list view displays all price list items."""
        url = reverse('inventory:price_list_item_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Price List Items')
        self.assertContains(response, 'TEST001')
        self.assertContains(response, 'TEST002')
        self.assertContains(response, 'Test item 1 description')
        self.assertContains(response, 'Test item 2 description')
        self.assertContains(response, '15.00')  # Selling price
        self.assertContains(response, '30.00')  # Selling price
        self.assertContains(response, 'Add New Price List Item')

    def test_price_list_item_add_view_get(self):
        """Test the add view displays the form."""
        url = reverse('inventory:price_list_item_add')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Price List Item')
        self.assertIsInstance(response.context['form'], PriceListItemForm)
        self.assertContains(response, 'Code')
        self.assertContains(response, 'Description')
        self.assertContains(response, 'Create Item')

    def test_price_list_item_add_view_post_valid(self):
        """Test successfully adding a new price list item."""
        url = reverse('inventory:price_list_item_add')
        data = {
            'code': 'NEW001',
            'units': 'kg',
            'description': 'New test item',
            'purchase_price': '25.50',
            'selling_price': '35.75',
            'qty_on_hand': '200.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
            'is_inventoried': True,
            'accounting_category': self.category.pk,
        }

        response = self.client.post(url, data, follow=True)

        # Check redirect to list view
        self.assertRedirects(response, reverse('inventory:price_list_item_list'))

        # Check item was created
        new_item = PriceListItem.objects.get(code='NEW001')
        self.assertEqual(new_item.units, 'kg')
        self.assertEqual(new_item.description, 'New test item')
        self.assertEqual(new_item.purchase_price, Decimal('25.50'))
        self.assertEqual(new_item.selling_price, Decimal('35.75'))
        self.assertEqual(new_item.qty_on_hand, Decimal('200.00'))

        # Check success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('created successfully', str(messages[0]))

    def test_price_list_item_add_view_post_duplicate_code(self):
        """Test that duplicate item codes are rejected."""
        url = reverse('inventory:price_list_item_add')
        data = {
            'code': 'TEST001',  # Duplicate code
            'units': 'ea',
            'description': 'Duplicate item',
            'purchase_price': '10.00',
            'selling_price': '15.00',
            'qty_on_hand': '100.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00'
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Item with code ')
        self.assertContains(response, 'TEST001')
        self.assertContains(response, ' already exists.')

        # Check no new item was created
        self.assertEqual(PriceListItem.objects.filter(code='TEST001').count(), 1)

    def test_price_list_item_edit_view_get(self):
        """Test the edit view displays the form with existing data."""
        url = reverse('inventory:price_list_item_edit',
                     kwargs={'item_id': self.item1.price_list_item_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Edit Price List Item: {self.item1.code}')
        self.assertIsInstance(response.context['form'], PriceListItemForm)
        self.assertEqual(response.context['item'], self.item1)
        self.assertContains(response, 'TEST001')
        self.assertContains(response, 'Test item 1 description')
        self.assertContains(response, 'Update Item')

    def test_price_list_item_edit_view_post_valid(self):
        """Test successfully editing an existing price list item."""
        url = reverse('inventory:price_list_item_edit',
                     kwargs={'item_id': self.item1.price_list_item_id})
        data = {
            'code': 'TEST001',  # Keep same code
            'units': 'pcs',  # Changed
            'description': 'Updated test item description',  # Changed
            'purchase_price': '12.00',  # Changed
            'selling_price': '18.00',  # Changed
            'qty_on_hand': '90.00',  # Changed
            'qty_sold': '30.00',  # Changed
            'qty_wasted': '3.00',  # Changed
            'is_inventoried': True,
            'accounting_category': self.category.pk,
        }

        response = self.client.post(url, data, follow=True)

        # Check redirect to list view
        self.assertRedirects(response, reverse('inventory:price_list_item_list'))

        # Check item was updated
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.units, 'pcs')
        self.assertEqual(self.item1.description, 'Updated test item description')
        self.assertEqual(self.item1.purchase_price, Decimal('12.00'))
        self.assertEqual(self.item1.selling_price, Decimal('18.00'))
        self.assertEqual(self.item1.qty_on_hand, Decimal('90.00'))
        self.assertEqual(self.item1.qty_sold, Decimal('30.00'))
        self.assertEqual(self.item1.qty_wasted, Decimal('3.00'))

        # Check success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('updated successfully', str(messages[0]))

    def test_price_list_item_edit_view_nonexistent(self):
        """Test editing a non-existent price list item returns 404."""
        url = reverse('inventory:price_list_item_edit', kwargs={'item_id': 99999})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_price_list_item_form_validation(self):
        """Test form validation for PriceListItemForm."""
        # Test with empty required field
        form = PriceListItemForm(data={
            'code': '',  # Required field
            'units': 'ea',
            'description': 'Test',
            'purchase_price': '10.00',
            'selling_price': '15.00',
            'qty_on_hand': '100.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
            'accounting_category': self.category.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('code', form.errors)

        # Test with negative price
        form = PriceListItemForm(data={
            'code': 'NEGATIVE001',
            'units': 'ea',
            'description': 'Test',
            'purchase_price': '-10.00',  # Negative not allowed
            'selling_price': '15.00',
            'qty_on_hand': '100.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
            'accounting_category': self.category.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('purchase_price', form.errors)

        # Test valid form
        form = PriceListItemForm(data={
            'code': 'VALID001',
            'units': 'ea',
            'description': 'Valid test item',
            'purchase_price': '10.00',
            'selling_price': '15.00',
            'qty_on_hand': '100.00',
            'qty_sold': '25.00',
            'qty_wasted': '2.00',
            'accounting_category': self.category.pk,
        })
        self.assertTrue(form.is_valid())

    def test_price_list_items_ordered_by_code(self):
        """Test that price list items are displayed in alphabetical order by code."""
        # Create additional items with codes that should sort differently
        PriceListItem.objects.create(
            code="AAA001",
            description="Should be first",
            purchase_price=Decimal('5.00'),
            selling_price=Decimal('10.00'),
            accounting_category=self.category
        )
        PriceListItem.objects.create(
            code="ZZZ999",
            description="Should be last",
            purchase_price=Decimal('5.00'),
            selling_price=Decimal('10.00'),
            accounting_category=self.category
        )

        url = reverse('inventory:price_list_item_list')
        response = self.client.get(url)

        items = response.context['items']
        codes = [item.code for item in items]

        # Check that codes are sorted
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(codes[0], "AAA001")
        self.assertEqual(codes[-1], "ZZZ999")