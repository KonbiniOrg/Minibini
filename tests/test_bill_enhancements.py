from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import Bill, BillLineItem
from apps.contacts.models import Contact, Business
from decimal import Decimal


class BillStrTest(TestCase):
    """Test Bill's __str__ representation."""

    def test_bill_str_uses_vendor_invoice_number(self):
        contact = Contact.objects.create(first_name='V', last_name='I')
        business = Business.objects.create(business_name='Vendor', default_contact=contact)
        contact.business = business
        contact.save()
        bill = Bill.objects.create(
            business=business, contact=contact,
            vendor_invoice_number='VIN-XYZ',
        )
        self.assertEqual(str(bill), 'Bill VIN-XYZ')


class BillLineItemManualEntryTest(TestCase):
    """Test that Bill line items can be created without price list items."""

    def setUp(self):
        """Set up test data."""
        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create business, contact and bill
        self.business = Business.objects.create(business_name="Test Vendor Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Vendor', last_name='', email='test.vendor@test.com', business=self.business)
        self.bill = Bill.objects.create(
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='VIN001',
        )

    def test_create_line_item_with_manual_entry(self):
        """Test creating a bill line item with manual entry (no price list item)."""
        line_item = BillLineItem.objects.create(
            bill=self.bill,
            description="Custom service",
            qty=Decimal('5.00'),
            units="hours",
            price=Decimal('100.00')
        )

        # Verify line item was created
        self.assertIsNotNone(line_item.line_item_id)
        self.assertEqual(line_item.description, "Custom service")
        self.assertEqual(line_item.qty, Decimal('5.00'))
        self.assertEqual(line_item.units, "hours")
        self.assertEqual(line_item.price, Decimal('100.00'))
        self.assertIsNone(line_item.inventory_item)
        self.assertIsNone(line_item.task)

    def test_manual_line_item_total_amount(self):
        """Test that manual line items calculate total_amount correctly."""
        line_item = BillLineItem.objects.create(
            bill=self.bill,
            description="Custom parts",
            qty=Decimal('10.00'),
            units="ea",
            price=Decimal('25.50')
        )

        # Verify total_amount calculation
        self.assertEqual(line_item.total_amount, Decimal('255.00'))

    def test_multiple_manual_line_items_on_same_bill(self):
        """Test that multiple manual line items can be added to the same bill."""
        line_item1 = BillLineItem.objects.create(
            bill=self.bill,
            description="Item 1",
            qty=Decimal('2.00'),
            price=Decimal('50.00')
        )

        line_item2 = BillLineItem.objects.create(
            bill=self.bill,
            description="Item 2",
            qty=Decimal('3.00'),
            price=Decimal('30.00')
        )

        # Verify both were created
        line_items = BillLineItem.objects.filter(bill=self.bill)
        self.assertEqual(line_items.count(), 2)


class BillDraftStateValidationTest(TestCase):
    """Test that Bills cannot leave Draft state without line items."""

    def setUp(self):
        """Set up test data."""
        # Create default contact for business
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')

        # Create business, contact and bill
        self.business = Business.objects.create(business_name="Test Vendor Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Vendor', last_name='', email='test.vendor@test.com', business=self.business)
        self.bill = Bill.objects.create(
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='VIN001',
        )

    def test_cannot_transition_from_draft_without_line_items(self):
        """Test that Bill cannot transition from draft to received without line items."""
        # Verify bill is in draft status
        self.assertEqual(self.bill.status, Bill.STATUS_DRAFT)

        # Try to transition to received without line items
        self.bill.status = Bill.STATUS_RECEIVED

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
            price=Decimal('100.00')
        )

        # Verify line item was added
        self.assertEqual(BillLineItem.objects.filter(bill=self.bill).count(), 1)

        # Now transition to received should work
        self.bill.status = Bill.STATUS_RECEIVED
        self.bill.save()

        # Verify status changed
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_RECEIVED)

    def test_can_stay_in_draft_without_line_items(self):
        """Test that Bill can remain in draft status without line items."""
        # Verify bill is in draft status
        self.assertEqual(self.bill.status, Bill.STATUS_DRAFT)

        # Update other fields while staying in draft
        self.bill.vendor_invoice_number = 'VIN001-UPDATED'
        self.bill.save()

        # Should succeed
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.vendor_invoice_number, 'VIN001-UPDATED')
        self.assertEqual(self.bill.status, Bill.STATUS_DRAFT)

    def test_transitions_after_draft_not_affected_by_line_item_count(self):
        """Test that transitions after draft don't check line item count."""
        # Add a line item
        BillLineItem.objects.create(
            bill=self.bill,
            description="Test item",
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )

        # Transition to received
        self.bill.status = Bill.STATUS_RECEIVED
        self.bill.save()

        # Now delete the line item
        BillLineItem.objects.filter(bill=self.bill).delete()

        # Transition to partly_paid should still work (no line item check after draft)
        self.bill.status = Bill.STATUS_PARTLY_PAID
        self.bill.save()

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.STATUS_PARTLY_PAID)

    def test_validation_message_is_clear(self):
        """Test that validation error message is clear and helpful."""
        self.bill.status = Bill.STATUS_RECEIVED

        with self.assertRaises(ValidationError) as context:
            self.bill.save()

        error_message = str(context.exception)
        self.assertIn('Cannot change Bill status from Draft', error_message)
        self.assertIn('without at least one line item', error_message)
        self.assertIn('Please add at least one line item', error_message)
