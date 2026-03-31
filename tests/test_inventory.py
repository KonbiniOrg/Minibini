from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.inventory.models import PriceListItem
from apps.inventory.forms import InventoryItemForm


class InventoryItemModelTest(TestCase):
    """Tests for inventoried PriceListItem behavior."""

    def test_create_inventoried_item(self):
        item = PriceListItem.objects.create(
            code='TEST.001',
            description='Test plywood sheet',
            units='sq ft',
            qty_on_hand=Decimal('10.00'),
            purchase_price=Decimal('50.00'),
            selling_price=Decimal('100.00'),
            is_inventoried=True,
        )
        self.assertEqual(item.code, 'TEST.001')
        self.assertEqual(item.description, 'Test plywood sheet')
        self.assertEqual(item.units, 'sq ft')
        self.assertEqual(item.qty_on_hand, Decimal('10.00'))
        self.assertEqual(item.purchase_price, Decimal('50.00'))
        self.assertEqual(item.selling_price, Decimal('100.00'))
        self.assertTrue(item.is_active)
        self.assertTrue(item.is_inventoried)

    def test_default_values(self):
        item = PriceListItem.objects.create(code='TEST.002', is_inventoried=True)
        self.assertEqual(item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(item.qty_sold, Decimal('0.00'))
        self.assertEqual(item.qty_wasted, Decimal('0.00'))
        self.assertEqual(item.purchase_price, Decimal('0.00'))
        self.assertEqual(item.selling_price, Decimal('0.00'))
        self.assertTrue(item.is_active)
        self.assertTrue(item.is_inventoried)

    def test_str_representation(self):
        item = PriceListItem.objects.create(
            code='BBPLY.75',
            description='4x8 x 3/4" Baltic Birch plywood',
            is_inventoried=True,
        )
        self.assertEqual(str(item), "BBPLY.75 - 4x8 x 3/4\" Baltic Birch plywood")

    def test_soft_delete(self):
        item = PriceListItem.objects.create(code='TEST.003', is_inventoried=True)
        item.is_active = False
        item.save()
        item.refresh_from_db()
        self.assertFalse(item.is_active)

    def test_is_inventoried_default_false(self):
        item = PriceListItem.objects.create(code='TEST.004')
        self.assertFalse(item.is_inventoried)


class InventoryItemFormTest(TestCase):
    """Tests for the InventoryItemForm."""

    def _form_data(self, **overrides):
        """Helper to build valid form data with defaults."""
        data = {
            'code': 'NEW.001',
            'description': 'New test item',
            'units': 'sq ft',
            'qty_on_hand': '5.00',
            'purchase_price': '25.00',
            'selling_price': '50.00',
        }
        data.update(overrides)
        return data

    def test_valid_form(self):
        form = InventoryItemForm(data=self._form_data())
        self.assertTrue(form.is_valid())

    def test_save_sets_units(self):
        form = InventoryItemForm(data=self._form_data(units='sheets'))
        self.assertTrue(form.is_valid())
        item = form.save()
        self.assertEqual(item.units, 'sheets')

    def test_save_sets_is_inventoried(self):
        form = InventoryItemForm(data=self._form_data())
        self.assertTrue(form.is_valid())
        item = form.save()
        self.assertTrue(item.is_inventoried)

    def test_invalid_unit_rejected(self):
        form = InventoryItemForm(data=self._form_data(units='pallets'))
        self.assertFalse(form.is_valid())
        self.assertIn('units', form.errors)

    def test_duplicate_code_rejected(self):
        PriceListItem.objects.create(code='DUPE.001', is_inventoried=True)
        form = InventoryItemForm(data=self._form_data(code='DUPE.001'))
        self.assertFalse(form.is_valid())
        self.assertIn('code', form.errors)

    def test_duplicate_code_allowed_on_same_instance(self):
        item = PriceListItem.objects.create(code='EDIT.001', is_inventoried=True)
        form = InventoryItemForm(
            data=self._form_data(code='EDIT.001'),
            instance=item,
        )
        self.assertTrue(form.is_valid())

    def test_duplicate_code_rejected_even_if_not_inventoried(self):
        """Duplicate code is always rejected (unique constraint at model level)."""
        PriceListItem.objects.create(code='DUPE.002', is_inventoried=False)
        form = InventoryItemForm(data=self._form_data(code='DUPE.002'))
        self.assertFalse(form.is_valid())
        self.assertIn('code', form.errors)

    def test_negative_purchase_price_rejected(self):
        form = InventoryItemForm(data=self._form_data(purchase_price='-10.00'))
        self.assertFalse(form.is_valid())
        self.assertIn('purchase_price', form.errors)

    def test_negative_selling_price_rejected(self):
        form = InventoryItemForm(data=self._form_data(selling_price='-5.00'))
        self.assertFalse(form.is_valid())
        self.assertIn('selling_price', form.errors)

    def test_negative_qty_on_hand_rejected(self):
        form = InventoryItemForm(data=self._form_data(qty_on_hand='-1.00'))
        self.assertFalse(form.is_valid())
        self.assertIn('qty_on_hand', form.errors)

    def test_edit_populates_unit(self):
        item = PriceListItem.objects.create(code='UNIT.001', units='lbs', is_inventoried=True)
        form = InventoryItemForm(instance=item)
        self.assertEqual(form.initial.get('units'), 'lbs')


class InventoryListViewTest(TestCase):
    """Tests for the inventory list view."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('inventory:inventory_list')
        self.active_item = PriceListItem.objects.create(
            code='ACTIVE.001',
            description='Active item',
            is_active=True,
            is_inventoried=True,
        )
        self.inactive_item = PriceListItem.objects.create(
            code='INACTIVE.001',
            description='Inactive item',
            is_active=False,
            is_inventoried=True,
        )
        self.non_inventoried = PriceListItem.objects.create(
            code='NONINV.001',
            description='Not inventoried',
            is_active=True,
            is_inventoried=False,
        )

    def test_list_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_list_shows_active_inventoried_items(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'ACTIVE.001')

    def test_list_hides_inactive_items(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'INACTIVE.001')

    def test_list_hides_non_inventoried_items(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'NONINV.001')

    def test_list_has_add_link(self):
        response = self.client.get(self.url)
        self.assertContains(response, reverse('inventory:inventory_item_add'))


class InventoryItemAddViewTest(TestCase):
    """Tests for the inventory add view."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('inventory:inventory_item_add')

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_get_shows_form(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Add Inventory Item')
        self.assertContains(response, 'Add Item')

    def test_post_valid_creates_item(self):
        data = {
            'code': 'NEW.001',
            'description': 'New item',
            'units': 'sheets',
            'qty_on_hand': '10.00',
            'purchase_price': '25.00',
            'selling_price': '50.00',
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('inventory:inventory_list'))
        item = PriceListItem.objects.get(code='NEW.001')
        self.assertEqual(item.units, 'sheets')
        self.assertEqual(item.qty_on_hand, Decimal('10.00'))
        self.assertTrue(item.is_inventoried)

    def test_post_with_valid_units(self):
        data = {
            'code': 'CUST.001',
            'description': 'Custom unit item',
            'units': 'lbs',
            'qty_on_hand': '3.00',
            'purchase_price': '10.00',
            'selling_price': '20.00',
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('inventory:inventory_list'))
        item = PriceListItem.objects.get(code='CUST.001')
        self.assertEqual(item.units, 'lbs')

    def test_post_invalid_stays_on_form(self):
        data = {
            'code': '',
            'description': '',
            'units': 'sq ft',
            'qty_on_hand': '0',
            'purchase_price': '0',
            'selling_price': '0',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PriceListItem.objects.filter(is_inventoried=True).count(), 0)


class InventoryItemEditViewTest(TestCase):
    """Tests for the inventory edit view."""

    def setUp(self):
        self.client = Client()
        self.item = PriceListItem.objects.create(
            code='EDIT.001',
            description='Item to edit',
            units='sq ft',
            qty_on_hand=Decimal('5.00'),
            purchase_price=Decimal('20.00'),
            selling_price=Decimal('40.00'),
            is_inventoried=True,
        )
        self.url = reverse('inventory:inventory_item_edit', args=[self.item.price_list_item_id])

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_get_shows_existing_data(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'EDIT.001')
        self.assertContains(response, 'Update Item')

    def test_post_updates_item(self):
        data = {
            'code': 'EDIT.001',
            'description': 'Updated description',
            'units': 'lbs',
            'qty_on_hand': '15.00',
            'purchase_price': '30.00',
            'selling_price': '60.00',
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse('inventory:inventory_list'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, 'Updated description')
        self.assertEqual(self.item.units, 'lbs')
        self.assertEqual(self.item.qty_on_hand, Decimal('15.00'))

    def test_edit_nonexistent_item_returns_404(self):
        url = reverse('inventory:inventory_item_edit', args=[99999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_edit_non_inventoried_item_returns_404(self):
        non_inv = PriceListItem.objects.create(code='NONINV.001', is_inventoried=False)
        url = reverse('inventory:inventory_item_edit', args=[non_inv.price_list_item_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_post_duplicate_code_stays_on_form(self):
        PriceListItem.objects.create(code='OTHER.001', is_inventoried=True)
        data = {
            'code': 'OTHER.001',
            'description': 'Trying duplicate',
            'units_select': 'sq ft',
            'units_custom': '',
            'qty_on_hand': '1.00',
            'purchase_price': '10.00',
            'selling_price': '20.00',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.code, 'EDIT.001')
