from django.test import TestCase
from apps.purchasing.models import Bill, PurchaseOrder
from apps.contacts.models import Contact, Business


class BillBusinessAutoAssociationTest(TestCase):
    """
    Test that Bill automatically associates Business from Contact on creation.
    """

    def setUp(self):
        """Set up test data with businesses and contacts."""
        # Create default contacts for businesses
        self.default_contact1 = Contact.objects.create(first_name='Default Contact 1', last_name='', email='default.contact.1@test.com')
        self.default_contact2 = Contact.objects.create(first_name='Default Contact 2', last_name='', email='default.contact.2@test.com')

        # Create businesses
        self.business1 = Business.objects.create(business_name="Vendor Corp", default_contact=self.default_contact1)
        self.business2 = Business.objects.create(business_name="Alternative Vendor Inc", default_contact=self.default_contact2)

        # Create contact with business
        self.contact_with_business = Contact.objects.create(
            first_name='John Vendor',
            last_name='',
            email='john.vendor@test.com',
            business=self.business1
        )

        # Create contact without business
        self.contact_without_business = Contact.objects.create(
            first_name='Jane Independent',
            last_name='',
            email='jane.independent@test.com',
        )

    def test_bill_auto_associates_business_from_contact_on_creation(self):
        """
        Test that when creating a Bill with a Contact that has a Business,
        the Business is automatically associated with the Bill.
        """
        bill = Bill.objects.create(
            bill_number="BILL-039",
            contact=self.contact_with_business,
            vendor_invoice_number="INV001"
        )

        # Verify business was auto-associated from contact
        self.assertEqual(bill.business, self.business1)
        self.assertEqual(bill.business, self.contact_with_business.business)

    def test_bill_explicit_business_must_match_contact_business(self):
        """
        Test that when creating a Bill with both Contact and Business,
        the Business must match the Contact's Business, otherwise ValidationError is raised.
        """
        from django.core.exceptions import ValidationError

        # Try to create bill with explicit business that differs from contact's business
        bill = Bill(
            bill_number="BILL-041",
            contact=self.contact_with_business,  # has business1
            business=self.business2,  # explicitly set to different business
            vendor_invoice_number="INV003"
        )

        # Should raise ValidationError because business doesn't match contact's business
        with self.assertRaises(ValidationError) as cm:
            bill.save()

        self.assertIn('Contact', str(cm.exception))

    def test_bill_business_not_changed_on_update(self):
        """
        Test that when updating an existing Bill, the business is not changed.
        """
        # Create bill with auto-associated business
        bill = Bill.objects.create(
            bill_number="BILL-042",
            contact=self.contact_with_business,
            vendor_invoice_number="INV004"
        )

        # Verify initial business
        self.assertEqual(bill.business, self.business1)

        # Update the contact's business
        self.contact_with_business.business = self.business2
        self.contact_with_business.save()

        # Update the bill (change vendor invoice number)
        bill.vendor_invoice_number = "INV004-UPDATED"
        bill.save()

        # Verify business was NOT updated
        self.assertEqual(bill.business, self.business1)
        self.assertNotEqual(bill.business, self.contact_with_business.business)

    def test_bill_with_purchase_order_auto_associates_business(self):
        """
        Test that Bill auto-associates business even when created with a PurchaseOrder.
        """
        # Create a purchase order in issued status
        po = PurchaseOrder.objects.create(
            business=self.business1,
            po_number="PO001",
            status='draft'
        )
        po.status = 'issued'
        po.save()

        # Create bill with PO and contact with business
        bill = Bill.objects.create(
            bill_number="BILL-044",
            purchase_order=po,
            contact=self.contact_with_business,
            vendor_invoice_number="INV006"
        )

        # Verify business was auto-associated
        self.assertEqual(bill.business, self.business1)
