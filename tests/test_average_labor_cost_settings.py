"""Settings validation for average_labor_cost — must be a non-negative number
(dollars per hour), blank allowed (treated as 0). See
docs/designs/jobs-and-tasks.md §9.3.
"""
from rest_framework.test import APIClient
from django.contrib.auth.models import Permission

from tests.base import BaseTestCase
from apps.core.models import User, Configuration


def _admin():
    user = User.objects.create_user(username='alc_admin', password='pass')
    user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
    return User.objects.get(pk=user.pk)


class AverageLaborCostSettingsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_rejects_non_numeric(self):
        resp = self.client.patch(
            '/api/settings/', {'average_labor_cost': 'abc'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('average_labor_cost', resp.json())

    def test_rejects_negative(self):
        resp = self.client.patch(
            '/api/settings/', {'average_labor_cost': '-5'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('average_labor_cost', resp.json())

    def test_accepts_valid_decimal(self):
        resp = self.client.patch(
            '/api/settings/', {'average_labor_cost': '25.50'}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key='average_labor_cost').value, '25.50',
        )

    def test_accepts_blank_to_unset(self):
        resp = self.client.patch(
            '/api/settings/', {'average_labor_cost': ''}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            Configuration.objects.get(key='average_labor_cost').value, '',
        )
