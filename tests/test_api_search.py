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
