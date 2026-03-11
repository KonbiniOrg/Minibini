from rest_framework.test import APIClient
from tests.base import BaseTestCase


class APIFoundationTest(BaseTestCase):
    """Test that the API root is accessible and DRF is configured."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_api_root_returns_200(self):
        """The API root URL should return 200."""
        response = self.client.get('/api/')
        self.assertEqual(response.status_code, 200)

    def test_api_requires_authentication(self):
        """Unauthenticated requests should return 403."""
        client = APIClient()
        response = client.get('/api/')
        self.assertEqual(response.status_code, 403)
