"""
Tests for model-level deletion protection in purchasing app.

These tests verify that deletion protection is enforced at the model level,
not just at the view level. This prevents bypassing the protection through
direct ORM operations, Django admin, management commands, or shell access.

Business Rules:
- PurchaseOrders can only be deleted when status is 'draft'
- Bills can only be deleted when status is 'draft'
- Attempting to delete non-draft objects should raise ProtectedError
"""

from django.test import TestCase
from django.core.exceptions import PermissionDenied
from apps.purchasing.models import PurchaseOrder, Bill, BillLineItem
from apps.contacts.models import Contact, Business
from decimal import Decimal


class PurchaseOrderModelDeletionTest(TestCase):
    """Test that PurchaseOrder deletion is protected at the model level."""

    def setUp(self):
        """Set up test data."""
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(
            business_name='Test Vendor Business',
            default_contact=self.default_contact
        )

    def test_can_delete_draft_purchase_order_via_orm(self):
        """Test that draft POs can be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-DRAFT-001',
            status='draft'
        )

        po_id = po.po_id

        # Should succeed without raising exception
        po.delete()

        # Verify it's actually deleted
        self.assertFalse(PurchaseOrder.objects.filter(po_id=po_id).exists())

    def test_cannot_delete_issued_purchase_order_via_orm(self):
        """Test that issued POs cannot be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-ISSUED-001',
            status='draft'
        )
        po.status = 'issued'
        po.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po.po_id).exists())

    def test_cannot_delete_partly_received_purchase_order_via_orm(self):
        """Test that partly_received POs cannot be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-PARTLY-001',
            status='draft'
        )
        po.status = 'issued'
        po.save()
        po.status = 'partly_received'
        po.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po.po_id).exists())

    def test_cannot_delete_received_in_full_purchase_order_via_orm(self):
        """Test that received_in_full POs cannot be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-RECEIVED-001',
            status='draft'
        )
        po.status = 'issued'
        po.save()
        po.status = 'received_in_full'
        po.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po.po_id).exists())

    def test_cannot_delete_cancelled_purchase_order_via_orm(self):
        """Test that cancelled POs cannot be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-CANCELLED-001',
            status='draft'
        )
        po.status = 'issued'
        po.save()
        po.status = 'cancelled'
        po.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po.po_id).exists())


class BillModelDeletionTest(TestCase):
    """Test that Bill deletion is protected at the model level."""

    def setUp(self):
        """Set up test data."""
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(
            business_name='Test Vendor Business',
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='Test Vendor',
            last_name='',
            email='test.vendor@test.com',
            business=self.business
        )

        # Create an issued PO for bill association
        self.po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-TEST-001',
            status='draft'
        )
        self.po.status = 'issued'
        self.po.save()

    def test_can_delete_draft_bill_via_orm(self):
        """Test that draft Bills can be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-DRAFT-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-DRAFT-001',
            status='draft'
        )

        bill_id = bill.bill_id

        # Should succeed without raising exception
        bill.delete()

        # Verify it's actually deleted
        self.assertFalse(Bill.objects.filter(bill_id=bill_id).exists())

    def test_cannot_delete_received_bill_via_orm(self):
        """Test that received Bills cannot be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-RECEIVED-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-RECEIVED-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        bill.status = 'received'
        bill.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            bill.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(Bill.objects.filter(bill_id=bill.bill_id).exists())

    def test_cannot_delete_partly_paid_bill_via_orm(self):
        """Test that partly_paid Bills cannot be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-PARTLY-PAID-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-PARTLY-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        bill.status = 'received'
        bill.save()
        bill.status = 'partly_paid'
        bill.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            bill.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(Bill.objects.filter(bill_id=bill.bill_id).exists())

    def test_cannot_delete_paid_in_full_bill_via_orm(self):
        """Test that paid_in_full Bills cannot be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-PAID-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-PAID-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            bill.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(Bill.objects.filter(bill_id=bill.bill_id).exists())

    def test_cannot_delete_cancelled_bill_via_orm(self):
        """Test that cancelled Bills cannot be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-CANCELLED-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-CANCELLED-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        bill.status = 'received'
        bill.save()
        bill.status = 'cancelled'
        bill.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            bill.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(Bill.objects.filter(bill_id=bill.bill_id).exists())

    def test_cannot_delete_refunded_bill_via_orm(self):
        """Test that refunded Bills cannot be deleted via direct ORM operation."""
        bill = Bill.objects.create(
            bill_number='BILL-REFUNDED-001',
            purchase_order=self.po,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number='INV-REFUNDED-001',
            status='draft'
        )
        # Add line item so it can transition out of draft
        BillLineItem.objects.create(
            bill=bill,
            description="Test item",
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        bill.status = 'received'
        bill.save()
        bill.status = 'paid_in_full'
        bill.save()
        bill.status = 'refunded'
        bill.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            bill.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(Bill.objects.filter(bill_id=bill.bill_id).exists())
