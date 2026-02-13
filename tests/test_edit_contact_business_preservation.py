"""Tests for contact editing business association preservation.

This test verifies that when editing a contact, if no radio button is selected
for business association, the existing business association is preserved.
"""
from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.core.models import User


class EditContactBusinessPreservationTest(TestCase):
    """Test that editing a contact without selecting a radio button preserves business association."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

        # Create a default contact for the business
        self.default_contact = Contact.objects.create(
            first_name='Default',
            last_name='Contact',
            email='default@test.com',
            work_number='555-0000'
        )

        # Create a business
        self.business = Business.objects.create(
            business_name='Test Company',
            business_phone='555-1234',
            default_contact=self.default_contact
        )

        # Associate the default contact with the business
        self.default_contact.business = self.business
        self.default_contact.save()

        # Create a contact associated with the business
        self.contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-5678',
            business=self.business
        )

    def test_edit_contact_without_radio_selection_preserves_business(self):
        """Editing a contact without selecting any radio button should preserve business association."""
        response = self.client.post(
            reverse('contacts:edit_contact', args=[self.contact.contact_id]),
            {
                'first_name': 'John',
                'last_name': 'Smith',  # Changed last name
                'email': 'john@test.com',
                'work_number': '555-5678',
                # Note: No business_selection_mode parameter (no radio button selected)
            }
        )

        # Should redirect on success
        self.assertEqual(response.status_code, 302)

        # Refresh contact from database
        self.contact.refresh_from_db()

        # Verify last name was updated
        self.assertEqual(self.contact.last_name, 'Smith')

        # Verify business association was preserved
        self.assertIsNotNone(self.contact.business)
        self.assertEqual(self.contact.business, self.business)

    def test_edit_contact_with_none_selection_removes_business(self):
        """Selecting 'No business association' radio button should remove business association."""
        response = self.client.post(
            reverse('contacts:edit_contact', args=[self.contact.contact_id]),
            {
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@test.com',
                'work_number': '555-5678',
                'business_selection_mode': 'none',  # Explicitly select "No business"
            }
        )

        # Should redirect on success
        self.assertEqual(response.status_code, 302)

        # Refresh contact from database
        self.contact.refresh_from_db()

        # Verify business association was removed
        self.assertIsNone(self.contact.business)

    def test_edit_contact_with_existing_selection_changes_business(self):
        """Selecting an existing business should change the business association."""
        # Create another business
        another_default_contact = Contact.objects.create(
            first_name='Another',
            last_name='Default',
            email='another@test.com',
            work_number='555-9999'
        )
        another_business = Business.objects.create(
            business_name='Another Company',
            business_phone='555-8888',
            default_contact=another_default_contact
        )
        another_default_contact.business = another_business
        another_default_contact.save()

        response = self.client.post(
            reverse('contacts:edit_contact', args=[self.contact.contact_id]),
            {
                'first_name': 'John',
                'last_name': 'Doe',
                'email': 'john@test.com',
                'work_number': '555-5678',
                'business_selection_mode': 'existing',
                'existing_business_id': str(another_business.business_id),
            }
        )

        # Should redirect on success
        self.assertEqual(response.status_code, 302)

        # Refresh contact from database
        self.contact.refresh_from_db()

        # Verify business association was changed
        self.assertEqual(self.contact.business, another_business)
