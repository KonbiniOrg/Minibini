from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.purchasing.models import PurchaseOrder
from apps.contacts.models import Contact, Business


class PurchaseOrderContactBusinessTest(TestCase):
    """Test Contact and Business associations for PurchaseOrder"""

    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Vendor", default_contact=self.default_contact)
        self.business2 = Business.objects.create(business_name="Another Vendor", default_contact=self.default_contact)
        self.contact_with_business = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email='test.contact@test.com',
            business=self.business
        )
        self.contact_without_business = Contact.objects.create(first_name='Contact No Business', last_name='', email='contact.no.business@test.com')

    def test_po_creation_with_business_only(self):
        """PO can be created with just a Business"""
        po = PurchaseOrder.objects.create(
            business=self.business,
            po_number="PO001"
        )
        self.assertEqual(po.business, self.business)
        self.assertIsNone(po.contact)

    def test_po_creation_with_contact_and_business(self):
        """PO can be created with both Contact and Business"""
        po = PurchaseOrder.objects.create(
            business=self.business,
            contact=self.contact_with_business,
            po_number="PO002"
        )
        self.assertEqual(po.business, self.business)
        self.assertEqual(po.contact, self.contact_with_business)

    def test_po_contact_auto_assigns_business(self):
        """When Contact is provided without Business, Business is auto-assigned from Contact"""
        po = PurchaseOrder(
            contact=self.contact_with_business,
            po_number="PO003"
        )
        po.save()

        # Business should be auto-assigned from contact
        self.assertEqual(po.business, self.business)
        self.assertEqual(po.contact, self.contact_with_business)

    def test_po_contact_business_mismatch_fails(self):
        """PO creation fails if Contact's Business doesn't match explicitly set Business"""
        po = PurchaseOrder(
            business=self.business2,  # Different from contact's business
            contact=self.contact_with_business,
            po_number="PO003a"
        )

        with self.assertRaises(ValidationError) as cm:
            po.save()

        self.assertIn('The Business must match', str(cm.exception))

    def test_po_contact_without_business_fails(self):
        """PO creation fails if Contact doesn't have a Business"""
        po = PurchaseOrder(
            business=self.business,
            contact=self.contact_without_business,
            po_number="PO004"
        )

        with self.assertRaises(ValidationError) as cm:
            po.save()

        self.assertIn('does not have a Business associated', str(cm.exception))

    def test_po_can_be_created_without_business(self):
        """PO can be created without a Business — a draft PO exists before the
        vendor is known (see tests.test_po_vendorless_draft for the issue-time
        gate that requires a Business before the PO can move to Issued)."""
        po = PurchaseOrder.objects.create(po_number="PO005")
        self.assertIsNone(po.business_id)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
