"""
Tests for setting default contact via UI views.

This test suite covers:
- Setting default contact via checkbox on add business contact page
- Setting default contact via button on contact detail page
- View permissions and error handling
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business


class AddBusinessContactWithDefaultTest(TestCase):
    """Test adding a contact with the 'set as default' checkbox"""

    def setUp(self):
        self.client = Client()
        # Create initial contact for business
        initial_contact = Contact.objects.create(
            first_name='Initial',
            last_name='Setup',
            email='initial@setup.com',
            work_number='555-0000'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=initial_contact
        )
        initial_contact.business = self.business
        initial_contact.save()

    def test_add_contact_with_default_checkbox_checked(self):
        """Adding a contact with 'set as default' checked should set it as default"""
        url = reverse('contacts:add_business_contact', args=[self.business.business_id])

        # Verify initial setup contact is default
        self.business.refresh_from_db()
        initial_contact = Contact.objects.get(email='initial@setup.com')
        self.assertEqual(self.business.default_contact, initial_contact)

        # Add contact without default checkbox
        response = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'work_number': '555-0001',
        })

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Verify initial contact is still default
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, initial_contact)

        # Add contact with default checkbox checked
        response = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@test.com',
            'work_number': '555-0002',
            'set_as_default': 'true',
        })

        self.assertEqual(response.status_code, 302)

        # Verify new contact is now default
        self.business.refresh_from_db()
        contact2 = Contact.objects.get(email='jane@test.com')
        self.assertEqual(self.business.default_contact, contact2)

    def test_add_contact_without_default_checkbox(self):
        """Adding a contact without checkbox should not change existing default"""
        # Get the initial default contact from setUp
        self.business.refresh_from_db()
        initial_default = self.business.default_contact

        url = reverse('contacts:add_business_contact', args=[self.business.business_id])

        # Add contact without checking default
        response = self.client.post(url, {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@test.com',
            'work_number': '555-0002',
        })

        self.assertEqual(response.status_code, 302)

        # Verify initial contact is still default
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, initial_default)

    def test_add_contact_with_default_checkbox_changes_default(self):
        """Contact with default checkbox should replace existing default"""
        url = reverse('contacts:add_business_contact', args=[self.business.business_id])

        response = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'work_number': '555-0001',
            'set_as_default': 'true',
        })

        self.assertEqual(response.status_code, 302)

        self.business.refresh_from_db()
        new_contact = Contact.objects.get(email='john@test.com')
        self.assertEqual(self.business.default_contact, new_contact)

    def test_add_contact_with_validation_errors(self):
        """Validation errors should not create contact or set default"""
        url = reverse('contacts:add_business_contact', args=[self.business.business_id])

        # Get initial contact count and default
        initial_count = Contact.objects.count()
        initial_default = self.business.default_contact

        # Try to add contact without required email
        response = self.client.post(url, {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': '',  # Missing required field
            'work_number': '555-0001',
            'set_as_default': 'true',
        })

        # Should stay on the same page with error
        self.assertEqual(response.status_code, 200)

        # No new contact should be created
        self.assertEqual(Contact.objects.count(), initial_count)

        # Default should remain unchanged
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, initial_default)


class SetDefaultContactViewTest(TestCase):
    """Test the set_default_contact view"""

    def setUp(self):
        self.client = Client()

        # Create first contact
        self.contact1 = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with first contact as default
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact1
        )
        self.contact1.business = self.business
        self.contact1.save()

        # Create second contact
        self.contact2 = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

    def test_set_contact_as_default(self):
        """POST to set_default_contact should set the contact as default"""
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact1)

        url = reverse('contacts:set_default_contact', args=[self.contact2.contact_id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)  # Redirect

        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact2)

    def test_set_default_for_contact_without_business(self):
        """Setting default for contact without business should show error"""
        contact_no_business = Contact.objects.create(
            first_name='No',
            last_name='Business',
            email='no@business.com',
            work_number='555-0003'
        )

        url = reverse('contacts:set_default_contact', args=[contact_no_business.contact_id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)  # Redirect back

        # Should not have affected our business
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact1)

    def test_set_default_get_request_redirects(self):
        """GET request to set_default_contact should redirect"""
        url = reverse('contacts:set_default_contact', args=[self.contact2.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)  # Redirect

        # Default should not change
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact1)

    def test_set_already_default_contact(self):
        """Setting an already-default contact should work without error"""
        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact1)

        url = reverse('contacts:set_default_contact', args=[self.contact1.contact_id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)

        self.business.refresh_from_db()
        self.assertEqual(self.business.default_contact, self.contact1)

    def test_set_default_redirects_to_contact_detail(self):
        """After setting default, should redirect to contact detail page"""
        url = reverse('contacts:set_default_contact', args=[self.contact2.contact_id])
        response = self.client.post(url)

        expected_redirect = reverse('contacts:contact_detail', args=[self.contact2.contact_id])
        self.assertRedirects(response, expected_redirect)


class ContactDetailPageDefaultIndicatorTest(TestCase):
    """Test that contact detail page shows default contact indicator"""

    def setUp(self):
        self.client = Client()

        # Create default contact
        self.default_contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with default contact
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.default_contact
        )
        self.default_contact.business = self.business
        self.default_contact.save()

        # Create non-default contact
        self.non_default_contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

    def test_default_contact_shows_indicator(self):
        """Default contact detail page should show [DEFAULT CONTACT] indicator"""
        url = reverse('contacts:contact_detail', args=[self.default_contact.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '[DEFAULT CONTACT]')

    def test_non_default_contact_shows_set_default_button(self):
        """Non-default contact should show 'Set as Default Contact' button"""
        url = reverse('contacts:contact_detail', args=[self.non_default_contact.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Set as Default Contact')
        self.assertNotContains(response, '[DEFAULT CONTACT]')

    def test_default_contact_does_not_show_set_default_button(self):
        """Default contact should NOT show 'Set as Default Contact' button"""
        url = reverse('contacts:contact_detail', args=[self.default_contact.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # The button should not appear for the default contact
        # Check by looking for the form action (more reliable than button text)
        self.assertNotContains(
            response,
            f'action="{reverse("contacts:set_default_contact", args=[self.default_contact.contact_id])}"'
        )

    def test_contact_without_business_no_default_controls(self):
        """Contact without business should not show default-related controls"""
        contact_no_business = Contact.objects.create(
            first_name='No',
            last_name='Business',
            email='no@business.com',
            work_number='555-0003'
        )

        url = reverse('contacts:contact_detail', args=[contact_no_business.contact_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Set as Default Contact')
        self.assertNotContains(response, '[DEFAULT CONTACT]')


class BusinessDetailPageDefaultDisplayTest(TestCase):
    """Test that business detail page shows default contact information"""

    def setUp(self):
        self.client = Client()

        # Create default contact
        self.default_contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            work_number='555-0001'
        )

        # Create business with default contact
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.default_contact
        )
        self.default_contact.business = self.business
        self.default_contact.save()

        # Create other contact
        self.other_contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@test.com',
            work_number='555-0002',
            business=self.business
        )

    def test_business_detail_shows_default_contact(self):
        """Business detail page should display the default contact"""
        self.business.refresh_from_db()

        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Default Contact')
        self.assertContains(response, self.default_contact.name)

    def test_business_detail_highlights_default_in_contact_list(self):
        """Default contact should be highlighted in the contacts list"""
        url = reverse('contacts:business_detail', args=[self.business.business_id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Check for the [DEFAULT] badge in the contact list
        self.assertContains(response, '[DEFAULT]')
