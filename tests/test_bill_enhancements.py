from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import Bill, BillLineItem, PurchaseOrder
from apps.purchasing.forms import BillForm, BillLineItemForm
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.core.services import NumberGenerationService
from decimal import Decimal


class BillNumberGenerationTest(TestCase):
    """Test that Bill numbers are auto-generated using NumberGenerationService."""

    def setUp(self):
        """Set up test data and configuration."""
        # Create configuration for bill numbering
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create business and contact for bills
        self.business = Business.objects.create(business_name="Test Vendor Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Vendor', last_name='', email='test.vendor@test.com', business=self.business)

    def test_bill_number_generated_on_form_save(self):
        """Test that bill number is automatically generated when using BillForm."""
        form = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })

        self.assertTrue(form.is_valid())
        bill = form.save()

        # Verify bill number was generated
        self.assertIsNotNone(bill.bill_number)
        self.assertTrue(bill.bill_number.startswith('BILL-'))
        self.assertIn('-0001', bill.bill_number)

    def test_bill_numbers_increment_sequentially(self):
        """Test that bill numbers increment sequentially."""
        # Create first bill
        form1 = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })
        bill1 = form1.save()

        # Create second bill
        form2 = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN002',
        })
        bill2 = form2.save()

        # Create third bill
        form3 = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN003',
        })
        bill3 = form3.save()

        # Verify sequential numbering
        self.assertIn('-0001', bill1.bill_number)
        self.assertIn('-0002', bill2.bill_number)
        self.assertIn('-0003', bill3.bill_number)

    def test_bill_number_is_unique(self):
        """Test that bill numbers are unique."""
        # Create bill
        form = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })
        bill1 = form.save()

        # Try to create another bill with same bill_number (should fail)
        with self.assertRaises(Exception):
            Bill.objects.create(
                bill_number=bill1.bill_number,
                business=self.business,
                contact=self.contact,
                vendor_invoice_number='VIN002'
            )

    def test_bill_str_method_uses_bill_number(self):
        """Test that Bill's __str__ method uses bill_number."""
        form = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })
        bill = form.save()

        self.assertEqual(str(bill), f"Bill {bill.bill_number}")


class BillLineItemManualEntryTest(TestCase):
    """Test that Bill line items can be created without price list items."""

    def setUp(self):
        """Set up test data."""
        # Create configuration for bill numbering
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create business, contact and bill
        self.business = Business.objects.create(business_name="Test Vendor Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Vendor', last_name='', email='test.vendor@test.com', business=self.business)
        form = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })
        self.bill = form.save()

    def test_create_line_item_with_manual_entry(self):
        """Test creating a bill line item with manual entry (no price list item)."""
        line_item = BillLineItem.objects.create(
            bill=self.bill,
            description="Custom service",
            qty=Decimal('5.00'),
            units="hours",
            price_currency=Decimal('100.00')
        )

        # Verify line item was created
        self.assertIsNotNone(line_item.line_item_id)
        self.assertEqual(line_item.description, "Custom service")
        self.assertEqual(line_item.qty, Decimal('5.00'))
        self.assertEqual(line_item.units, "hours")
        self.assertEqual(line_item.price_currency, Decimal('100.00'))
        self.assertIsNone(line_item.price_list_item)
        self.assertIsNone(line_item.task)

    def test_manual_line_item_total_amount(self):
        """Test that manual line items calculate total_amount correctly."""
        line_item = BillLineItem.objects.create(
            bill=self.bill,
            description="Custom parts",
            qty=Decimal('10.00'),
            units="ea",
            price_currency=Decimal('25.50')
        )

        # Verify total_amount calculation
        self.assertEqual(line_item.total_amount, Decimal('255.00'))

    def test_bill_line_item_form_allows_manual_entry(self):
        """Test that BillLineItemForm accepts manual entry without price_list_item."""
        form = BillLineItemForm(data={
            'description': 'Manual labor',
            'qty': '8.00',
            'units': 'hours',
            'price': '75.00'
        })

        self.assertTrue(form.is_valid())

    def test_bill_line_item_form_requires_description_for_manual_entry(self):
        """Test that BillLineItemForm requires description when no price_list_item."""
        form = BillLineItemForm(data={
            'qty': '5.00',
            'units': 'ea',
            'price': '10.00'
            # Missing description and price_list_item
        })

        self.assertFalse(form.is_valid())
        self.assertIn('Either select a Price List Item or provide a Description', str(form.errors))

    def test_multiple_manual_line_items_on_same_bill(self):
        """Test that multiple manual line items can be added to the same bill."""
        line_item1 = BillLineItem.objects.create(
            bill=self.bill,
            description="Item 1",
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00')
        )

        line_item2 = BillLineItem.objects.create(
            bill=self.bill,
            description="Item 2",
            qty=Decimal('3.00'),
            price_currency=Decimal('30.00')
        )

        # Verify both were created
        line_items = BillLineItem.objects.filter(bill=self.bill)
        self.assertEqual(line_items.count(), 2)


