from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class SearchAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_search_returns_results(self):
        response = self.client.get('/api/search/', {'q': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_search_empty_query(self):
        response = self.client.get('/api/search/')
        self.assertEqual(response.status_code, 400)

    def test_search_with_category_filter(self):
        response = self.client.get('/api/search/', {'q': 'test', 'category': 'jobs'})
        self.assertEqual(response.status_code, 200)

    def test_global_search_matches_phone_ignoring_punctuation(self):
        from apps.contacts.models import Contact
        c = Contact.objects.create(first_name='Glo', last_name='Bal', email='glo@x.com',
                                   phones=[{'number': '(555) 321-7777', 'label': ''}])
        r = self.client.get('/api/search/', {'q': '555-321'})
        self.assertEqual(r.status_code, 200)
        contacts = r.data['results'].get('contacts', [])
        self.assertIn(c.pk, [x['contact_id'] for x in contacts])
        match = [x for x in contacts if x['contact_id'] == c.pk][0]
        self.assertEqual(match['phone'], '(555) 321-7777')
