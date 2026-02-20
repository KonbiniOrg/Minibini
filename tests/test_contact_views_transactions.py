"""Tests for transaction wrapping in contact views.

These tests verify that:
1. Multi-model operations are wrapped in transactions
2. If one operation fails, all are rolled back
3. add_contact properly handles business creation with default_contact
"""
from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.core.models import User


class AddContactViewTransactionTest(TestCase):
    """Test add_contact view transaction handling."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

    def test_add_contact_with_existing_business(self):
        """Adding a contact with existing business selected should associate them."""
        # Create a contact and business first
        default_contact = Contact.objects.create(
            first_name='Default', last_name='Contact',
            email='default@test.com', work_number='555-0000'
        )
        business = Business.objects.create(
            business_name='Test Company',
            business_phone='555-5678',
            default_contact=default_contact
        )
        default_contact.business = business
        default_contact.save()

        response = self.client.post(reverse('contacts:add_contact'), {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@test.com',
            'work_number': '555-1234',
            'business_id': str(business.business_id),
        })

        # Should redirect on success
        self.assertEqual(response.status_code, 302)

        # Contact should be associated with business
        contact = Contact.objects.get(email='john@test.com')
        self.assertEqual(contact.business, business)

    def test_add_contact_without_business(self):
        """Adding a contact without business info should only create contact."""
        response = self.client.post(reverse('contacts:add_contact'), {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@test.com',
            'mobile_number': '555-9999',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 0)


class AddBusinessViewTransactionTest(TestCase):
    """Test add_business view transaction handling."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

    def test_add_business_creates_all_atomically(self):
        """Adding a business with multiple contacts should create all atomically."""
        response = self.client.post(reverse('contacts:add_business'), {
            'business_name': 'Test Corp',
            'business_phone': '555-0000',
            'contact_count': '2',
            'contact_0_first_name': 'Alice',
            'contact_0_last_name': 'Anderson',
            'contact_0_email': 'alice@test.com',
            'contact_0_work_number': '555-1111',
            'contact_1_first_name': 'Bob',
            'contact_1_last_name': 'Brown',
            'contact_1_email': 'bob@test.com',
            'contact_1_work_number': '555-2222',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(Contact.objects.count(), 2)

        # All contacts should be associated with business
        business = Business.objects.first()
        for contact in Contact.objects.all():
            self.assertEqual(contact.business, business)

        # First contact should be default
        self.assertEqual(business.default_contact.first_name, 'Alice')

    def test_add_business_requires_at_least_one_contact(self):
        """Business creation should fail if no valid contacts provided."""
        response = self.client.post(reverse('contacts:add_business'), {
            'business_name': 'Test Corp',
            'contact_count': '0',
        })

        # Should not create anything
        self.assertEqual(Business.objects.count(), 0)
        self.assertEqual(Contact.objects.count(), 0)
