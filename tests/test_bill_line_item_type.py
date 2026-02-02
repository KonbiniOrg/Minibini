"""Tests for LineItemType in Bill line items."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType, Configuration
from apps.contacts.models import Contact, Business
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem
from apps.invoicing.models import PriceListItem


class BillLineItemTypeFormTest(TestCase):
    """Tests for LineItemType in Bill line item forms."""

    @classmethod
    def setUpTestData(cls):
        cls.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com'
        )
        cls.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=cls.default_contact
        )
        cls.bill = Bill.objects.create(
            business=cls.business,
            bill_number='BILL-001',
            vendor_invoice_number='INV-001',
            status='draft'
        )
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()

    def test_form_includes_line_item_type_field(self):
        """Test that line item form shows LineItemType field."""
        response = self.client.get(
            reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id])
        )
        self.assertContains(response, 'line_item_type')

    def test_manual_entry_creates_line_item_with_type(self):
        """Test that manual form creates line item with LineItemType."""
        response = self.client.post(
            reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id]),
            {
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price': '50.00',
                'line_item_type': self.service_type.pk,
            }
        )
        line_item = BillLineItem.objects.filter(bill=self.bill).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.service_type)

    def test_manual_entry_requires_line_item_type(self):
        """Test that manual entry requires LineItemType."""
        response = self.client.post(
            reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id]),
            {
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price': '50.00',
                # No line_item_type
            }
        )
        # Should stay on page with error
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BillLineItem.objects.filter(bill=self.bill).count(), 0)


class BillLineItemFromPriceListTest(TestCase):
    """Tests for LineItemType when adding from PriceList."""

    @classmethod
    def setUpTestData(cls):
        cls.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default2@test.com'
        )
        cls.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=cls.default_contact
        )
        cls.bill = Bill.objects.create(
            business=cls.business,
            bill_number='BILL-002',
            vendor_invoice_number='INV-002',
            status='draft'
        )
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.price_list_item = PriceListItem.objects.create(
            code='ITEM-001',
            description='Test Product',
            selling_price=Decimal('100.00'),
            purchase_price=Decimal('75.00'),
            line_item_type=cls.product_type
        )

    def setUp(self):
        self.client = Client()

    def test_pricelist_form_copies_line_item_type(self):
        """Test that adding from price list copies the LineItemType."""
        response = self.client.post(
            reverse('purchasing:bill_add_line_item', args=[self.bill.bill_id]),
            {
                'price_list_item': self.price_list_item.pk,
                'qty': '1.00',
            }
        )
        line_item = BillLineItem.objects.filter(bill=self.bill).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.product_type)


class BillCreateFromPOLineItemTypeTest(TestCase):
    """Tests for LineItemType when creating Bill from PO."""

    @classmethod
    def setUpTestData(cls):
        # Create the bill number sequence configuration
        Configuration.objects.get_or_create(
            key='bill_number_sequence',
            defaults={'value': 'BILL-{counter:04d}'}
        )
        Configuration.objects.get_or_create(
            key='bill_counter',
            defaults={'value': '0'}
        )
        cls.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default3@test.com'
        )
        cls.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=cls.default_contact
        )
        # Create a PO in issued status (required for bill creation)
        cls.po = PurchaseOrder.objects.create(
            business=cls.business,
            po_number='PO-003',
            status='draft'
        )
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        # Add line items to the PO
        cls.po_line_item = PurchaseOrderLineItem.objects.create(
            purchase_order=cls.po,
            description='Test Product',
            qty=Decimal('2.00'),
            units='ea',
            price_currency=Decimal('50.00'),
            line_item_type=cls.product_type
        )
        # Issue the PO so we can create a bill from it
        cls.po.status = 'issued'
        cls.po.save()

    def setUp(self):
        self.client = Client()

    def test_bill_from_po_copies_line_item_type(self):
        """Test that creating a Bill from PO copies LineItemType to line items."""
        response = self.client.post(
            reverse('purchasing:bill_create_for_po', args=[self.po.po_id]),
            {
                'purchase_order': self.po.po_id,
                'business': self.business.pk,
                'vendor_invoice_number': 'VENDOR-INV-001',
            }
        )
        # Find the created bill
        bill = Bill.objects.filter(vendor_invoice_number='VENDOR-INV-001').first()
        self.assertIsNotNone(bill)

        # Check the line item was copied with line_item_type
        bill_line_item = BillLineItem.objects.filter(bill=bill).first()
        self.assertIsNotNone(bill_line_item)
        self.assertEqual(bill_line_item.line_item_type, self.product_type)
