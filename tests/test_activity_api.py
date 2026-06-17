from rest_framework.test import APIClient

from apps.core.models import User, Configuration
from tests.base import BaseTestCase


class ActivityAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '5'},
        )

    def test_unauthenticated_blocked(self):
        response = self.client.get('/api/activity/')
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_returns_top_level_keys(self):
        user = User.objects.get(username='admin')
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/activity/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ('recent_days', 'on_shift', 'completed_bleps',
                    'job_events', 'po_events', 'invoice_events'):
            self.assertIn(key, data)
        self.assertEqual(data['recent_days'], 5)
