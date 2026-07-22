"""
Tests for model-level deletion protection in purchasing app.

These tests verify that deletion protection is enforced at the model level,
not just at the view level. This prevents bypassing the protection through
direct ORM operations, Django admin, management commands, or shell access.

Business Rules:
- PurchaseOrders can only be deleted when status is PurchaseOrder.STATUS_DRAFT
- Attempting to delete non-draft objects should raise PermissionDenied

(Bill deletion protection was removed with the Bill domain retirement —
bills live in QBO now; the Bill model is schema-only.)
"""

from django.test import TestCase
from django.core.exceptions import PermissionDenied
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
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

    def _add_po_line_item(self, po):
        PurchaseOrderLineItem.objects.create(purchase_order=po, description='Test item', price=Decimal('100.00'))

    def test_can_delete_draft_purchase_order_via_orm(self):
        """Test that draft POs can be deleted via direct ORM operation."""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-DRAFT-001',
            status=PurchaseOrder.STATUS_DRAFT
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
            status=PurchaseOrder.STATUS_DRAFT
        )
        self._add_po_line_item(po)
        po.status = PurchaseOrder.STATUS_ISSUED
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
            status=PurchaseOrder.STATUS_DRAFT
        )
        self._add_po_line_item(po)
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        po.status = PurchaseOrder.STATUS_PARTLY_RECEIVED
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
            status=PurchaseOrder.STATUS_DRAFT
        )
        self._add_po_line_item(po)
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        po.status = PurchaseOrder.STATUS_RECEIVED_IN_FULL
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
            status=PurchaseOrder.STATUS_DRAFT
        )
        self._add_po_line_item(po)
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        po.status = PurchaseOrder.STATUS_CANCELLED
        po.save()

        # Should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Verify it still exists
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po.po_id).exists())
