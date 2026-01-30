"""
Tests for add_business view ensuring default contact is properly set.

This test suite covers the new implementation where:
- The first contact is created before the business
- The business is created with that contact as the default
- The contact is then linked back to the business
"""

from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business


class AddBusinessWithDefaultContactTest(TestCase):
    """Test the add_business view creates businesses with proper default contacts"""

    def setUp(self):
        self.client = Client()
        self.url = reverse('contacts:add_business')

    def test_create_business_with_single_contact_sets_default(self):
        """Creating a business with one contact should automatically set it as default"""
        response = self.client.post(self.url, {
            'business_name': 'Test Business',
            'business_phone': '555-1000',
            'business_address': '123 Test St',
            'tax_exemption_number': 'TAX123',
            'website': 'https://test.com',
            'contact_count': '1',
            'contact_0_first_name': 'John',
            'contact_0_middle_initial': 'A',
            'contact_0_last_name': 'Doe',
            'contact_0_email': 'john@test.com',
            'contact_0_work_number': '555-0001',
            'contact_0_mobile_number': '',
            'contact_0_home_number': '',
            'contact_0_address': '123 Test St',
            'contact_0_city': 'Test City',
            'contact_0_postal_code': '12345',
        })

        # Should redirect after successful creation
        self.assertEqual(response.status_code, 302)

        # Verify business was created
        business = Business.objects.get(business_name='Test Business')
        self.assertIsNotNone(business)

        # Verify contact was created
        contact = Contact.objects.get(email='john@test.com')
        self.assertIsNotNone(contact)

        # Verify contact is linked to business
        self.assertEqual(contact.business, business)

        # Verify contact is set as default
        self.assertEqual(business.default_contact, contact)

    def test_create_business_with_multiple_contacts_first_is_default(self):
        """Creating a business with multiple contacts should set first contact as default"""
        response = self.client.post(self.url, {
            'business_name': 'Multi Contact Business',
            'business_phone': '555-2000',
            'business_address': '456 Multi St',
            'contact_count': '3',
            'contact_0_first_name': 'Alice',
            'contact_0_last_name': 'Anderson',
            'contact_0_email': 'alice@test.com',
            'contact_0_work_number': '555-0001',
            'contact_1_first_name': 'Bob',
            'contact_1_last_name': 'Brown',
            'contact_1_email': 'bob@test.com',
            'contact_1_mobile_number': '555-0002',
            'contact_2_first_name': 'Carol',
            'contact_2_last_name': 'Clark',
            'contact_2_email': 'carol@test.com',
            'contact_2_home_number': '555-0003',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Multi Contact Business')
        first_contact = Contact.objects.get(email='alice@test.com')
        second_contact = Contact.objects.get(email='bob@test.com')
        third_contact = Contact.objects.get(email='carol@test.com')

        # All contacts should be linked to business
        self.assertEqual(first_contact.business, business)
        self.assertEqual(second_contact.business, business)
        self.assertEqual(third_contact.business, business)

        # First contact should be default
        self.assertEqual(business.default_contact, first_contact)

    def test_business_requires_at_least_one_contact(self):
        """Creating a business without contacts should show error"""
        response = self.client.post(self.url, {
            'business_name': 'No Contact Business',
            'business_phone': '555-3000',
            'contact_count': '0',
        })

        # Should stay on the same page with error
        self.assertEqual(response.status_code, 200)

        # No business should be created
        self.assertFalse(Business.objects.filter(business_name='No Contact Business').exists())

    def test_business_creation_validates_contact_email(self):
        """Business creation should fail if any contact is missing email"""
        response = self.client.post(self.url, {
            'business_name': 'Invalid Email Business',
            'business_phone': '555-4000',
            'contact_count': '1',
            'contact_0_first_name': 'John',
            'contact_0_last_name': 'Doe',
            'contact_0_email': '',  # Missing email
            'contact_0_work_number': '555-0001',
        })

        # Should stay on the same page with error
        self.assertEqual(response.status_code, 200)

        # No business should be created
        self.assertFalse(Business.objects.filter(business_name='Invalid Email Business').exists())

        # No contact should be created
        self.assertEqual(Contact.objects.count(), 0)

    def test_business_creation_validates_contact_phone(self):
        """Business creation should fail if contact has no phone numbers"""
        response = self.client.post(self.url, {
            'business_name': 'No Phone Business',
            'business_phone': '555-5000',
            'contact_count': '1',
            'contact_0_first_name': 'John',
            'contact_0_last_name': 'Doe',
            'contact_0_email': 'john@test.com',
            'contact_0_work_number': '',
            'contact_0_mobile_number': '',
            'contact_0_home_number': '',
        })

        # Should stay on the same page with error
        self.assertEqual(response.status_code, 200)

        # No business should be created
        self.assertFalse(Business.objects.filter(business_name='No Phone Business').exists())

        # No contact should be created
        self.assertEqual(Contact.objects.count(), 0)

    def test_business_creation_with_partial_contact_data(self):
        """Only contacts with first and last name should be created"""
        response = self.client.post(self.url, {
            'business_name': 'Partial Contact Business',
            'business_phone': '555-6000',
            'contact_count': '3',
            'contact_0_first_name': 'Alice',
            'contact_0_last_name': 'Anderson',
            'contact_0_email': 'alice@test.com',
            'contact_0_work_number': '555-0001',
            'contact_1_first_name': '',  # Empty first name
            'contact_1_last_name': 'Brown',
            'contact_1_email': 'bob@test.com',
            'contact_1_mobile_number': '555-0002',
            'contact_2_first_name': 'Carol',
            'contact_2_last_name': '',  # Empty last name
            'contact_2_email': 'carol@test.com',
            'contact_2_home_number': '555-0003',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Partial Contact Business')

        # Only first contact should be created
        self.assertEqual(Contact.objects.count(), 1)
        contact = Contact.objects.get(email='alice@test.com')
        self.assertEqual(contact.business, business)
        self.assertEqual(business.default_contact, contact)

    def test_business_default_contact_not_null(self):
        """Business default_contact should never be null after successful creation"""
        response = self.client.post(self.url, {
            'business_name': 'Default Not Null Business',
            'business_phone': '555-7000',
            'contact_count': '1',
            'contact_0_first_name': 'Test',
            'contact_0_last_name': 'User',
            'contact_0_email': 'test@test.com',
            'contact_0_work_number': '555-0001',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Default Not Null Business')

        # default_contact should not be null
        self.assertIsNotNone(business.default_contact)

        # default_contact should be a valid Contact instance
        self.assertIsInstance(business.default_contact, Contact)

    def test_first_contact_linked_to_business_after_creation(self):
        """The first contact should be properly linked to business after creation"""
        response = self.client.post(self.url, {
            'business_name': 'Link Test Business',
            'business_phone': '555-8000',
            'contact_count': '1',
            'contact_0_first_name': 'Link',
            'contact_0_last_name': 'Test',
            'contact_0_email': 'link@test.com',
            'contact_0_work_number': '555-0001',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Link Test Business')
        contact = Contact.objects.get(email='link@test.com')

        # Verify bidirectional relationship
        self.assertEqual(contact.business, business)
        self.assertEqual(business.default_contact, contact)
        self.assertIn(contact, business.contacts.all())


class BusinessDefaultContactIntegrityTest(TestCase):
    """Test data integrity of default contacts during business operations"""

    def test_business_default_contact_points_to_own_contact(self):
        """Business default_contact should always point to one of its own contacts"""
        # Create business with contact
        client = Client()
        url = reverse('contacts:add_business')

        response = client.post(url, {
            'business_name': 'Integrity Test Business',
            'contact_count': '2',
            'contact_0_first_name': 'First',
            'contact_0_last_name': 'Contact',
            'contact_0_email': 'first@test.com',
            'contact_0_work_number': '555-0001',
            'contact_1_first_name': 'Second',
            'contact_1_last_name': 'Contact',
            'contact_1_email': 'second@test.com',
            'contact_1_mobile_number': '555-0002',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Integrity Test Business')

        # Default contact should belong to this business
        self.assertEqual(business.default_contact.business, business)

        # Default contact should be in business.contacts
        self.assertIn(business.default_contact, business.contacts.all())

    def test_contact_business_reference_matches_default_contact_business(self):
        """Contact's business field should match the business it's default for"""
        client = Client()
        url = reverse('contacts:add_business')

        response = client.post(url, {
            'business_name': 'Reference Match Business',
            'contact_count': '1',
            'contact_0_first_name': 'Match',
            'contact_0_last_name': 'Test',
            'contact_0_email': 'match@test.com',
            'contact_0_work_number': '555-0001',
        })

        self.assertEqual(response.status_code, 302)

        business = Business.objects.get(business_name='Reference Match Business')
        default_contact = business.default_contact

        # Both should point to the same business
        self.assertEqual(default_contact.business, business)
        self.assertEqual(business.default_contact.business, business)
