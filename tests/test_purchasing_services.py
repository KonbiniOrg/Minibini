"""Tests for purchasing app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import (
    PurchaseOrder, Bill, PurchaseOrderLineItem, BillLineItem,
)
from apps.purchasing.services import PurchaseOrderService, BillService
from apps.core.services import NotFoundError
from apps.core.models import LineItemType
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
        self.lit = LineItemType.objects.create(
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
        self.assertEqual(po.status, 'draft')
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
        updated = PurchaseOrderService.update_status(self.po.pk, 'issued')
        self.assertEqual(updated.status, 'issued')

    def test_update_status_not_found(self):
        """Nonexistent PO raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            PurchaseOrderService.update_status(99999, 'issued')


class PurchaseOrderServiceCancelTest(PurchasingTestBase):
    """Tests for PurchaseOrderService.cancel_po."""

    def test_cancel_issued_po(self):
        """Cancel an issued PO."""
        po = PurchaseOrderService.create_po(business=self.business)
        po.status = 'issued'
        po.save()
        cancelled = PurchaseOrderService.cancel_po(po.pk)
        self.assertEqual(cancelled.status, 'cancelled')

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
        po.status = 'issued'
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
            price=Decimal('10.00'), line_item_type=self.lit,
        )
        self.assertEqual(li.purchase_order, self.po)
        self.assertEqual(li.description, 'Steel plate')
        self.assertIsNotNone(li.pk)

    def test_add_line_item_from_pli(self):
        """Add a line item from a PriceListItem."""
        from apps.inventory.models import PriceListItem
        pli = PriceListItem.objects.create(
            code='STL-001', description='Steel plate', units='sheets',
            purchase_price=Decimal('50.00'), selling_price=Decimal('75.00'),
            line_item_type=self.lit,
        )
        li = PurchaseOrderService.add_line_item_from_pli(
            self.po.pk, pli.pk, qty=Decimal('10.00'),
        )
        self.assertEqual(li.price_list_item, pli)
        self.assertEqual(li.price, Decimal('50.00'))
        self.assertEqual(li.description, 'Steel plate')

    def test_reorder_line_item(self):
        """Reorder line items via service."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), line_item_type=self.lit,
        )
        li2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), line_item_type=self.lit,
        )
        PurchaseOrderService.reorder_line_item(li1.pk, 'down')
        li1.refresh_from_db()
        li2.refresh_from_db()
        self.assertEqual(li1.line_number, 2)
        self.assertEqual(li2.line_number, 1)

    def test_delete_line_item(self):
        """Delete a line item and renumber."""
        li1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), line_item_type=self.lit,
        )
        li2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), line_item_type=self.lit,
        )
        PurchaseOrderService.delete_line_item(li1.pk)
        self.assertFalse(PurchaseOrderLineItem.objects.filter(pk=li1.pk).exists())
        li2.refresh_from_db()
        self.assertEqual(li2.line_number, 1)


class BillServiceCreateTest(PurchasingTestBase):
    """Tests for BillService.create_bill."""

    def test_create_bill(self):
        """Create a bill."""
        bill = BillService.create_bill(
            business=self.business, vendor_invoice_number='VINV-001',
        )
        self.assertIsNotNone(bill.pk)
        self.assertTrue(bill.bill_number.startswith('BILL'))
        self.assertEqual(bill.status, 'draft')

    def test_create_bill_from_po(self):
        """Create a bill from an issued PO, copying line items."""
        po = PurchaseOrderService.create_po(business=self.business)
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item 1',
            line_number=1, qty=Decimal('5.00'), price=Decimal('10.00'),
            line_item_type=self.lit,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item 2',
            line_number=2, qty=Decimal('3.00'), price=Decimal('20.00'),
            line_item_type=self.lit,
        )
        # PO must be issued before creating a bill from it
        PurchaseOrderService.update_status(po.pk, 'issued')
        bill = BillService.create_bill_from_po(
            po.pk, vendor_invoice_number='VINV-002',
        )
        self.assertEqual(bill.purchase_order, po)
        self.assertEqual(bill.business, po.business)
        bill_items = BillLineItem.objects.filter(bill=bill)
        self.assertEqual(bill_items.count(), 2)
        self.assertEqual(bill_items.first().description, 'Item 1')


class BillServiceStatusTest(PurchasingTestBase):
    """Tests for BillService.update_status."""

    def test_update_status(self):
        """Valid transition: draft → received (requires line item)."""
        bill = BillService.create_bill(
            business=self.business, vendor_invoice_number='VINV-001',
        )
        # Bill needs at least one line item before status change
        BillLineItem.objects.create(
            bill=bill, description='Item 1', line_number=1,
            qty=1, price=Decimal('10.00'), line_item_type=self.lit,
        )
        updated = BillService.update_status(bill.pk, 'received')
        self.assertEqual(updated.status, 'received')

    def test_update_status_not_found(self):
        """Nonexistent bill raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            BillService.update_status(99999, 'received')