class BillDraftStateValidationTest(TestCase):
    """Test that Bills cannot leave Draft state without line items."""

    def setUp(self):
        """Set up test data."""
        # Create configuration for bill numbering
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create business, contact and bill
        self.business = Business.objects.create(business_name="Test Vendor Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Vendor', last_name='', email='test.vendor@test.com', business=self.business)
        form = BillForm(data={
            'business': self.business.business_id,
            'contact': self.contact.contact_id,
            'vendor_invoice_number': 'VIN001',
        })
        self.bill = form.save()

    def test_cannot_transition_from_draft_without_line_items(self):
        """Test that Bill cannot transition from draft to received without line items."""
        # Verify bill is in draft status
        self.assertEqual(self.bill.status, 'draft')

        # Try to transition to received without line items
        self.bill.status = 'received'

        with self.assertRaises(ValidationError) as context:
            self.bill.save()

        self.assertIn('without at least one line item', str(context.exception))

    def test_can_transition_from_draft_with_line_items(self):
        """Test that Bill can transition from draft to received with line items."""
        # Add a line item
        BillLineItem.objects.create(
            bill=self.bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )

        # Verify line item was added
        self.assertEqual(BillLineItem.objects.filter(bill=self.bill).count(), 1)

        # Now transition to received should work
        self.bill.status = 'received'
        self.bill.save()

        # Verify status changed
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'received')

    def test_can_stay_in_draft_without_line_items(self):
        """Test that Bill can remain in draft status without line items."""
        # Verify bill is in draft status
        self.assertEqual(self.bill.status, 'draft')

        # Update other fields while staying in draft
        self.bill.vendor_invoice_number = 'VIN001-UPDATED'
        self.bill.save()

        # Should succeed
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.vendor_invoice_number, 'VIN001-UPDATED')
        self.assertEqual(self.bill.status, 'draft')

    def test_transitions_after_draft_not_affected_by_line_item_count(self):
        """Test that transitions after draft don't check line item count."""
        # Add a line item
        BillLineItem.objects.create(
            bill=self.bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )

        # Transition to received
        self.bill.status = 'received'
        self.bill.save()

        # Now delete the line item
        BillLineItem.objects.filter(bill=self.bill).delete()

        # Transition to partly_paid should still work (no line item check after draft)
        self.bill.status = 'partly_paid'
        self.bill.save()

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, 'partly_paid')

    def test_validation_message_is_clear(self):
        """Test that validation error message is clear and helpful."""
        self.bill.status = 'received'

        with self.assertRaises(ValidationError) as context:
            self.bill.save()

        error_message = str(context.exception)
        self.assertIn('Cannot change Bill status from Draft', error_message)
        self.assertIn('without at least one line item', error_message)
        self.assertIn('Please add at least one line item', error_message)
