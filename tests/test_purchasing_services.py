"""Tests for purchasing app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.services import NotFoundError
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact, Business


class PurchasingTestBase(TestCase):
    """Shared setUp for purchasing service tests."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Vendor',
            email='vendor@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Vendor Co', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.lit = AccountingCategory.objects.create(
            code='MAT', name='Material', taxable=True,
        )


class PurchaseOrderServiceCreateTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.create_po."""

    def test_create_po(self):
        """Create a PO with auto-generated number."""
        po = PurchaseOrderService.create_po(
            business=self.business, contact=self.contact,
        )
        self.assertIsNotNone(po.pk)
        self.assertTrue(po.po_number.startswith('PO'))
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertEqual(po.business, self.business)

    def test_create_po_minimal(self):
        """Create a PO with just a business."""
        po = PurchaseOrderService.create_po(business=self.business)
        self.assertIsNotNone(po.pk)
        self.assertIsNone(po.contact)


class PurchaseOrderServiceUpdateTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.update_po."""

    def setUp(self):
        super().setUp()
        self.po = PurchaseOrderService.create_po(business=self.business)

    def test_update_po(self):
        """Update PO fields."""
        other_biz = Business.objects.create(
            business_name='Other Vendor', business_phone='555-9999',
            default_contact=self.contact,
        )
        updated = PurchaseOrderService.update_po(self.po.pk, business=other_biz)
        self.assertEqual(updated.business, other_biz)

    def test_update_po_not_found(self):
        """Updating a nonexistent PO raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            PurchaseOrderService.update_po(99999, business=self.business)


class PurchaseOrderServiceStatusTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.update_status."""

    def setUp(self):
        super().setUp()
        self.po = PurchaseOrderService.create_po(business=self.business)

    def test_update_status_draft_to_issued(self):
        """Valid transition: draft → issued."""
        PurchaseOrderLineItem.objects.create(purchase_order=self.po, description='Test item', price=Decimal('100.00'))
        updated = PurchaseOrderService.update_status(self.po.pk, PurchaseOrder.STATUS_ISSUED)
        self.assertEqual(updated.status, PurchaseOrder.STATUS_ISSUED)

    def test_update_status_not_found(self):
        """Nonexistent PO raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            PurchaseOrderService.update_status(99999, PurchaseOrder.STATUS_ISSUED)


class PurchaseOrderServiceCancelTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.cancel_po."""

    def test_cancel_issued_po(self):
        """Cancel an issued PO."""
        po = PurchaseOrderService.create_po(business=self.business)
        li = PurchaseOrderLineItem.objects.create(purchase_order=po, description='Test item', price=Decimal('100.00'), qty=Decimal('5.00'))
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        cancelled = PurchaseOrderService.cancel_po(po.pk)
        self.assertEqual(cancelled.status, PurchaseOrder.STATUS_CANCELLED)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, li.qty)

    def test_cancel_issued_po_with_partial_receipt_sets_remaining_cancelled(self):
        """Cancel a partially received PO — qty_cancelled should be qty - qty_received."""
        # Note: cancel_po only works on ISSUED POs, so this tests the line item math
        po = PurchaseOrderService.create_po(business=self.business)
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Test item', price=Decimal('100.00'), qty=Decimal('10.00'),
            qty_received=Decimal('3.00'),
        )
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        PurchaseOrderService.cancel_po(po.pk)
        li.refresh_from_db()
        self.assertEqual(li.qty_cancelled, Decimal('7.00'))

    def test_cancel_draft_po_raises(self):
        """Cannot cancel a draft PO."""
        po = PurchaseOrderService.create_po(business=self.business)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.cancel_po(po.pk)


class PurchaseOrderServiceDeleteTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.delete_po."""

    def test_delete_draft_po(self):
        """Delete a draft PO."""
        po = PurchaseOrderService.create_po(business=self.business)
        pk = po.pk
        PurchaseOrderService.delete_po(pk)
        self.assertFalse(PurchaseOrder.objects.filter(pk=pk).exists())

    def test_delete_issued_po_raises(self):
        """Cannot delete an issued PO."""
        po = PurchaseOrderService.create_po(business=self.business)
        PurchaseOrderLineItem.objects.create(purchase_order=po, description='Test item', price=Decimal('100.00'))
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.delete_po(po.pk)


class PurchaseOrderServiceLineItemTest(PurchasingTestBase):
    """Tests for PurchaseOrderService line item operations."""

    def setUp(self):
        super().setUp()
        self.po = PurchaseOrderService.create_po(business=self.business)

    def test_add_line_item(self):
        """Add a manual line item to a PO."""
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='Steel plate', qty=Decimal('5.00'),
            price=Decimal('10.00'), accounting_category=self.lit,
        )
        self.assertEqual(li.purchase_order, self.po)
        self.assertEqual(li.description, 'Steel plate')
        self.assertIsNotNone(li.pk)

    def test_add_line_item_from_pli(self):
        """Add a line item from a InventoryItem."""
        from apps.inventory.models import InventoryItem
        pli = InventoryItem.objects.create(
            code='STL-001', description='Steel plate', units='sheet',
            purchase_price=Decimal('50.00'), selling_price=Decimal('75.00'),
            accounting_category=self.lit,
        )
        li = PurchaseOrderService.add_line_item_from_pli(
            self.po.pk, pli.pk, qty=Decimal('10.00'),
        )
        self.assertEqual(li.inventory_item, pli)
        self.assertEqual(li.price, Decimal('50.00'))
        self.assertEqual(li.description, 'Steel plate')

    def test_reorder_line_item(self):
        """Reorder line items via service."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        li2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), accounting_category=self.lit,
        )
        PurchaseOrderService.reorder_line_item(li1.pk, 'down')
        li1.refresh_from_db()
        li2.refresh_from_db()
        self.assertEqual(li1.line_number, 2)
        self.assertEqual(li2.line_number, 1)

    def test_reorder_line_item_non_draft_raises(self):
        """Cannot reorder line items on a non-draft PO."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), accounting_category=self.lit,
        )
        PurchaseOrderService.update_status(self.po.pk, PurchaseOrder.STATUS_ISSUED)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.reorder_line_item(li1.pk, 'down')

    def test_delete_line_item(self):
        """Delete a line item and renumber."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        li2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), accounting_category=self.lit,
        )
        PurchaseOrderService.delete_line_item(li1.pk)
        self.assertFalse(PurchaseOrderLineItem.objects.filter(pk=li1.pk).exists())
        li2.refresh_from_db()
        self.assertEqual(li2.line_number, 1)

    def test_delete_line_item_non_draft_raises(self):
        """Cannot delete line items on a non-draft PO."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), accounting_category=self.lit,
        )
        PurchaseOrderService.update_status(self.po.pk, PurchaseOrder.STATUS_ISSUED)
        with self.assertRaises(ValidationError):
            PurchaseOrderService.delete_line_item(li1.pk)
