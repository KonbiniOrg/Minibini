from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import PurchaseOrder, Bill, BillLineItem, PurchaseOrderLineItem
from apps.invoicing.models import PriceListItem
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class PurchaseOrderContactBusinessTest(TestCase):
    """Test Contact and Business associations for PurchaseOrder"""

    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Vendor", default_contact=self.default_contact)
        self.business2 = Business.objects.create(business_name="Another Vendor", default_contact=self.default_contact)
        self.contact_with_business = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test.contact@test.com',
            business=self.business
        )
        self.contact_without_business = Contact.objects.create(first_name='Contact No Business', last_name='', email='contact.no.business@test.com')

    def test_po_creation_with_business_only(self):
        """PO can be created with just a Business"""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO001"
        )
        self.assertEqual(po.business, self.business)
        self.assertIsNone(po.contact)

    def test_po_creation_with_contact_and_business(self):
        """PO can be created with both Contact and Business"""
        po = PurchaseOrder.objects.create(
            business=self.business,
            contact=self.contact_with_business,
            po_number="PO002"
        )
        self.assertEqual(po.business, self.business)
        self.assertEqual(po.contact, self.contact_with_business)

    def test_po_contact_auto_assigns_business(self):
        """When Contact is provided without Business, Business is auto-assigned from Contact"""
        po = PurchaseOrder(
            contact=self.contact_with_business,
            po_number="PO003"
        )
        po.save()

        # Business should be auto-assigned from contact
        self.assertEqual(po.business, self.business)
        self.assertEqual(po.contact, self.contact_with_business)

    def test_po_contact_business_mismatch_fails(self):
        """PO creation fails if Contact's Business doesn't match explicitly set Business"""
        po = PurchaseOrder(
            business=self.business2,  # Different from contact's business
            contact=self.contact_with_business,
            po_number="PO003a"
        )

        with self.assertRaises(ValidationError) as cm:
            po.save()

        self.assertIn('The Business must match', str(cm.exception))

    def test_po_contact_without_business_fails(self):
        """PO creation fails if Contact doesn't have a Business"""
        po = PurchaseOrder(
            business=self.business,
            contact=self.contact_without_business,
            po_number="PO004"
        )

        with self.assertRaises(ValidationError) as cm:
            po.save()

        self.assertIn('does not have a Business associated', str(cm.exception))

    def test_po_business_is_required(self):
        """PO cannot be created without a Business"""
        with self.assertRaises(Exception):
            PurchaseOrder.objects.create(po_number="PO005")


class BillContactBusinessTest(TestCase):
    """Test Contact and Business associations for Bill"""

    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Vendor", default_contact=self.default_contact)
        self.business2 = Business.objects.create(business_name="Another Vendor", default_contact=self.default_contact)
        self.contact_with_business = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test.contact@test.com',
            business=self.business
        )
        self.contact_without_business = Contact.objects.create(first_name='Contact No Business', last_name='', email='contact.no.business@test.com')

    def test_bill_creation_with_business_only(self):
        """Bill can be created with just a Business"""
        bill = Bill.objects.create(
            business=self.business,
            bill_number="BILL001",
            vendor_invoice_number="VIN001"
        )
        self.assertEqual(bill.business, self.business)
        self.assertIsNone(bill.contact)

    def test_bill_creation_with_contact_and_business(self):
        """Bill can be created with both Contact and Business"""
        bill = Bill.objects.create(
            business=self.business,
            contact=self.contact_with_business,
            bill_number="BILL002",
            vendor_invoice_number="VIN002"
        )
        self.assertEqual(bill.business, self.business)
        self.assertEqual(bill.contact, self.contact_with_business)

    def test_bill_contact_auto_assigns_business(self):
        """When Contact is provided without Business, Business is auto-assigned from Contact"""
        bill = Bill(
            contact=self.contact_with_business,
            bill_number="BILL003",
            vendor_invoice_number="VIN003"
        )
        bill.save()

        # Business should be auto-assigned from contact
        self.assertEqual(bill.business, self.business)
        self.assertEqual(bill.contact, self.contact_with_business)

    def test_bill_contact_business_mismatch_fails(self):
        """Bill creation fails if Contact's Business doesn't match explicitly set Business"""
        bill = Bill(
            business=self.business2,  # Different from contact's business
            contact=self.contact_with_business,
            bill_number="BILL003a",
            vendor_invoice_number="VIN003a"
        )

        with self.assertRaises(ValidationError) as cm:
            bill.save()

        self.assertIn('The Business must match', str(cm.exception))

    def test_bill_contact_without_business_fails(self):
        """Bill creation fails if Contact doesn't have a Business"""
        bill = Bill(
            business=self.business,
            contact=self.contact_without_business,
            bill_number="BILL004",
            vendor_invoice_number="VIN004"
        )

        with self.assertRaises(ValidationError) as cm:
            bill.save()

        self.assertIn('does not have a Business associated', str(cm.exception))

    def test_bill_business_is_required(self):
        """Bill cannot be created without a Business"""
        with self.assertRaises(Exception):
            Bill.objects.create(
                bill_number="BILL005",
                vendor_invoice_number="VIN005"
            )


