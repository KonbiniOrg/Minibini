"""
Tests for deletion functionality in purchasing app.

Tests cover:
- Deleting PurchaseOrders (only in draft status)
- Deleting Bills (only in draft status)
- Deleting line items from POs (only when PO is draft)
- Deleting line items from Bills (only when Bill is draft)
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.purchasing.models import PurchaseOrder, Bill, PurchaseOrderLineItem, BillLineItem
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class PurchaseOrderDeletionTest(TestCase):
    """Test PurchaseOrder deletion functionality."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

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

        # Create a draft PO
        self.draft_po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-DRAFT-001',
            status='draft'
        )

        # Create an issued PO
        self.issued_po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-ISSUED-001',
            status='draft'
        )
        self.issued_po.status = 'issued'
        self.issued_po.save()

    def test_delete_draft_po_via_post(self):
        """Test that draft POs can be deleted via POST."""
        url = reverse('purchasing:purchase_order_delete', args=[self.draft_po.po_id])
        response = self.client.post(url, follow=True)

        # Should redirect to PO list
        self.assertRedirects(response, reverse('purchasing:purchase_order_list'))

        # PO should be deleted
        self.assertFalse(PurchaseOrder.objects.filter(po_id=self.draft_po.po_id).exists())

        # Success message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('deleted successfully', str(messages[0]).lower())

    def test_cannot_delete_non_draft_po(self):
        """Test that non-draft POs cannot be deleted."""
        url = reverse('purchasing:purchase_order_delete', args=[self.issued_po.po_id])
        response = self.client.post(url, follow=True)

        # Should redirect back to detail page
        self.assertRedirects(response, reverse('purchasing:purchase_order_detail', args=[self.issued_po.po_id]))

        # PO should still exist
        self.assertTrue(PurchaseOrder.objects.filter(po_id=self.issued_po.po_id).exists())

        # Error message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('only draft', str(messages[0]).lower())

    def test_delete_po_get_request_shows_confirmation(self):
        """Test that GET request to delete shows confirmation page."""
        url = reverse('purchasing:purchase_order_delete', args=[self.draft_po.po_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'confirm')
        self.assertContains(response, self.draft_po.po_number)


class BillDeletionTest(TestCase):
    """Test Bill deletion functionality."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()

        # Create Configuration for number generation
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

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

        # Create PO for bill association
        self.po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.po.status = 'issued'
        self.po.save()

        # Create a draft bill
        self.draft_bill = Bill.objects.create(
            bill_number='BILL-DRAFT-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-DRAFT-001',
            status='draft'
        )

        # Create a received bill
        self.received_bill = Bill.objects.create(
            bill_number='BILL-RECEIVED-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-RECEIVED-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=self.received_bill,
            description="Test item",
            qty=Decimal('1.00'),
            price=Decimal('100.00')
        )
        self.received_bill.status = 'received'
        self.received_bill.save()

    def test_delete_draft_bill_via_post(self):
        """Test that draft bills can be deleted via POST."""
        url = reverse('purchasing:bill_delete', args=[self.draft_bill.bill_id])
        response = self.client.post(url, follow=True)

        # Should redirect to bill list
        self.assertRedirects(response, reverse('purchasing:bill_list'))

        # Bill should be deleted
        self.assertFalse(Bill.objects.filter(bill_id=self.draft_bill.bill_id).exists())

        # Success message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('deleted successfully', str(messages[0]).lower())

    def test_cannot_delete_non_draft_bill(self):
        """Test that non-draft bills cannot be deleted."""
        url = reverse('purchasing:bill_delete', args=[self.received_bill.bill_id])
        response = self.client.post(url, follow=True)

        # Should redirect back to detail page
        self.assertRedirects(response, reverse('purchasing:bill_detail', args=[self.received_bill.bill_id]))

        # Bill should still exist
        self.assertTrue(Bill.objects.filter(bill_id=self.received_bill.bill_id).exists())

        # Error message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('only draft', str(messages[0]).lower())

    def test_delete_bill_get_request_shows_confirmation(self):
        """Test that GET request to delete shows confirmation page."""
        url = reverse('purchasing:bill_delete', args=[self.draft_bill.bill_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'confirm')
        self.assertContains(response, self.draft_bill.bill_number)


class PurchaseOrderLineItemDeletionTest(TestCase):
    """Test PurchaseOrderLineItem deletion functionality."""

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

        # Create draft PO
        self.draft_po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-DRAFT-001',
            status='draft'
        )

        # Create issued PO
        self.issued_po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-ISSUED-001',
            status='draft'
        )
        self.issued_po.status = 'issued'
        self.issued_po.save()

        # Create line items for draft PO
        self.line_item_1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.draft_po,
            description="Item 1",
            qty=Decimal('1.00'),
            price=Decimal('10.00'),
            line_number=1
        )
        self.line_item_2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.draft_po,
            description="Item 2",
            qty=Decimal('2.00'),
            price=Decimal('20.00'),
            line_number=2
        )
        self.line_item_3 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.draft_po,
            description="Item 3",
            qty=Decimal('3.00'),
            price=Decimal('30.00'),
            line_number=3
        )

        # Create line item for issued PO
        self.issued_line_item = PurchaseOrderLineItem.objects.create(
            purchase_order=self.issued_po,
            description="Issued item",
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            line_number=1
        )

    def test_delete_po_line_item_via_post(self):
        """Test that line items can be deleted from draft POs."""
        url = reverse('purchasing:purchase_order_delete_line_item', args=[
            self.draft_po.po_id,
            self.line_item_2.line_item_id
        ])
        response = self.client.post(url, follow=True)

        # Should redirect to PO detail
        self.assertRedirects(response, reverse('purchasing:purchase_order_detail', args=[self.draft_po.po_id]))

        # Line item should be deleted
        self.assertFalse(PurchaseOrderLineItem.objects.filter(line_item_id=self.line_item_2.line_item_id).exists())

        # Remaining items should be renumbered
        remaining_items = PurchaseOrderLineItem.objects.filter(purchase_order=self.draft_po).order_by('line_number')
        self.assertEqual(remaining_items.count(), 2)
        self.assertEqual(remaining_items[0].line_number, 1)  # Was item 1, stays 1
        self.assertEqual(remaining_items[1].line_number, 2)  # Was item 3, now 2

        # Success message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('deleted', str(messages[0]).lower())

    def test_cannot_delete_line_item_from_non_draft_po(self):
        """Test that line items cannot be deleted from non-draft POs."""
        url = reverse('purchasing:purchase_order_delete_line_item', args=[
            self.issued_po.po_id,
            self.issued_line_item.line_item_id
        ])
        response = self.client.post(url, follow=True)

        # Should redirect back to detail page
        self.assertRedirects(response, reverse('purchasing:purchase_order_detail', args=[self.issued_po.po_id]))

        # Line item should still exist
        self.assertTrue(PurchaseOrderLineItem.objects.filter(line_item_id=self.issued_line_item.line_item_id).exists())

        # Error message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('cannot modify', str(messages[0]).lower())


class BillLineItemDeletionTest(TestCase):
    """Test BillLineItem deletion functionality."""

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

        # Create PO
        self.po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.po.status = 'issued'
        self.po.save()

        # Create draft bill
        self.draft_bill = Bill.objects.create(
            bill_number='BILL-DRAFT-001',
            purchase_order=self.po,
            business=self.business,
            vendor_invoice_number='INV-DRAFT-001',
            status='draft'
        )

        # Create received bill
        self.received_bill = Bill.objects.create(
            bill_number='BILL-RECEIVED-001',
            purchase_order=self.po,
            business=self.business,
            vendor_invoice_number='INV-RECEIVED-001',
            status='draft'
        )

        # Create line items for draft bill
        self.line_item_1 = BillLineItem.objects.create(
            bill=self.draft_bill,
            description="Item 1",
            qty=Decimal('1.00'),
            price=Decimal('10.00'),
            line_number=1
        )
        self.line_item_2 = BillLineItem.objects.create(
            bill=self.draft_bill,
            description="Item 2",
            qty=Decimal('2.00'),
            price=Decimal('20.00'),
            line_number=2
        )
        self.line_item_3 = BillLineItem.objects.create(
            bill=self.draft_bill,
            description="Item 3",
            qty=Decimal('3.00'),
            price=Decimal('30.00'),
            line_number=3
        )

        # Create line item for received bill and transition
        self.received_line_item = BillLineItem.objects.create(
            bill=self.received_bill,
            description="Received item",
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
            line_number=1
        )
        self.received_bill.status = 'received'
        self.received_bill.save()

    def test_delete_bill_line_item_via_post(self):
        """Test that line items can be deleted from draft bills."""
        url = reverse('purchasing:bill_delete_line_item', args=[
            self.draft_bill.bill_id,
            self.line_item_2.line_item_id
        ])
        response = self.client.post(url, follow=True)

        # Should redirect to bill detail
        self.assertRedirects(response, reverse('purchasing:bill_detail', args=[self.draft_bill.bill_id]))

        # Line item should be deleted
        self.assertFalse(BillLineItem.objects.filter(line_item_id=self.line_item_2.line_item_id).exists())

        # Remaining items should be renumbered
        remaining_items = BillLineItem.objects.filter(bill=self.draft_bill).order_by('line_number')
        self.assertEqual(remaining_items.count(), 2)
        self.assertEqual(remaining_items[0].line_number, 1)  # Was item 1, stays 1
        self.assertEqual(remaining_items[1].line_number, 2)  # Was item 3, now 2

        # Success message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('deleted', str(messages[0]).lower())

    def test_cannot_delete_line_item_from_non_draft_bill(self):
        """Test that line items cannot be deleted from non-draft bills."""
        url = reverse('purchasing:bill_delete_line_item', args=[
            self.received_bill.bill_id,
            self.received_line_item.line_item_id
        ])
        response = self.client.post(url, follow=True)

        # Should redirect back to detail page
        self.assertRedirects(response, reverse('purchasing:bill_detail', args=[self.received_bill.bill_id]))

        # Line item should still exist
        self.assertTrue(BillLineItem.objects.filter(line_item_id=self.received_line_item.line_item_id).exists())

        # Error message should be shown
        messages = list(response.context['messages'])
        self.assertTrue(len(messages) >= 1)
        self.assertIn('cannot modify', str(messages[0]).lower())
