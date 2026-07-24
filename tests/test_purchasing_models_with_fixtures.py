from django.test import TestCase
from django.db import models
from apps.purchasing.models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business


class PurchaseOrderModelFixtureTest(TestCase):
    """
    Test PurchaseOrder model using fixture data
    """
    fixtures = ['core_base_data.json', 'contacts_base_data.json', 'jobs_basic_data.json', 'invoicing_data.json', 'purchasing_data.json']

    def test_purchase_orders_exist_from_fixture(self):
        """Test that purchase orders from fixture data exist and have correct properties"""
        po1 = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        self.assertEqual(po1.business.business_name, "XYZ Industries")

        po2 = PurchaseOrder.objects.get(po_number="PO-2024-0002")
        self.assertEqual(po2.business.business_name, "XYZ Industries")

    def test_purchase_order_str_method_with_fixture_data(self):
        """Test purchase order string representation with fixture data"""
        po = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        self.assertEqual(str(po), "PO PO-2024-0001")

    def test_purchase_order_unique_po_number(self):
        """Test that PO numbers are unique using fixture data as baseline"""
        # Verify existing PO numbers from fixture
        self.assertTrue(PurchaseOrder.objects.filter(po_number="PO-2024-0001").exists())

        # Try to create duplicate - should fail
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        with self.assertRaises(Exception):
            PurchaseOrder.objects.create(business=business, po_number="PO-2024-0001")

    def test_create_new_purchase_order(self):
        """Test creating a new purchase order"""
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        new_po = PurchaseOrder.objects.create(
            business=business,
            po_number="PO-2024-0003"
        )
        self.assertEqual(PurchaseOrder.objects.count(), 3)  # 2 from fixture + 1 new

    def test_purchase_order_without_contact(self):
        """Test creating purchase order without contact"""
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        po = PurchaseOrder.objects.create(
            business=business,
            po_number="PO-2024-0004"
        )
        self.assertIsNone(po.contact)


class BillModelFixtureTest(TestCase):
    """
    Bill is a RETIRED, schema-only model (bills live in QBO). These tests
    cover only the KEPT passive row-safety behavior for legacy fixture rows.
    """
    fixtures = ['core_base_data.json', 'contacts_base_data.json', 'jobs_basic_data.json', 'invoicing_data.json', 'purchasing_data.json']

    def test_bill_fixture_rows_load_inertly(self):
        """Legacy bill rows in fixtures still load against the schema-only model."""
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        self.assertEqual(bill.purchase_order.po_number, "PO-2024-0001")

    def test_bill_protected_from_purchase_order_delete(self):
        """Test that PurchaseOrders with Bills cannot be deleted (PROTECT)"""
        # Get existing bill and its PO
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        po = bill.purchase_order
        bill_id = bill.bill_id
        po_id = po.po_id

        # Attempt to delete the purchase order should fail
        # The PO's own non-draft delete guard fires first
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            po.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Both PO and Bill should still exist
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po_id).exists())
        self.assertTrue(Bill.objects.filter(bill_id=bill_id).exists())

        # Bill should still reference the PO
        bill.refresh_from_db()
        self.assertEqual(bill.purchase_order, po)

    def test_bill_protected_from_contact_deletion(self):
        """Test that bill is protected when vendor contact is deleted (PROTECT)"""
        # Create a new vendor contact for this test to avoid affecting other tests
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        test_vendor = Contact.objects.create(
            first_name='Test Vendor',
            last_name='',
            email="test@vendor.com",
            business=business
        )

        # Create a new legacy-style bill row for this test
        po = PurchaseOrder.objects.get(po_number="PO-2024-0002")
        test_bill = Bill.objects.create(
            purchase_order=po,
            business=business,
            contact=test_vendor,
            vendor_invoice_number="TEST-INV-001"
        )
        bill_id = test_bill.bill_id

        # Try to delete the vendor contact - should raise ProtectedError
        with self.assertRaises(models.ProtectedError):
            test_vendor.delete()

        # Bill should still exist
        Bill.objects.get(bill_id=bill_id)  # Should not raise DoesNotExist
