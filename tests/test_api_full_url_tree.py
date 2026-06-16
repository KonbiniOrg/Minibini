from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class FullURLTreeTest(BaseTestCase):
    """Verify every documented endpoint returns a non-404 response."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_all_list_endpoints_resolve(self):
        """All list endpoints should return 200 or 501 (not 404)."""
        endpoints = [
            '/api/',
            '/api/auth/me/',
            '/api/jobs/',
            '/api/contacts/',
            '/api/businesses/',
            '/api/payment-terms/',
            '/api/est-worksheets/',
            '/api/estimates/',
            '/api/invoices/',
            '/api/purchase-orders/',
            '/api/bills/',
            '/api/inventory/',
            '/api/emails/',
            '/api/work-templates/',
            '/api/task-templates/',
            '/api/accounting-categories/',
            '/api/settings/',
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertNotEqual(
                response.status_code, 404,
                f'{url} returned 404 — endpoint not wired'
            )

    def test_all_stub_endpoints_return_501(self):
        """Stub endpoints should return 501."""
        stubs = [
            ('POST', '/api/auth/refresh/'),
            # /api/shifts/clock-in/ and clock-out/ are now implemented (shifts feature).
            ('GET', '/api/time-tracking/status/'),
            ('GET', '/api/time-tracking/active/'),
            ('POST', '/api/emails/send/'),
        ]
        for method, url in stubs:
            if method == 'GET':
                response = self.client.get(url)
            else:
                response = self.client.post(url, {}, format='json')
            self.assertEqual(
                response.status_code, 501,
                f'{method} {url} should return 501, got {response.status_code}'
            )
