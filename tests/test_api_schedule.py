from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class ScheduleAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def test_unauthenticated_blocked(self):
        response = self.client.get('/api/schedule/')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_returns_envelope(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ('now', 'horizon_start', 'horizon_end', 'horizon_days',
                    'day_shape', 'days', 'jobs', 'workers'):
            self.assertIn(key, data)

    def test_days_param_respected(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=2')
        self.assertEqual(response.json()['horizon_days'], 2)

    def test_days_param_clamped_high(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=99')
        self.assertEqual(response.json()['horizon_days'], 14)

    def test_days_param_clamped_low(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/schedule/?days=0')
        self.assertEqual(response.json()['horizon_days'], 1)
