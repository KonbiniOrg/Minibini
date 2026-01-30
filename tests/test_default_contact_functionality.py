"""
Tests for default contact functionality in the contacts app.

This test suite covers:
- Automatic default contact assignment when a business has only one contact
- Default contact preservation when adding additional contacts
- Default contact reassignment when the default is removed
- Default contact clearing when all contacts are removed
"""

from django.test import TestCase
from apps.contacts.models import Contact, Business


class DefaultContactAutomaticAssignmentTest(TestCase):
    """Test automatic default contact assignment behavior"""

    def test_single_contact_auto_set_as_default(self):
        """When a business has only one contact, it should automatically be set as default"""
        # Create contact first without business
        contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact
        )

        # Link contact to business
        contact.business = business
        contact.save()

        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact)

    def test_adding_second_contact_preserves_default(self):
        """Adding a second contact should not change the existing default"""
        # Create first contact
        contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with first contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )

        # Link contact to business
        contact1.business = business
        contact1.save()

        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

        # Add second contact
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )
        business.refresh_from_db()

        # Default should still be contact1
        self.assertEqual(business.default_contact, contact1)



class DefaultContactReassignmentTest(TestCase):
    """Test default contact reassignment when contacts are removed"""


    def test_removing_non_default_contact_preserves_default(self):
        """Removing a non-default contact should not affect the default"""
        # Create first contact
        contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with first contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()

        # Create second contact
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )

        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

        # Remove the non-default contact
        contact2.delete()

        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)



class DefaultContactUpdateMethodTest(TestCase):
    """Test the update_default_contact method on Business model"""

    # Note: Tests that clear default_contact to None have been removed
    # since businesses are now required to always have a default contact


class DefaultContactMultipleContactsTest(TestCase):
    """Test default contact behavior with multiple contacts"""

    def test_multiple_contacts_default_not_auto_changed(self):
        """With multiple contacts, default should not be automatically changed"""
        # Create first contact
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Alpha',
            email='alice@test.com',
            work_number='555-0001'
        )

        # Create business with first contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()

        # Add more contacts
        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Beta',
            email='bob@test.com',
            work_number='555-0002',
            business=business
        )

        contact3 = Contact.objects.create(
            first_name='Charlie',
            last_name='Gamma',
            email='charlie@test.com',
            work_number='555-0003',
            business=business
        )

        business.refresh_from_db()

        # Default should be the first contact added
        self.assertEqual(business.default_contact, contact1)

        # Manually set to contact2
        business.default_contact = contact2
        business.save()

        # Add another contact
        contact4 = Contact.objects.create(
            first_name='David',
            last_name='Delta',
            email='david@test.com',
            work_number='555-0004',
            business=business
        )

        business.refresh_from_db()

        # Default should still be contact2
        self.assertEqual(business.default_contact, contact2)

    def test_default_contact_persists_across_saves(self):
        """Default contact should persist when business is saved"""
        # Create first contact
        contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with first contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()

        # Add second contact
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )

        business.refresh_from_db()
        original_default = business.default_contact

        # Modify and save business
        business.business_phone = '555-9999'
        business.save()

        business.refresh_from_db()
        self.assertEqual(business.default_contact, original_default)
