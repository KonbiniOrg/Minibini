from rest_framework.test import APIClient
from django.contrib.auth.models import Permission

from apps.core.models import User, Configuration
from tests.base import BaseTestCase


def _admin():
    user = User.objects.create_user(username='cfg_admin_activity', password='pass')
    perm = Permission.objects.get(codename='can_manage_config')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


class ActivityRecentDaysSettingsTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_valid_int_persists(self):
        response = self.client.patch('/api/settings/', {
            'activity_recent_days': '7',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Configuration.objects.get(key='activity_recent_days').value, '7',
        )

    def test_non_int_rejected(self):
        response = self.client.patch('/api/settings/', {
            'activity_recent_days': 'abc',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('activity_recent_days', response.json())
        self.assertFalse(
            Configuration.objects.filter(key='activity_recent_days').exists(),
        )

    def test_less_than_one_rejected(self):
        response = self.client.patch('/api/settings/', {
            'activity_recent_days': '0',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('activity_recent_days', response.json())
