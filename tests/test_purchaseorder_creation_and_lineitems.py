"""Tests for creating PurchaseOrders and adding LineItems from Price List"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Contact, Business
from apps.invoicing.models import PriceListItem
from apps.core.models import Configuration


class PurchaseOrderCreationTests(TestCase):
    """Test creating PurchaseOrders with Business association."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create default contacts for businesses
        self.default_contact1 = Contact.objects.create(first_name='Default Contact 1', last_name='', email='default.contact.1@test.com')
        self.default_contact2 = Contact.objects.create(first_name='Default Contact 2', last_name='', email='default.contact.2@test.com')

        # Create a test business
        self.business = Business.objects.create(
            business_name='Test Vendor Co',
            our_reference_code='VENDOR001',
            default_contact=self.default_contact1
        )

        # Create another business for testing
        self.business2 = Business.objects.create(
            business_name='Another Vendor',
            our_reference_code='VENDOR002',
            default_contact=self.default_contact2
        )

    def test_get_purchase_order_create_page(self):
        """Test GET request to create purchase order page shows form."""
        url = reverse('purchasing:purchase_order_create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Purchase Order')
        self.assertContains(response, 'Business')
        self.assertContains(response, 'PO number will be assigned automatically')

    def test_create_purchase_order_with_business(self):
        """Test creating a purchase order with a business."""
        url = reverse('purchasing:purchase_order_create')

        form_data = {
            'business': str(self.business.business_id),
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to PO detail page
        self.assertEqual(response.status_code, 302)

        # Check PO was created
        po = PurchaseOrder.objects.first()
        self.assertIsNotNone(po)
        self.assertEqual(po.business, self.business)
        self.assertIsNone(po.job)
        self.assertTrue(po.po_number)  # Should have auto-generated number

        # Should redirect to PO detail
        self.assertRedirects(response, reverse('purchasing:purchase_order_detail', args=[po.po_id]))

    def test_create_purchase_order_auto_generates_po_number(self):
        """Test that PO number is auto-generated using NumberGenerationService."""
        url = reverse('purchasing:purchase_order_create')

        form_data = {
            'business': str(self.business.business_id),
        }

        response = self.client.post(url, data=form_data)

        # Check PO number was generated
        po = PurchaseOrder.objects.first()
        self.assertIsNotNone(po.po_number)
        # Should match pattern from Configuration
        self.assertTrue(po.po_number.startswith('PO-'))

    def test_create_purchase_order_missing_business(self):
        """Test that business is required when creating a PO."""
        url = reverse('purchasing:purchase_order_create')

        form_data = {}  # Missing business

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No PO should be created
        pos = PurchaseOrder.objects.all()
        self.assertEqual(pos.count(), 0)

    def test_multiple_purchase_orders_can_be_created(self):
        """Test that multiple POs can be created."""
        url = reverse('purchasing:purchase_order_create')

        # Create first PO
        form_data_1 = {
            'business': str(self.business.business_id),
        }
        self.client.post(url, data=form_data_1)

        # Create second PO
        form_data_2 = {
            'business': str(self.business2.business_id),
        }
        self.client.post(url, data=form_data_2)

        # Check both POs were created
        pos = PurchaseOrder.objects.all().order_by('po_id')
        self.assertEqual(pos.count(), 2)

        # Verify they have different businesses
        self.assertEqual(pos[0].business, self.business)
        self.assertEqual(pos[1].business, self.business2)

        # Verify they have different PO numbers
        self.assertNotEqual(pos[0].po_number, pos[1].po_number)


class PurchaseOrderLineItemAdditionTests(TestCase):
    """Test adding line items to PurchaseOrders from Price List."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a test business
        self.business = Business.objects.create(
            business_name='Test Vendor Co',
            our_reference_code='VENDOR001',
            default_contact=self.default_contact
        )

        # Create a purchase order
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001'
        )

        # Create price list items
        self.price_list_item = PriceListItem.objects.create(
            code='WIDGET001',
            units='each',
            description='Widget Type A',
            purchase_price=Decimal('25.00'),
            selling_price=Decimal('50.00'),
            qty_on_hand=Decimal('100.00')
        )

        self.price_list_item2 = PriceListItem.objects.create(
            code='GADGET001',
            units='box',
            description='Gadget Type B',
            purchase_price=Decimal('15.50'),
            selling_price=Decimal('30.00'),
            qty_on_hand=Decimal('50.00')
        )

    def test_get_add_line_item_page(self):
        """Test GET request to add line item page shows form."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item to Purchase Order')
        self.assertContains(response, 'PO-TEST-001')
        self.assertContains(response, 'Price List Item')
        self.assertContains(response, 'Quantity')

    def test_add_line_item_from_price_list(self):
        """Test adding a line item from price list."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '10.00',
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to PO detail page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('purchasing:purchase_order_detail', args=[self.purchase_order.po_id]))

        # Check line item was created
        line_item = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order).first()
        self.assertIsNotNone(line_item)

        # Verify values were copied from price list item
        self.assertEqual(line_item.description, self.price_list_item.description)
        self.assertEqual(line_item.units, self.price_list_item.units)
        self.assertEqual(line_item.price_currency, self.price_list_item.purchase_price)  # IMPORTANT: Uses purchase_price

        # Verify qty came from form
        self.assertEqual(line_item.qty, Decimal('10.00'))

        # Verify price_list_item reference is set
        self.assertEqual(line_item.price_list_item, self.price_list_item)

        # Verify task is not set
        self.assertIsNone(line_item.task)

    def test_line_item_uses_purchase_price_not_selling_price(self):
        """Test that line items use purchase_price from PriceListItem, not selling_price."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '5.00',
        }

        response = self.client.post(url, data=form_data)

        # Check line item uses purchase_price (25.00), not selling_price (50.00)
        line_item = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order).first()
        self.assertEqual(line_item.price_currency, Decimal('25.00'))
        self.assertNotEqual(line_item.price_currency, Decimal('50.00'))

    def test_add_line_item_missing_qty(self):
        """Test that qty is required when adding a line item."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '',  # Missing qty
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order)
        self.assertEqual(line_items.count(), 0)

    def test_add_line_item_missing_price_list_item(self):
        """Test that price_list_item is required when adding a line item."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        form_data = {
            'qty': '5.00',
            # Missing price_list_item
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order)
        self.assertEqual(line_items.count(), 0)

    def test_multiple_line_items_can_be_added(self):
        """Test that multiple line items can be added to a PO."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        # Add first line item
        form_data_1 = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '10.00',
        }
        self.client.post(url, data=form_data_1)

        # Add second line item
        form_data_2 = {
            'price_list_item': str(self.price_list_item2.price_list_item_id),
            'qty': '5.00',
        }
        self.client.post(url, data=form_data_2)

        # Check both line items were created
        line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order).order_by('line_item_id')
        self.assertEqual(line_items.count(), 2)

        # Verify first item
        self.assertEqual(line_items[0].price_list_item, self.price_list_item)
        self.assertEqual(line_items[0].qty, Decimal('10.00'))
        self.assertEqual(line_items[0].price_currency, Decimal('25.00'))

        # Verify second item
        self.assertEqual(line_items[1].price_list_item, self.price_list_item2)
        self.assertEqual(line_items[1].qty, Decimal('5.00'))
        self.assertEqual(line_items[1].price_currency, Decimal('15.50'))

    def test_line_item_total_amount_calculation(self):
        """Test that line item total amount is calculated correctly."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        # Add line item with qty and purchase_price
        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '3.00',  # 3.00 * 25.00 = 75.00
        }

        self.client.post(url, data=form_data)

        # Check total_amount property
        line_item = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order).first()
        expected_total = Decimal('3.00') * Decimal('25.00')
        self.assertEqual(line_item.total_amount, expected_total)

    def test_line_item_auto_numbering(self):
        """Test that line items are automatically numbered sequentially."""
        url = reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id])

        # Add three line items
        for i in range(3):
            form_data = {
                'price_list_item': str(self.price_list_item.price_list_item_id),
                'qty': f'{i+1}.00',
            }
            self.client.post(url, data=form_data)

        # Check line numbers are sequential
        line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.purchase_order).order_by('line_number')
        self.assertEqual(line_items.count(), 3)

        for i, item in enumerate(line_items, start=1):
            self.assertEqual(item.line_number, i)

    def test_purchase_order_detail_shows_add_line_item_link(self):
        """Test that PO detail page has a link to add line items."""
        url = reverse('purchasing:purchase_order_detail', args=[self.purchase_order.po_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item')
        self.assertContains(response, reverse('purchasing:purchase_order_add_line_item', args=[self.purchase_order.po_id]))

    def test_purchase_order_detail_shows_business(self):
        """Test that PO detail page displays the business."""
        url = reverse('purchasing:purchase_order_detail', args=[self.purchase_order.po_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Business')
        self.assertContains(response, self.business.business_name)

    def test_purchase_order_detail_calculates_total(self):
        """Test that PO detail page calculates total correctly."""
        # Add two line items
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            price_list_item=self.price_list_item,
            description='Item 1',
            qty=Decimal('2.00'),
            units='each',
            price_currency=Decimal('10.00')
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            price_list_item=self.price_list_item2,
            description='Item 2',
            qty=Decimal('3.00'),
            units='each',
            price_currency=Decimal('15.00')
        )

        url = reverse('purchasing:purchase_order_detail', args=[self.purchase_order.po_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Total should be (2 * 10) + (3 * 15) = 20 + 45 = 65
        expected_total = Decimal('65.00')
        self.assertContains(response, f'${expected_total:.2f}')


class PurchaseOrderModelWithBusinessTests(TestCase):
    """Test PurchaseOrder model with Business field."""

    def setUp(self):
        """Set up test data."""
        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a test business
        self.business = Business.objects.create(
            business_name='Test Vendor',
            our_reference_code='VENDOR001',
            default_contact=self.default_contact
        )

    def test_purchase_order_creation_with_business(self):
        """Test creating a PO with a business."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO001'
        )
        self.assertEqual(po.business, self.business)
        self.assertEqual(po.po_number, 'PO001')

    def test_purchase_order_str_method(self):
        """Test PO string representation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO003'
        )
        self.assertEqual(str(po), 'PO PO003')