class BillServiceDeleteTest(PurchasingTestBase):
    """Tests for BillService.delete_bill."""

    def test_delete_draft_bill(self):
        """Delete a draft bill."""
        bill = BillService.create_bill(
            business=self.business, vendor_invoice_number='VINV-001',
        )
        pk = bill.pk
        BillService.delete_bill(pk)
        self.assertFalse(Bill.objects.filter(pk=pk).exists())

    def test_delete_received_bill_raises(self):
        """Cannot delete a received bill."""
        bill = BillService.create_bill(
            business=self.business, vendor_invoice_number='VINV-001',
        )
        # Bill needs a line item before status change
        BillLineItem.objects.create(
            bill=bill, description='Item 1', line_number=1,
            qty=1, price=Decimal('10.00'), line_item_type=self.lit,
        )
        BillService.update_status(bill.pk, 'received')
        with self.assertRaises(ValidationError):
            BillService.delete_bill(bill.pk)


class BillServiceLineItemTest(PurchasingTestBase):
    """Tests for BillService line item operations."""

    def setUp(self):
        super().setUp()
        self.bill = BillService.create_bill(
            business=self.business, vendor_invoice_number='VINV-001',
        )

    def test_add_line_item(self):
        """Add a manual line item to a bill."""
        li = BillService.add_line_item(
            self.bill.pk, description='Bolts', qty=Decimal('100.00'),
            price=Decimal('0.50'), line_item_type=self.lit,
        )
        self.assertEqual(li.bill, self.bill)
        self.assertEqual(li.description, 'Bolts')

    def test_add_line_item_from_pli(self):
        """Add a line item from a PriceListItem."""
        from apps.inventory.models import PriceListItem
        pli = PriceListItem.objects.create(
            code='BLT-001', description='Bolts', units='pcs',
            purchase_price=Decimal('0.50'), selling_price=Decimal('1.00'),
            line_item_type=self.lit,
        )
        li = BillService.add_line_item_from_pli(
            self.bill.pk, pli.pk, qty=Decimal('100.00'),
        )
        self.assertEqual(li.price_list_item, pli)
        self.assertEqual(li.price, Decimal('0.50'))

    def test_reorder_line_item(self):
        """Reorder bill line items via service."""
        li1 = BillLineItem.objects.create(
            bill=self.bill, description='Item 1',
            line_number=1, qty=1, price=Decimal('10.00'), line_item_type=self.lit,
        )
        li2 = BillLineItem.objects.create(
            bill=self.bill, description='Item 2',
            line_number=2, qty=1, price=Decimal('20.00'), line_item_type=self.lit,
        )
        BillService.reorder_line_item(li1.pk, 'down')
        li1.refresh_from_db()
        li2.refresh_from_db()
        self.assertEqual(li1.line_number, 2)
        self.assertEqual(li2.line_number, 1)
