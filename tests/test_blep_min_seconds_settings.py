"""Settings validation for blep_minimum_seconds — must be a non-negative
integer. See docs/plans/2026-05-24-blep-handling-changes.md §2.
"""
from rest_framework.test import APIClient
from django.contrib.auth.models import Permission

from tests.base import BaseTestCase
from apps.core.models import User, Configuration


def _admin():
    user = User.objects.create_user(username='bms_admin', password='pass')
    user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
    return User.objects.get(pk=user.pk)


class BlepMinSecondsSettingsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_rejects_non_integer(self):
        resp = self.client.patch(
            '/api/settings/', {'blep_minimum_seconds': 'abc'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('blep_minimum_seconds', resp.json())

    def test_rejects_negative(self):
        resp = self.client.patch(
            '/api/settings/', {'blep_minimum_seconds': '-5'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('blep_minimum_seconds', resp.json())

    def test_accepts_valid(self):
        resp = self.client.patch(
            '/api/settings/', {'blep_minimum_seconds': '90'}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key='blep_minimum_seconds').value, '90',
        )