class BillFromPurchaseOrderTest(TestCase):
    """Test Bill creation from PurchaseOrder with Contact/Business copying and line items"""

    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Vendor", default_contact=self.default_contact)
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test.contact@test.com',
            business=self.business
        )
        self.customer_contact = Contact.objects.create(
            first_name='Test Customer',
            last_name='',
            email='test.customer@test.com',
            business=self.business
        )
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.customer_contact,
            description="Test job"
        )

        # Create PO with contact and business
        self.po = PurchaseOrder.objects.create(
            business=self.business,
            contact=self.contact,
            po_number="PO001",
            status='draft'
        )

        # Transition PO to issued status
        self.po.status = 'issued'
        self.po.save()

        # Create price list items for line items
        self.price_list_item1 = PriceListItem.objects.create(
            description="Test Item 1",
            units="ea",
            purchase_price=10.00,
            selling_price=15.00
        )
        self.price_list_item2 = PriceListItem.objects.create(
            description="Test Item 2",
            units="kg",
            purchase_price=20.00,
            selling_price=30.00
        )

        # Add line items to PO
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.price_list_item1,
            description="Test Item 1",
            qty=5,
            units="ea",
            price_currency=10.00,
            line_number=1
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.price_list_item2,
            description="Test Item 2",
            qty=3,
            units="kg",
            price_currency=20.00,
            line_number=2
        )

    def test_bill_copies_contact_and_business_from_po(self):
        """When creating Bill from PO, Contact and Business are copied"""
        bill = Bill.objects.create(
            purchase_order=self.po,
            business=self.po.business,
            contact=self.po.contact,
            bill_number="BILL001",
            vendor_invoice_number="VIN001"
        )

        self.assertEqual(bill.business, self.po.business)
        self.assertEqual(bill.contact, self.po.contact)

    def test_bill_from_po_without_contact(self):
        """Bill can be created from PO even if PO has no Contact"""
        po_no_contact = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO002",
            status='issued'
        )

        bill = Bill.objects.create(
            purchase_order=po_no_contact,
            business=po_no_contact.business,
            bill_number="BILL002",
            vendor_invoice_number="VIN002"
        )

        self.assertEqual(bill.business, po_no_contact.business)
        self.assertIsNone(bill.contact)

    def test_line_items_copied_from_po_to_bill(self):
        """Line items from PO are copied to Bill"""
        bill = Bill.objects.create(
            purchase_order=self.po,
            business=self.po.business,
            contact=self.po.contact,
            bill_number="BILL003",
            vendor_invoice_number="VIN003"
        )

        # Copy line items from PO
        po_line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.po).order_by('line_number')
        for po_line_item in po_line_items:
            BillLineItem.objects.create(
                bill=bill,
                price_list_item=po_line_item.price_list_item,
                description=po_line_item.description,
                qty=po_line_item.qty,
                units=po_line_item.units,
                price_currency=po_line_item.price_currency,
                line_number=po_line_item.line_number
            )

        # Verify line items were copied
        bill_line_items = BillLineItem.objects.filter(bill=bill).order_by('line_number')
        self.assertEqual(bill_line_items.count(), 2)

        # Verify first line item
        self.assertEqual(bill_line_items[0].description, "Test Item 1")
        self.assertEqual(bill_line_items[0].qty, 5)
        self.assertEqual(bill_line_items[0].price_currency, 10.00)

        # Verify second line item
        self.assertEqual(bill_line_items[1].description, "Test Item 2")
        self.assertEqual(bill_line_items[1].qty, 3)
        self.assertEqual(bill_line_items[1].price_currency, 20.00)

    def test_bill_line_items_can_be_modified_after_creation(self):
        """Bill line items can be modified after creation from PO"""
        bill = Bill.objects.create(
            purchase_order=self.po,
            business=self.po.business,
            contact=self.po.contact,
            bill_number="BILL004",
            vendor_invoice_number="VIN004"
        )

        # Copy line items from PO
        po_line_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.po).order_by('line_number')
        for po_line_item in po_line_items:
            BillLineItem.objects.create(
                bill=bill,
                price_list_item=po_line_item.price_list_item,
                description=po_line_item.description,
                qty=po_line_item.qty,
                units=po_line_item.units,
                price_currency=po_line_item.price_currency,
                line_number=po_line_item.line_number
            )

        # Modify a line item
        bill_line_item = BillLineItem.objects.filter(bill=bill).first()
        bill_line_item.qty = 10
        bill_line_item.save()

        # Verify modification
        bill_line_item.refresh_from_db()
        self.assertEqual(bill_line_item.qty, 10)

        # Add a new line item
        BillLineItem.objects.create(
            bill=bill,
            description="New Item",
            qty=1,
            units="ea",
            price_currency=5.00,
            line_number=3
        )

        # Verify new line item was added
        self.assertEqual(BillLineItem.objects.filter(bill=bill).count(), 3)
