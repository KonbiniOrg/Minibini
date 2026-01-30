from django.test import TestCase
from django.core.exceptions import ValidationError
from decimal import Decimal
from apps.invoicing.models import Invoice, InvoiceLineItem, PriceListItem
from apps.jobs.models import Job, Estimate, Task, WorkOrder
from apps.purchasing.models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration



class PriceListItemModelTest(TestCase):
    def setUp(self):
        pass
        
    def test_price_list_item_creation(self):
        item = PriceListItem.objects.create(
            code="ITEM001",
            units="each",
            description="Test item description",
            purchase_price=Decimal('10.50'),
            selling_price=Decimal('15.75'),
            qty_on_hand=Decimal('100.00'),
            qty_sold=Decimal('25.00'),
            qty_wasted=Decimal('2.00')
        )
        self.assertEqual(item.code, "ITEM001")
        self.assertEqual(item.units, "each")
        self.assertEqual(item.description, "Test item description")
        self.assertEqual(item.purchase_price, Decimal('10.50'))
        self.assertEqual(item.selling_price, Decimal('15.75'))
        self.assertEqual(item.qty_on_hand, Decimal('100.00'))
        self.assertEqual(item.qty_sold, Decimal('25.00'))
        self.assertEqual(item.qty_wasted, Decimal('2.00'))
        
    def test_price_list_item_str_method(self):
        item = PriceListItem.objects.create(
            code="TEST123",
            description="This is a very long description that should be truncated in the string representation"
        )
        self.assertEqual(str(item), "TEST123 - This is a very long description that should be tru")
        
    def test_price_list_item_defaults(self):
        item = PriceListItem.objects.create(
            code="DEFAULT001"
        )
        self.assertEqual(item.purchase_price, Decimal('0.00'))
        self.assertEqual(item.selling_price, Decimal('0.00'))
        self.assertEqual(item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(item.qty_sold, Decimal('0.00'))
        self.assertEqual(item.qty_wasted, Decimal('0.00'))


class InvoiceModelTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        
    def test_invoice_creation(self):
        invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV001",
            status='open'  # Use valid status from INVOICE_STATUS_CHOICES
        )
        self.assertEqual(invoice.job, self.job)
        self.assertEqual(invoice.invoice_number, "INV001")
        self.assertEqual(invoice.status, 'open')
        
    def test_invoice_str_method(self):
        invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV002"
        )
        self.assertEqual(str(invoice), "Invoice INV002")
        
    def test_invoice_default_status(self):
        """Test that Invoice default status is 'draft' (a valid choice)."""
        invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV003"
        )
        # Default status must be 'draft' - a valid choice in INVOICE_STATUS_CHOICES
        self.assertEqual(invoice.status, 'draft')

    def test_invoice_default_status_is_valid_choice(self):
        """Test that the default status is in the valid choices list."""
        invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV_VALID_DEFAULT"
        )
        valid_statuses = [choice[0] for choice in Invoice.INVOICE_STATUS_CHOICES]
        self.assertIn(invoice.status, valid_statuses,
            f"Default status '{invoice.status}' is not in valid choices: {valid_statuses}")
        
    def test_invoice_status_choices(self):
        invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV004",
            status='cancelled'
        )
        self.assertEqual(invoice.status, 'cancelled')


class InvoiceLineItemModelTest(TestCase):
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(
            first_name='Test Customer',
            last_name='',
            email='test.customer@test.com',
            business=self.business
        )
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        self.invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV001"
        )
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST001"
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            job=self.job,
            po_number="PO001",
            status='issued'
        )
        self.bill = Bill.objects.create(
            purchase_order=self.purchase_order,
            contact=self.contact,
            vendor_invoice_number="VIN001"
        )
        self.price_list_item = PriceListItem.objects.create(
            code="ITEM001"
        )
        
    def test_invoice_line_item_creation(self):
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            task=self.task,
            price_list_item=None,
            line_number=1,
            qty=Decimal('5.00'),
            units="hours",
            description="Test line item",
            price_currency=Decimal('50.00')
        )
        self.assertEqual(line_item.invoice, self.invoice)
        self.assertEqual(line_item.task, self.task)
        self.assertIsNone(line_item.price_list_item)
        self.assertEqual(line_item.line_number, 1)
        self.assertEqual(line_item.qty, Decimal('5.00'))
        self.assertEqual(line_item.units, "hours")
        self.assertEqual(line_item.description, "Test line item")
        self.assertEqual(line_item.price_currency, Decimal('50.00'))
        
    def test_invoice_line_item_str_method(self):
        line_item = InvoiceLineItem.objects.create(invoice=self.invoice, task=self.task)
        self.assertEqual(str(line_item), f"Invoice Line Item {line_item.line_item_id} for {self.invoice.invoice_number}")
        
    def test_invoice_line_item_defaults(self):
        line_item = InvoiceLineItem.objects.create(invoice=self.invoice, task=self.task)
        self.assertEqual(line_item.qty, Decimal('0.00'))
        self.assertEqual(line_item.price_currency, Decimal('0.00'))
        
    def test_invoice_line_item_optional_relationships(self):
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            price_list_item=self.price_list_item,
            qty=Decimal('1.00'),
            description="Simple line item"
        )
        self.assertEqual(line_item.invoice, self.invoice)
        self.assertIsNone(line_item.task)
        self.assertEqual(line_item.price_list_item, self.price_list_item)
        
    def test_invoice_line_item_validation_both_task_and_price_item(self):
        """Test that validation prevents having both task and price_list_item"""
        line_item = InvoiceLineItem(
            invoice=self.invoice,
            task=self.task,
            price_list_item=self.price_list_item,
            description="Invalid line item with both"
        )
        with self.assertRaises(ValidationError) as context:
            line_item.full_clean()
        self.assertIn("cannot have both task and price_list_item", str(context.exception))
        
    def test_invoice_line_item_validation_both_null_allowed(self):
        """Test that validation allows both task and price_list_item to be null"""
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            task=None,
            price_list_item=None,
            description="Line item with neither task nor price item"
        )
        # Should not raise any validation errors
        line_item.full_clean()
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)
        
    def test_invoice_line_item_validation_task_only(self):
        """Test that line item with only task is valid"""
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            task=self.task,
            price_list_item=None,
            description="Task-only line item"
        )
        line_item.full_clean()  # Should not raise
        self.assertEqual(line_item.task, self.task)
        self.assertIsNone(line_item.price_list_item)
        
    def test_invoice_line_item_validation_price_item_only(self):
        """Test that line item with only price_list_item is valid"""
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            task=None,
            price_list_item=self.price_list_item,
            description="Price item only line item"
        )
        line_item.full_clean()  # Should not raise
        self.assertIsNone(line_item.task)
        self.assertEqual(line_item.price_list_item, self.price_list_item)