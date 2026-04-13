from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class StubEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_time_tracking_stubs(self):
        endpoints = [
            '/api/shifts/clock-in/',
            '/api/shifts/clock-out/',
            '/api/time-tracking/status/',
            '/api/time-tracking/active/',
        ]
        for url in endpoints:
            response = self.client.post(url, {}, format='json')
            self.assertEqual(response.status_code, 501, f'{url} should return 501')

    # test_expense_stubs removed — /api/expenses/ now has a real viewset
