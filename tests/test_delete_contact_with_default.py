"""
Tests for deleting contacts with default contact handling.

This test suite covers the delete contact functionality to ensure:
- Cannot delete the last contact of a business
- Auto-assigns remaining contact when deleting default with one other contact
- Prompts user to select new default when deleting default with multiple contacts
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business


class DeleteDefaultContactTest(TestCase):
    """Test deleting default contacts"""

    def setUp(self):
        self.client = Client()

    def test_cannot_delete_last_contact_of_business(self):
        """Cannot delete the only contact of a business"""
        # Create contact
        contact = Contact.objects.create(
            first_name='Only',
            last_name='Contact',
            email='only@test.com',
            work_number='555-0001'
        )

        # Create business with this contact as default
        business = Business.objects.create(
            business_name='Test Business',
            default_contact=contact
        )
        contact.business = business
        contact.save()

        # Try to delete the contact
        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url)

        # Should redirect with error
        self.assertEqual(response.status_code, 302)

        # Contact should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact.contact_id).exists())

        # Business should still exist with same default
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact)

    def test_auto_assign_when_deleting_default_with_one_other(self):
        """When deleting default contact with 1 other contact, auto-assign remaining as default"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Other',
            last_name='Contact',
            email='other@test.com',
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

        # Delete contact1 (default)
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url)

        # Should redirect to business detail
        self.assertEqual(response.status_code, 302)

        # Contact1 should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact1.contact_id).exists())

        # Contact2 should now be default
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact2)

    def test_prompt_user_when_deleting_default_with_multiple_others(self):
        """When deleting default with multiple other contacts, prompt user to select new default"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Contact',
            last_name='Two',
            email='two@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Contact',
            last_name='Three',
            email='three@test.com',
            work_number='555-0003'
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
        contact3.business = business
        contact3.save()

        # Try to delete contact1 (default) without selecting new default
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url)

        # Should render selection page (not redirect)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contacts/select_new_default_contact.html')

        # Contact1 should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact1.contact_id).exists())

        # Business default should still be contact1
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

    def test_delete_default_with_selected_new_default(self):
        """Successfully delete default contact when user selects new default"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Contact',
            last_name='Two',
            email='two@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Contact',
            last_name='Three',
            email='three@test.com',
            work_number='555-0003'
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
        contact3.business = business
        contact3.save()

        # Delete contact1 and select contact2 as new default
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url, {
            'new_default_contact': contact2.contact_id
        })

        # Should redirect to business detail
        self.assertEqual(response.status_code, 302)

        # Contact1 should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact1.contact_id).exists())

        # Contact2 should now be default
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact2)

    def test_delete_non_default_contact(self):
        """Can delete non-default contact without prompting"""
        # Create contacts
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Non',
            last_name='Default',
            email='non-default@test.com',
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

        # Delete contact2 (non-default)
        url = reverse('contacts:delete_contact', args=[contact2.contact_id])
        response = self.client.post(url)

        # Should redirect to business detail
        self.assertEqual(response.status_code, 302)

        # Contact2 should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact2.contact_id).exists())

        # Contact1 should still be default
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)

    def test_delete_contact_without_business(self):
        """Can delete contact that has no business association"""
        # Create contact without business
        contact = Contact.objects.create(
            first_name='Independent',
            last_name='Contact',
            email='independent@test.com',
            work_number='555-0001'
        )

        # Delete contact
        url = reverse('contacts:delete_contact', args=[contact.contact_id])
        response = self.client.post(url)

        # Should redirect to contact list
        self.assertEqual(response.status_code, 302)

        # Contact should be deleted
        self.assertFalse(Contact.objects.filter(contact_id=contact.contact_id).exists())

    def test_invalid_new_default_selection(self):
        """Selecting invalid contact as new default should show error"""
        # Create contacts for business 1 (need at least 3 for multiple selection)
        contact1 = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0001'
        )
        contact2 = Contact.objects.create(
            first_name='Contact',
            last_name='Two',
            email='two@test.com',
            work_number='555-0002'
        )
        contact3 = Contact.objects.create(
            first_name='Contact',
            last_name='Three',
            email='three@test.com',
            work_number='555-0003'
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
        contact3.business = business
        contact3.save()

        # Create another contact not in this business
        contact_other = Contact.objects.create(
            first_name='Other',
            last_name='Business',
            email='other@test.com',
            work_number='555-0099'
        )

        # Try to delete contact1 and select contact_other (invalid) as new default
        url = reverse('contacts:delete_contact', args=[contact1.contact_id])
        response = self.client.post(url, {
            'new_default_contact': contact_other.contact_id
        })

        # Should show selection page with error
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'contacts/select_new_default_contact.html')

        # Contact1 should still exist
        self.assertTrue(Contact.objects.filter(contact_id=contact1.contact_id).exists())

        # Business default should still be contact1
        business.refresh_from_db()
        self.assertEqual(business.default_contact, contact1)
