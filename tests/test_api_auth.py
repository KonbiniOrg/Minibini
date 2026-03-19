from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User


class AuthAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        # Set a known password for login tests
        self.user.set_password('testpass123')
        self.user.save()

    def test_login_success(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'admin',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'admin')

    def test_login_bad_credentials(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'admin',
            'password': 'wrong',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_logout(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/auth/logout/')
        self.assertEqual(response.status_code, 200)

    def test_me_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'admin')

    def test_me_unauthenticated(self):
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 403)

    def test_jwt_refresh_returns_501(self):
        response = self.client.post('/api/auth/refresh/')
        self.assertEqual(response.status_code, 501)
