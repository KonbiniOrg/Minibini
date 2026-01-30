"""
Tests for the Bill status state machine.

Business Rules:
1. Bill starts in 'draft' status
2. Valid transitions:
   - draft -> received
   - received -> partly_paid
   - received -> paid_in_full
   - received -> cancelled
   - partly_paid -> paid_in_full
   - paid_in_full -> refunded
3. Terminal states: cancelled, refunded
4. Date fields are automatically set on state transitions and are immutable (except due_date)
5. due_date can be set by user and is editable
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.purchasing.models import Bill, PurchaseOrder, BillLineItem
from apps.contacts.models import Contact, Business
from datetime import timedelta
from decimal import Decimal


class BillStatusTransitionTest(TestCase):
    """Test the status state machine for Bill."""

    def setUp(self):
        """Set up test data."""
        # Create default contact for business
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

        # Create a test purchase order in issued status (Bills can only be created from issued or later POs)
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.purchase_order.status = 'issued'
        self.purchase_order.save()

    def _add_line_item_to_bill(self, bill):
        """Helper method to add a line item to a bill."""
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )

    def test_bill_default_status_is_draft(self):
        """Test that a new Bill starts in draft status."""
        bill = Bill.objects.create(
            bill_number="BILL-001",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001'
        )
        self.assertEqual(bill.status, 'draft')

    def test_bill_created_date_is_set_automatically(self):
        """Test that created_date is automatically set on creation."""
        before_creation = timezone.now()
        bill = Bill.objects.create(
            bill_number="BILL-002",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001'
        )
        after_creation = timezone.now()

        self.assertIsNotNone(bill.created_date)
        self.assertGreaterEqual(bill.created_date, before_creation)
        self.assertLessEqual(bill.created_date, after_creation)

    def test_transition_draft_to_received(self):
        """Test valid transition from draft to received."""
        bill = Bill.objects.create(
            bill_number="BILL-003",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'received')
        self.assertIsNotNone(bill.received_date)

    def test_received_date_set_automatically(self):
        """Test that received_date is automatically set when transitioning to received."""
        bill = Bill.objects.create(
            bill_number="BILL-004",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        self.assertIsNone(bill.received_date)

        before_transition = timezone.now()
        bill.status = 'received'
        bill.save()
        after_transition = timezone.now()

        bill.refresh_from_db()
        self.assertIsNotNone(bill.received_date)
        self.assertGreaterEqual(bill.received_date, before_transition)
        self.assertLessEqual(bill.received_date, after_transition)

    def test_transition_received_to_partly_paid(self):
        """Test valid transition from received to partly_paid."""
        bill = Bill.objects.create(
            bill_number="BILL-005",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        bill.status = 'partly_paid'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'partly_paid')

    def test_transition_received_to_paid_in_full(self):
        """Test valid transition from received to paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-006",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        bill.status = 'paid_in_full'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'paid_in_full')
        self.assertIsNotNone(bill.paid_date)

    def test_transition_received_to_cancelled(self):
        """Test valid transition from received to cancelled."""
        bill = Bill.objects.create(
            bill_number="BILL-007",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        bill.status = 'cancelled'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'cancelled')
        self.assertIsNotNone(bill.cancelled_date)

    def test_transition_partly_paid_to_paid_in_full(self):
        """Test valid transition from partly_paid to paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-008",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'partly_paid'
        bill.save()

        bill.status = 'paid_in_full'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'paid_in_full')
        self.assertIsNotNone(bill.paid_date)

    def test_transition_paid_in_full_to_refunded(self):
        """Test valid transition from paid_in_full to refunded."""
        bill = Bill.objects.create(
            bill_number="BILL-009",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()

        bill.status = 'refunded'
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.status, 'refunded')

    def test_paid_date_set_automatically(self):
        """Test that paid_date is automatically set when transitioning to paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-010",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        self.assertIsNone(bill.paid_date)

        before_transition = timezone.now()
        bill.status = 'paid_in_full'
        bill.save()
        after_transition = timezone.now()

        bill.refresh_from_db()
        self.assertIsNotNone(bill.paid_date)
        self.assertGreaterEqual(bill.paid_date, before_transition)
        self.assertLessEqual(bill.paid_date, after_transition)

    def test_cancelled_date_set_automatically(self):
        """Test that cancelled_date is automatically set when transitioning to cancelled."""
        bill = Bill.objects.create(
            bill_number="BILL-011",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        self.assertIsNone(bill.cancelled_date)

        before_transition = timezone.now()
        bill.status = 'cancelled'
        bill.save()
        after_transition = timezone.now()

        bill.refresh_from_db()
        self.assertIsNotNone(bill.cancelled_date)
        self.assertGreaterEqual(bill.cancelled_date, before_transition)
        self.assertLessEqual(bill.cancelled_date, after_transition)

    def test_invalid_transition_draft_to_partly_paid(self):
        """Test that draft cannot transition to partly_paid."""
        bill = Bill.objects.create(
            bill_number="BILL-012",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        bill.status = 'partly_paid'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_draft_to_paid_in_full(self):
        """Test that draft cannot transition to paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-013",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        bill.status = 'paid_in_full'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_draft_to_cancelled(self):
        """Test that draft cannot transition to cancelled."""
        bill = Bill.objects.create(
            bill_number="BILL-014",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        bill.status = 'cancelled'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_draft_to_refunded(self):
        """Test that draft cannot transition to refunded."""
        bill = Bill.objects.create(
            bill_number="BILL-015",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        bill.status = 'refunded'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_partly_paid_to_cancelled(self):
        """Test that partly_paid cannot transition to cancelled."""
        bill = Bill.objects.create(
            bill_number="BILL-016",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'partly_paid'
        bill.save()

        bill.status = 'cancelled'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_partly_paid_to_received(self):
        """Test that partly_paid cannot transition back to received."""
        bill = Bill.objects.create(
            bill_number="BILL-017",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'partly_paid'
        bill.save()

        bill.status = 'received'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_invalid_transition_paid_in_full_to_partly_paid(self):
        """Test that paid_in_full cannot transition to partly_paid."""
        bill = Bill.objects.create(
            bill_number="BILL-018",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()

        bill.status = 'partly_paid'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('cannot transition', str(context.exception).lower())

    def test_terminal_state_cancelled_cannot_transition(self):
        """Test that cancelled is a terminal state."""
        bill = Bill.objects.create(
            bill_number="BILL-019",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'cancelled'
        bill.save()

        # Try to transition to any other state
        bill.status = 'paid_in_full'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('terminal state', str(context.exception).lower())

    def test_terminal_state_refunded_cannot_transition(self):
        """Test that refunded is a terminal state."""
        bill = Bill.objects.create(
            bill_number="BILL-020",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()
        bill.status = 'refunded'
        bill.save()

        # Try to transition to any other state
        bill.status = 'paid_in_full'
        with self.assertRaises(ValidationError) as context:
            bill.save()

        self.assertIn('terminal state', str(context.exception).lower())

    def test_created_date_is_immutable(self):
        """Test that created_date cannot be changed after creation."""
        bill = Bill.objects.create(
            bill_number="BILL-021",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001'
        )
        original_created_date = bill.created_date

        # Try to change created_date
        new_date = timezone.now() + timedelta(days=1)
        bill.created_date = new_date
        bill.save()

        bill.refresh_from_db()
        # Should be reset to original value
        self.assertEqual(bill.created_date, original_created_date)

    def test_received_date_is_immutable(self):
        """Test that received_date cannot be changed after being set."""
        bill = Bill.objects.create(
            bill_number="BILL-022",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()

        original_received_date = bill.received_date

        # Try to change received_date
        new_date = timezone.now() + timedelta(days=1)
        bill.received_date = new_date
        bill.save()

        bill.refresh_from_db()
        # Should be reset to original value
        self.assertEqual(bill.received_date, original_received_date)

    def test_paid_date_is_immutable(self):
        """Test that paid_date cannot be changed after being set."""
        bill = Bill.objects.create(
            bill_number="BILL-023",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()

        original_paid_date = bill.paid_date

        # Try to change paid_date
        new_date = timezone.now() + timedelta(days=1)
        bill.paid_date = new_date
        bill.save()

        bill.refresh_from_db()
        # Should be reset to original value
        self.assertEqual(bill.paid_date, original_paid_date)

    def test_cancelled_date_is_immutable(self):
        """Test that cancelled_date cannot be changed after being set."""
        bill = Bill.objects.create(
            bill_number="BILL-024",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )
        self._add_line_item_to_bill(bill)

        bill.status = 'received'
        bill.save()
        bill.status = 'cancelled'
        bill.save()

        original_cancelled_date = bill.cancelled_date

        # Try to change cancelled_date
        new_date = timezone.now() + timedelta(days=1)
        bill.cancelled_date = new_date
        bill.save()

        bill.refresh_from_db()
        # Should be reset to original value
        self.assertEqual(bill.cancelled_date, original_cancelled_date)

    def test_due_date_is_optional_and_editable(self):
        """Test that due_date is optional and can be edited."""
        bill = Bill.objects.create(
            bill_number="BILL-025",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001'
        )

        # Should be None initially
        self.assertIsNone(bill.due_date)

        # Can be set
        due_date = timezone.now() + timedelta(days=30)
        bill.due_date = due_date
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.due_date, due_date)

        # Can be changed
        new_due_date = timezone.now() + timedelta(days=60)
        bill.due_date = new_due_date
        bill.save()

        bill.refresh_from_db()
        self.assertEqual(bill.due_date, new_due_date)

    def test_valid_path_draft_received_partly_paid_full(self):
        """Test the path: draft -> received -> partly_paid -> paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-026",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        self._add_line_item_to_bill(bill)


        bill.status = 'received'
        bill.save()
        self.assertEqual(bill.status, 'received')
        self.assertIsNotNone(bill.received_date)

        bill.status = 'partly_paid'
        bill.save()
        self.assertEqual(bill.status, 'partly_paid')

        bill.status = 'paid_in_full'
        bill.save()
        self.assertEqual(bill.status, 'paid_in_full')
        self.assertIsNotNone(bill.paid_date)

    def test_valid_path_draft_received_partly_paid_full_refunded(self):
        """Test the path: draft -> received -> partly_paid -> paid_in_full -> refunded."""
        bill = Bill.objects.create(
            bill_number="BILL-027",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        self._add_line_item_to_bill(bill)


        bill.status = 'received'
        bill.save()
        self.assertEqual(bill.status, 'received')

        bill.status = 'partly_paid'
        bill.save()
        self.assertEqual(bill.status, 'partly_paid')

        bill.status = 'paid_in_full'
        bill.save()
        self.assertEqual(bill.status, 'paid_in_full')

        bill.status = 'refunded'
        bill.save()
        self.assertEqual(bill.status, 'refunded')

    def test_valid_path_draft_received_full(self):
        """Test the path: draft -> received -> paid_in_full."""
        bill = Bill.objects.create(
            bill_number="BILL-028",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        self._add_line_item_to_bill(bill)


        bill.status = 'received'
        bill.save()
        self.assertEqual(bill.status, 'received')

        bill.status = 'paid_in_full'
        bill.save()
        self.assertEqual(bill.status, 'paid_in_full')

    def test_valid_path_draft_received_full_refunded(self):
        """Test the path: draft -> received -> paid_in_full -> refunded."""
        bill = Bill.objects.create(
            bill_number="BILL-029",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        self._add_line_item_to_bill(bill)


        bill.status = 'received'
        bill.save()
        self.assertEqual(bill.status, 'received')

        bill.status = 'paid_in_full'
        bill.save()
        self.assertEqual(bill.status, 'paid_in_full')

        bill.status = 'refunded'
        bill.save()
        self.assertEqual(bill.status, 'refunded')

    def test_valid_path_draft_received_cancelled(self):
        """Test the path: draft -> received -> cancelled."""
        bill = Bill.objects.create(
            bill_number="BILL-030",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-001',
            status='draft'
        )

        self._add_line_item_to_bill(bill)


        bill.status = 'received'
        bill.save()
        self.assertEqual(bill.status, 'received')

        bill.status = 'cancelled'
        bill.save()
        self.assertEqual(bill.status, 'cancelled')
