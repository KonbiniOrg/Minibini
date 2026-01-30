from django.test import TestCase
from django.db import models
from apps.purchasing.models import PurchaseOrder, Bill
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class PurchaseOrderModelTest(TestCase):
    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.contact,
            description="Test job"
        )
        
    def test_purchase_order_creation(self):
        po = PurchaseOrder.objects.create(
            business=self.business,
            job=self.job,
            po_number="PO001"
        )
        self.assertEqual(po.job, self.job)
        self.assertEqual(po.po_number, "PO001")
        
    def test_purchase_order_str_method(self):
        po = PurchaseOrder.objects.create(business=self.business, po_number="PO002")
        self.assertEqual(str(po), "PO PO002")
        
    def test_purchase_order_optional_job(self):
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO003"
        )
        self.assertIsNone(po.job)

    def test_purchase_order_without_job(self):
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO004"
        )
        self.assertIsNone(po.job)
        self.assertEqual(po.po_number, "PO004")
        
    def test_purchase_order_unique_po_number(self):
        PurchaseOrder.objects.create(business=self.business, po_number="UNIQUE001")

        with self.assertRaises(Exception):
            PurchaseOrder.objects.create(business=self.business, po_number="UNIQUE001")


class PurchaseOrderFormTest(TestCase):
    """Test PurchaseOrderForm behavior."""

    def setUp(self):
        from apps.core.models import Configuration
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.default_contact = Contact.objects.create(
            first_name='Default Contact', last_name='', email='default.contact@test.com'
        )
        self.business = Business.objects.create(
            business_name="Test Business", default_contact=self.default_contact
        )
        self.default_contact.business = self.business
        self.default_contact.save()

    def test_form_preserves_po_number_on_edit(self):
        """Editing an existing PO should not regenerate the PO number.

        This is a critical bug fix - previously the form's save() method would
        always generate a new PO number, even when editing.
        """
        from apps.purchasing.forms import PurchaseOrderForm

        # Create a PO with a specific number
        existing_po = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO-PRESERVE-001",
            status='draft'
        )
        original_po_number = existing_po.po_number

        # Use the form to edit it
        form = PurchaseOrderForm(
            data={
                'business': self.business.business_id,
                'contact': self.default_contact.contact_id,
                'status': 'issued'
            },
            instance=existing_po
        )

        if form.is_valid():
            updated_po = form.save()
            # PO number should be preserved
            self.assertEqual(updated_po.po_number, original_po_number)
        else:
            self.fail(f"Form should be valid: {form.errors}")


class BillModelTest(TestCase):
    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Business", default_contact=self.default_contact)
        # Associate default_contact with business so it's not the sole contact
        self.default_contact.business = self.business
        self.default_contact.save()
        self.contact = Contact.objects.create(
            first_name='Test Vendor',
            last_name='',
            email='test.vendor@test.com',
            business=self.business
        )
        self.customer_contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com')
        self.job = Job.objects.create(
            job_number="JOB001",
            contact=self.customer_contact,
            description="Test job"
        )
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            job=self.job,
            po_number="PO001",
            status='draft'
        )
        self.purchase_order.status = 'issued'
        self.purchase_order.save()
        
    def test_bill_creation(self):
        bill = Bill.objects.create(
            bill_number="BILL-001",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VIN001"
        )
        self.assertEqual(bill.purchase_order, self.purchase_order)
        self.assertEqual(bill.business, self.business)
        self.assertEqual(bill.contact, self.contact)
        self.assertEqual(bill.vendor_invoice_number, "VIN001")
        
    def test_bill_str_method(self):
        bill = Bill.objects.create(
            bill_number="BILL-002",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VIN002"
        )
        self.assertEqual(str(bill), f"Bill {bill.bill_number}")
        
    def test_bill_protected_from_po_delete(self):
        """Test that PurchaseOrders with Bills cannot be deleted (PROTECT)."""
        bill = Bill.objects.create(
            bill_number="BILL-003",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VIN003"
        )
        bill_id = bill.bill_id
        po_id = self.purchase_order.po_id

        # Attempt to delete the purchase order should fail
        # Since Bills can only exist on issued+ POs, our model-level check fires first
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            self.purchase_order.delete()

        self.assertIn('draft', str(context.exception).lower())

        # Both PO and Bill should still exist
        self.assertTrue(PurchaseOrder.objects.filter(po_id=po_id).exists())
        self.assertTrue(Bill.objects.filter(bill_id=bill_id).exists())

        # Bill should still reference the PO
        bill.refresh_from_db()
        self.assertEqual(bill.purchase_order, self.purchase_order)
            
    def test_bill_with_contact_deletion(self):
        bill = Bill.objects.create(
            bill_number="BILL-004",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VIN004"
        )
        contact_id = self.contact.pk

        # Cannot delete the contact due to PROTECT
        with self.assertRaises(models.ProtectedError):
            self.contact.delete()
