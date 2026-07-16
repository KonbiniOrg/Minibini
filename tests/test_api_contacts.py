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

    def test_search_matches_business_name(self):
        match = Contact.objects.create(first_name='Pat', last_name='Quinn', email='pat.quinn@example.com')
        biz = Business.objects.create(
            business_name='Zylotech Industries', default_contact=match)
        match.business = biz
        match.save()
        other = Contact.objects.create(first_name='Sam', last_name='Reed', email='sam.reed@example.com')
        response = self.client.get('/api/contacts/?search=Zylotech')
        self.assertEqual(response.status_code, 200)
        ids = [c['contact_id'] for c in response.data['results']]
        self.assertIn(match.contact_id, ids)
        self.assertNotIn(other.contact_id, ids)

    def test_create_contact(self):
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Contact',
            'email': 'new@example.com',
            'mobile_number': '555-000-0000',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_contact_with_business_id_persists_association(self):
        dc = Contact.objects.create(first_name='DC', last_name='')
        biz = Business.objects.create(business_name='Acme Steel', default_contact=dc)
        response = self.client.post('/api/contacts/', {
            'first_name': 'Linked',
            'last_name': 'Contact',
            'email': 'linked@example.com',
            'mobile_number': '555-111-2222',
            'business_id': biz.business_id,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        created = Contact.objects.get(contact_id=response.data['contact_id'])
        self.assertEqual(created.business_id, biz.business_id)

    def test_create_contact_with_duplicate_email_returns_409_with_existing_contact(self):
        existing = Contact.objects.create(
            first_name='Existing', last_name='Person',
            email='dupe@example.com', mobile_number='555-999-0000',
        )
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Person',
            'email': 'dupe@example.com',
            'mobile_number': '555-000-0000',
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_email')
        self.assertEqual(response.data['existing_contact']['contact_id'], existing.contact_id)
        self.assertFalse(Contact.objects.filter(email='new@example.com').exists())

    def test_create_contact_with_duplicate_email_case_insensitive(self):
        Contact.objects.create(
            first_name='Existing', last_name='Person',
            email='Dupe@Example.com', mobile_number='555-999-0000',
        )
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Person',
            'email': 'dupe@example.com',
            'mobile_number': '555-000-0000',
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_email')

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
        self.assertEqual(response.status_code, 200)


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

    def test_create_business_with_duplicate_name_returns_409_with_existing_business(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc@example.com', work_number='555-1234',
        )
        existing = Business.objects.create(business_name='Argon.AI', default_contact=dc)
        new_contact = Contact.objects.create(
            first_name='New', last_name='Contact',
            email='new-contact@example.com', mobile_number='555-000-0000',
        )
        response = self.client.post('/api/businesses/', {
            'business_name': 'Argon.AI',
            'default_contact_id': new_contact.contact_id,
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_business_name')
        self.assertEqual(response.data['existing_business']['business_id'], existing.business_id)
        new_contact.refresh_from_db()
        self.assertIsNone(new_contact.business)

    def test_create_business_with_duplicate_name_case_insensitive(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc2@example.com', work_number='555-1234',
        )
        Business.objects.create(business_name='Argon.AI', default_contact=dc)
        new_contact = Contact.objects.create(
            first_name='New', last_name='Contact',
            email='new-contact2@example.com', mobile_number='555-000-0000',
        )
        response = self.client.post('/api/businesses/', {
            'business_name': 'argon.ai',
            'default_contact_id': new_contact.contact_id,
        }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'duplicate_business_name')

    def test_check_name_reports_existing_business(self):
        dc = Contact.objects.create(
            first_name='DC', last_name='', email='dc3@example.com', work_number='555-1234',
        )
        existing = Business.objects.create(business_name='Argon.AI', default_contact=dc)
        response = self.client.get('/api/businesses/check-name/?name=argon.ai')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['exists'])
        self.assertEqual(response.data['business']['business_id'], existing.business_id)

    def test_check_name_reports_no_conflict(self):
        response = self.client.get('/api/businesses/check-name/?name=Nobody Yet Inc')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['exists'])
        self.assertIsNone(response.data['business'])

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
