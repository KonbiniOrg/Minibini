from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact, Business, PaymentTerms


class ContactAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_contacts(self):
        response = self.client.get('/api/contacts/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_contact(self):
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Contact',
            'email': 'new@example.com',
            'mobile_number': '555-000-0000',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_contact(self):
        contact = Contact.objects.first()
        response = self.client.get(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_update_contact(self):
        contact = Contact.objects.first()
        response = self.client.patch(f'/api/contacts/{contact.pk}/', {
            'first_name': 'Updated',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['first_name'], 'Updated')

    def test_delete_contact_without_confirm_returns_impact(self):
        contact = Contact.objects.first()
        response = self.client.delete(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirm_required', response.data)

    def test_delete_contact_with_confirm(self):
        contact = Contact.objects.create(
            first_name='Delete', last_name='Me',
            email='delete@example.com', mobile_number='555-999-9999',
        )
        response = self.client.delete(f'/api/contacts/{contact.pk}/?confirm=true')
        self.assertEqual(response.status_code, 204)


class BusinessAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_businesses(self):
        response = self.client.get('/api/businesses/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_business(self):
        business = Business.objects.first()
        response = self.client.get(f'/api/businesses/{business.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_set_default_contact(self):
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if contact:
            response = self.client.post(
                f'/api/businesses/{business.pk}/set-default-contact/',
                {'contact_id': contact.pk}, format='json'
            )
            self.assertEqual(response.status_code, 200)


class PaymentTermsAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_payment_terms(self):
        response = self.client.get('/api/payment-terms/')
        self.assertEqual(response.status_code, 200)
