"""
Tests for validate_and_fix_default_contact functionality.

This test suite covers the validate_and_fix_default_contact method which ensures:
- The default contact exists within the business's contacts
- If invalid, it's automatically set to the contact with the lowest primary key
"""

from django.test import TestCase
from apps.contacts.models import Contact, Business


class ValidateAndFixDefaultContactTest(TestCase):
    """Test the validate_and_fix_default_contact method"""

    def test_valid_default_contact_unchanged(self):
        """When default contact is valid, it should not change"""
        # Create first contact
        contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with contact1 as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()

        # Add another contact
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=business
        )

        # Call validate_and_fix
        business.validate_and_fix_default_contact()

        # Default should still be contact1
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

    def test_invalid_default_contact_fixed_to_lowest_pk(self):
        """When default contact is invalid, should set to lowest PK contact"""
        # Create contacts for business 1
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Anderson',
            email='alice@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Brown',
            email='bob@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Carol',
            last_name='Clark',
            email='carol@test.com',
            work_number='555-0003'
        )

        # Create business 1 with contact1 as default
        business1 = Business.objects.create(
            business_name='Business 1',
            default_contact=contact1
        )
        contact1.business = business1
        contact1.save()
        contact2.business = business1
        contact2.save()

        # Create business 2 with contact3 as default
        business2 = Business.objects.create(
            business_name='Business 2',
            default_contact=contact3
        )
        contact3.business = business2
        contact3.save()

        # Manually set business1's default to contact3 (invalid - belongs to business2)
        business1.default_contact = contact3
        business1.save(update_fields=['default_contact'])

        # Call validate_and_fix
        business1.validate_and_fix_default_contact()

        # Default should now be contact1 (lowest PK among business1's contacts)
        business1.refresh_from_db()
        self.assertEqual(business1.default_contact, contact1)

    def test_invalid_default_auto_fixed_when_contact_saved(self):
        """When a contact is saved, invalid defaults should be auto-fixed"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002'
        )
        contact_other = Contact.objects.create(
            first_name='Other',
            last_name='Person',
            email='other@test.com',
            work_number='555-0099'
        )

        # Create business with contact_other as default (will be invalid when we move contacts)
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact_other
        )
        contact1.business = business
        contact1.save()
        contact2.business = business
        contact2.save()

        # Now contact_other is not in business's contacts, but default points to it
        # When we call validate_and_fix, it should fix to contact1 (lowest PK)
        business.validate_and_fix_default_contact()

        # Default should be contact1 (lowest PK among actual contacts)
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

    def test_no_contacts_no_change(self):
        """When business has no contacts, function should not crash"""
        # Create contact
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
        contact.business = business
        contact.save()

        # Remove all contacts
        contact.business = None
        contact.save()

        # Call validate_and_fix (should not crash)
        business.validate_and_fix_default_contact()

        # Business should still exist
        self.assertTrue(Business.objects.filter(business_id=business.business_id).exists())

    def test_lowest_pk_selected_among_multiple_contacts(self):
        """Should select contact with lowest PK when fixing invalid default"""
        # Create contacts in specific order to ensure PK order
        contact1 = Contact.objects.create(
            first_name='First',
            last_name='Contact',
            email='first@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Second',
            last_name='Contact',
            email='second@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Third',
            last_name='Contact',
            email='third@test.com',
            work_number='555-0003'
        )
        contact_invalid = Contact.objects.create(
            first_name='Invalid',
            last_name='Default',
            email='invalid@test.com',
            work_number='555-0099'
        )

        # Create business with contact_invalid as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact_invalid
        )

        # Add contacts 1, 2, 3 to business (but not contact_invalid)
        contact1.business = business
        contact1.save()
        contact2.business = business
        contact2.save()
        contact3.business = business
        contact3.save()

        # At this point, default (contact_invalid) is not in business's contacts
        # When saving contact3, validate_and_fix is triggered
        # It should set default to contact1 (lowest PK)
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)
        self.assertLess(contact1.contact_id, contact2.contact_id)
        self.assertLess(contact1.contact_id, contact3.contact_id)


class AutomaticDefaultContactFixingTest(TestCase):
    """Test that validate_and_fix_default_contact is called automatically"""

    def test_moving_contact_triggers_validate_and_fix(self):
        """Moving a contact to a business should trigger validate_and_fix"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Anderson',
            email='alice@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Brown',
            email='bob@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Carol',
            last_name='Clark',
            email='carol@test.com',
            work_number='555-0003'
        )

        # Create business1 with contact1 and contact2
        business1 = Business.objects.create(
            business_name='Business 1',
            default_contact=contact1
        )
        contact1.business = business1
        contact1.save()
        contact2.business = business1
        contact2.save()

        # Create business2 with contact3
        business2 = Business.objects.create(
            business_name='Business 2',
            default_contact=contact3
        )
        contact3.business = business2
        contact3.save()

        # Manually set business1's default to contact3 (invalid)
        business1.default_contact = contact3
        business1.save(update_fields=['default_contact'])

        # Move contact1 to another business (this should trigger validate_and_fix on business1)
        contact1.business = business2
        contact1.save()

        # Business1's default should now be contact2 (lowest PK remaining)
        business1.refresh_from_db()
        self.assertEqual(business1.default_contact, contact2)

    def test_delete_default_contact_auto_reassigns(self):
        """Deleting the default contact when other contacts exist should auto-reassign."""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Alice',
            last_name='Anderson',
            email='alice@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Bob',
            last_name='Brown',
            email='bob@test.com',
            work_number='555-0002'
        )

        # Create business with contact1 as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact1
        )
        contact1.business = business
        contact1.save()
        contact2.business = business
        contact2.save()

        # Deleting the default contact when other contacts exist should succeed
        # The default_contact should auto-reassign to another contact
        contact1.delete()

        # Verify deletion worked
        self.assertFalse(Contact.objects.filter(contact_id=contact1.contact_id).exists())

        # Business should now have contact2 as default (auto-reassigned)
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact2)
