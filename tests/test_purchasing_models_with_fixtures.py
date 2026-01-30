from django.test import TestCase
from django.db import models
from apps.purchasing.models import PurchaseOrder, Bill
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class PurchaseOrderModelFixtureTest(TestCase):
    """
    Test PurchaseOrder model using fixture data
    """
    fixtures = ['core_base_data.json', 'contacts_base_data.json', 'jobs_basic_data.json', 'invoicing_data.json', 'purchasing_data.json']

    def test_purchase_orders_exist_from_fixture(self):
        """Test that purchase orders from fixture data exist and have correct properties"""
        po1 = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        self.assertEqual(po1.job.job_number, "JOB-2024-0001")

        po2 = PurchaseOrder.objects.get(po_number="PO-2024-0002")
        self.assertEqual(po2.job.job_number, "JOB-2024-0002")

    def test_purchase_order_str_method_with_fixture_data(self):
        """Test purchase order string representation with fixture data"""
        po = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        self.assertEqual(str(po), "PO PO-2024-0001")

    def test_purchase_order_job_relationships(self):
        """Test that purchase orders are properly linked to jobs"""
        po = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(po.job, job)

    def test_purchase_order_unique_po_number(self):
        """Test that PO numbers are unique using fixture data as baseline"""
        # Verify existing PO numbers from fixture
        self.assertTrue(PurchaseOrder.objects.filter(po_number="PO-2024-0001").exists())

        # Try to create duplicate - should fail
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        with self.assertRaises(Exception):
            PurchaseOrder.objects.create(business=business, po_number="PO-2024-0001")

    def test_create_new_purchase_order_with_existing_job(self):
        """Test creating a new purchase order for existing job from fixtures"""
        job = Job.objects.get(job_number="JOB-2024-0001")
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        new_po = PurchaseOrder.objects.create(
            business=business,
            job=job,
            po_number="PO-2024-0003"
        )
        self.assertEqual(new_po.job, job)
        self.assertEqual(PurchaseOrder.objects.count(), 3)  # 2 from fixture + 1 new

    def test_purchase_order_without_job(self):
        """Test creating purchase order without job relationship"""
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        po_without_job = PurchaseOrder.objects.create(
            business=business,
            po_number="PO-2024-0004"
        )
        self.assertIsNone(po_without_job.job)

    def test_purchase_order_set_null_on_job_delete(self):
        """Test purchase order job is set to NULL when related job is deleted"""
        # Create a new job for this test
        contact = Contact.objects.get(first_name="John", last_name="Doe")
        test_job = Job.objects.create(
            job_number="JOB-TEST-DELETE",
            contact=contact,
            description="Test job for deletion"
        )

        # Create PO linked to this job
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture
        test_po = PurchaseOrder.objects.create(
            business=business,
            job=test_job,
            po_number="PO-TEST-DELETE"
        )
        po_id = test_po.po_id

        # Delete the job - PO should have job set to NULL (not deleted)
        test_job.delete()

        # PO should still exist with job=None due to SET_NULL
        test_po.refresh_from_db()
        self.assertIsNone(test_po.job)


class BillModelFixtureTest(TestCase):
    """
    Test Bill model using fixture data
    """
    fixtures = ['core_base_data.json', 'contacts_base_data.json', 'jobs_basic_data.json', 'invoicing_data.json', 'purchasing_data.json']

    def test_bills_exist_from_fixture(self):
        """Test that bills from fixture data exist and have correct properties"""
        bill1 = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        self.assertEqual(bill1.purchase_order.po_number, "PO-2024-0001")
        self.assertEqual(bill1.contact.name, "Acme Vendor")

        bill2 = Bill.objects.get(vendor_invoice_number="ACME-INV-002")
        self.assertEqual(bill2.purchase_order.po_number, "PO-2024-0002")
        self.assertEqual(bill2.contact.name, "Acme Vendor")

    def test_bill_str_method_with_fixture_data(self):
        """Test bill string representation with fixture data"""
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        expected_str = f"Bill {bill.bill_number}"
        self.assertEqual(str(bill), expected_str)

    def test_bill_purchase_order_relationships(self):
        """Test that bills are properly linked to purchase orders"""
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        po = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        self.assertEqual(bill.purchase_order, po)

    def test_bill_contact_relationships(self):
        """Test that bills are properly linked to vendor contacts"""
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        vendor = Contact.objects.get(first_name="Acme", last_name="Vendor")
        self.assertEqual(bill.contact, vendor)

    def test_create_new_bill_with_existing_relationships(self):
        """Test creating a new bill with existing PO and contact from fixtures"""
        po = PurchaseOrder.objects.get(po_number="PO-2024-0001")
        vendor = Contact.objects.get(first_name="Acme", last_name="Vendor")
        business = Business.objects.get(pk=2)  # XYZ Industries from fixture

        new_bill = Bill.objects.create(
            purchase_order=po,
            business=business,
            contact=vendor,
            bill_number='BILL-TEST',
            vendor_invoice_number="ACME-INV-003"
        )

        self.assertEqual(new_bill.purchase_order, po)
        self.assertEqual(new_bill.business, business)
        self.assertEqual(new_bill.contact, vendor)
        self.assertEqual(Bill.objects.count(), 3)  # 2 from fixture + 1 new

    def test_bill_protected_from_purchase_order_delete(self):
        """Test that PurchaseOrders with Bills cannot be deleted (PROTECT)"""
        # Get existing bill and its PO
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")
        po = bill.purchase_order
        bill_id = bill.bill_id
        po_id = po.po_id

        # Attempt to delete the purchase order should fail
        # Since Bills can only exist on issued+ POs, our model-level check fires first
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

        # Create a new PO and bill for this test
        po = PurchaseOrder.objects.get(po_number="PO-2024-0002")
        test_bill = Bill.objects.create(
            purchase_order=po,
            contact=test_vendor,
            bill_number='BILL-TEST',
            vendor_invoice_number="TEST-INV-001"
        )
        bill_id = test_bill.bill_id

        # Try to delete the vendor contact - should raise ProtectedError
        with self.assertRaises(models.ProtectedError):
            test_vendor.delete()

        # Bill should still exist
        Bill.objects.get(bill_id=bill_id)  # Should not raise DoesNotExist

    def test_bill_relationships_through_job(self):
        """Test bill relationships that trace back to jobs through purchase orders"""
        bill = Bill.objects.get(vendor_invoice_number="ACME-INV-001")

        # Trace relationship: Bill -> PO -> Job
        job_through_po = bill.purchase_order.job
        expected_job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(job_through_po, expected_job)

        # Verify we can get the customer contact through this relationship
        customer_contact = job_through_po.contact
        expected_customer = Contact.objects.get(first_name="John", last_name="Doe")
        self.assertEqual(customer_contact, expected_customer)
