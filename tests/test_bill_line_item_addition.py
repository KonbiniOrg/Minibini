"""Tests for adding line items to Bills from Price List"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.purchasing.models import Bill, BillLineItem, PurchaseOrder
from apps.contacts.models import Contact, Business
from apps.invoicing.models import PriceListItem


class BillLineItemAdditionTests(TestCase):
    """Test adding line items to Bills from Price List."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create a test contact (must be created before business for default_contact)
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create a test business
        self.business = Business.objects.create(
            business_name='Test Vendor Business',
            default_contact=self.default_contact
        )

        # Create a test contact
        self.contact = Contact.objects.create(
            first_name='Test Vendor',
            last_name='',
            email='test.vendor@test.com',
            business=self.business
        )

        # Create a purchase order in issued status (Bills require PO to be issued or later)
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.purchase_order.status = 'issued'
        self.purchase_order.save()

        # Create a bill
        self.bill = Bill.objects.create(
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            bill_number='BILL-TEST',
            vendor_invoice_number='INV-TEST-001'
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
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item to Bill')
        self.assertContains(response, 'INV-TEST-001')
        self.assertContains(response, 'Price List Item')
        self.assertContains(response, 'Quantity')

    def test_add_line_item_from_price_list(self):
        """Test adding a line item from price list."""
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '10.00',
        }

        response = self.client.post(url, data=form_data)

        # Should redirect to bill detail page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('purchasing:bill_detail', args=[self.bill.bill_id]))

        # Check line item was created
        line_item = BillLineItem.objects.filter(bill=self.bill).first()
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
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '5.00',
        }

        response = self.client.post(url, data=form_data)

        # Check line item uses purchase_price (25.00), not selling_price (50.00)
        line_item = BillLineItem.objects.filter(bill=self.bill).first()
        self.assertEqual(line_item.price_currency, Decimal('25.00'))
        self.assertNotEqual(line_item.price_currency, Decimal('50.00'))

    def test_add_line_item_missing_qty(self):
        """Test that qty is required when adding a line item."""
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '',  # Missing qty
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = BillLineItem.objects.filter(bill=self.bill)
        self.assertEqual(line_items.count(), 0)

    def test_add_line_item_missing_price_list_item(self):
        """Test that price_list_item is required when adding a line item."""
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        form_data = {
            'qty': '5.00',
            # Missing price_list_item
        }

        response = self.client.post(url, data=form_data)

        # Should NOT redirect (form errors)
        self.assertEqual(response.status_code, 200)

        # No line item should be created
        line_items = BillLineItem.objects.filter(bill=self.bill)
        self.assertEqual(line_items.count(), 0)

    def test_multiple_line_items_can_be_added(self):
        """Test that multiple line items can be added to a Bill."""
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

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
        line_items = BillLineItem.objects.filter(bill=self.bill).order_by('line_item_id')
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
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        # Add line item with qty and purchase_price
        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '3.00',  # 3.00 * 25.00 = 75.00
        }

        self.client.post(url, data=form_data)

        # Check total_amount property
        line_item = BillLineItem.objects.filter(bill=self.bill).first()
        expected_total = Decimal('3.00') * Decimal('25.00')
        self.assertEqual(line_item.total_amount, expected_total)

    def test_line_item_auto_numbering(self):
        """Test that line items are automatically numbered sequentially."""
        url = reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])

        # Add three line items
        for i in range(3):
            form_data = {
                'price_list_item': str(self.price_list_item.price_list_item_id),
                'qty': f'{i+1}.00',
            }
            self.client.post(url, data=form_data)

        # Check line numbers are sequential
        line_items = BillLineItem.objects.filter(bill=self.bill).order_by('line_number')
        self.assertEqual(line_items.count(), 3)

        for i, item in enumerate(line_items, start=1):
            self.assertEqual(item.line_number, i)

    def test_bill_detail_shows_add_line_item_link(self):
        """Test that Bill detail page has a link to add line items."""
        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add Line Item')
        self.assertContains(response, reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id]))

    def test_bill_detail_calculates_total(self):
        """Test that Bill detail page calculates total correctly."""
        # Add two line items
        BillLineItem.objects.create(
            bill=self.bill,
            price_list_item=self.price_list_item,
            description='Item 1',
            qty=Decimal('2.00'),
            units='each',
            price_currency=Decimal('10.00')
        )
        BillLineItem.objects.create(
            bill=self.bill,
            price_list_item=self.price_list_item2,
            description='Item 2',
            qty=Decimal('3.00'),
            units='each',
            price_currency=Decimal('15.00')
        )

        url = reverse('purchasing:bill_detail', args=[self.bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Total should be (2 * 10) + (3 * 15) = 20 + 45 = 65
        expected_total = Decimal('65.00')
        self.assertContains(response, f'${expected_total:.2f}')

    def test_add_line_item_to_bill_without_po(self):
        """Test that line items can be added to bills without a PO."""
        # Create a bill without a PO
        bill_no_po = Bill.objects.create(
            purchase_order=None,
            business=self.business,
            contact=self.contact,
            bill_number='BILL-TEST2',
            vendor_invoice_number='INV-NO-PO-001'
        )

        url = reverse('purchasing:bill_add_line_item', args=[bill_no_po.bill_id])

        form_data = {
            'price_list_item': str(self.price_list_item.price_list_item_id),
            'qty': '7.00',
        }

        response = self.client.post(url, data=form_data)

        # Should succeed
        self.assertEqual(response.status_code, 302)

        # Check line item was created
        line_item = BillLineItem.objects.filter(bill=bill_no_po).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.qty, Decimal('7.00'))
