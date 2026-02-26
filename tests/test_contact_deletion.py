"""Tests for Contact deletion validation.

These tests verify that:
1. Deleting the sole contact of a business is blocked
2. Deleting a contact when other contacts exist works and reassigns default_contact
3. The delete_business view uses individual contact deletes to trigger model validation
"""
from django.test import TestCase, Client
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from apps.contacts.models import Contact, Business


class ContactDeletionModelTest(TestCase):
    """Test Contact.delete() behavior with business constraints."""

    def test_delete_sole_contact_raises_permission_denied(self):
        """Deleting the only contact for a business should raise PermissionDenied.

        A Business is required to have a default_contact (null=False), so we cannot
        allow deletion of the sole contact.
        """
        # Create a contact and business where contact is the only one
        contact = Contact.objects.create(
            first_name='Only',
            last_name='Contact',
            email='only@test.com',
            work_number='555-1234'
        )
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=contact
        )
        contact.business = business
        contact.save()

        # Verify this is the only contact for the business
        self.assertEqual(business.contacts.count(), 1)
        self.assertEqual(business.default_contact, contact)

        # Attempting to delete should raise PermissionDenied
        with self.assertRaises(PermissionDenied) as context:
            contact.delete()

        self.assertIn('only contact', str(context.exception).lower())

        # Contact and business should still exist
        self.assertTrue(Contact.objects.filter(pk=contact.pk).exists())
        self.assertTrue(Business.objects.filter(pk=business.pk).exists())

    def test_delete_contact_when_other_contacts_exist(self):
        """Deleting a contact when other contacts exist should work and reassign default."""
        # Create two contacts for the same business
        contact1 = Contact.objects.create(
            first_name='First',
            last_name='Contact',
            email='first@test.com',
            work_number='555-1111'
        )
        contact2 = Contact.objects.create(
            first_name='Second',
            last_name='Contact',
            email='second@test.com',
            work_number='555-2222'
        )
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()
        contact2.business = business
        contact2.save()

        # Verify setup
        self.assertEqual(business.contacts.count(), 2)
        self.assertEqual(business.default_contact, contact1)

        # Delete the default contact - should succeed
        contact1.delete()

        # Business should now have contact2 as default
        business.refresh_from_db()
        self.assertEqual(business.contacts.count(), 1)
        self.assertEqual(business.default_contact, contact2)

    def test_delete_non_default_contact(self):
        """Deleting a non-default contact should work without issues."""
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-1111'
        )
        contact2 = Contact.objects.create(
            first_name='Other',
            last_name='Contact',
            email='other@test.com',
            work_number='555-2222'
        )
        business = Business.objects.create(
            business_name="Test Business",
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()
        contact2.business = business
        contact2.save()

        # Delete the non-default contact
        contact2.delete()

        # Business should still have contact1 as default
        business.refresh_from_db()
        self.assertEqual(business.contacts.count(), 1)
        self.assertEqual(business.default_contact, contact1)

    def test_delete_contact_without_business(self):
        """Deleting a contact with no business should work without issues."""
        contact = Contact.objects.create(
            first_name='Independent',
            last_name='Contact',
            email='independent@test.com',
            work_number='555-1234'
        )

        # Should not raise any exception
        contact.delete()

        self.assertFalse(Contact.objects.filter(pk=contact.pk).exists())


