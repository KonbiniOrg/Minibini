import json
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import Configuration, User


class UnitsListEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_get_units_list(self):
        response = self.client.get('/api/settings/units/')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertEqual(response.data[0], 'none')

    def test_get_units_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/settings/units/')
        self.assertEqual(response.status_code, 403)

    def test_get_units_falls_back_when_config_row_missing(self):
        """Absent units_list must return the built-in defaults, never 500."""
        from apps.core.units import DEFAULT_UNITS
        Configuration.objects.filter(key='units_list').delete()
        response = self.client.get('/api/settings/units/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, DEFAULT_UNITS)


class UnitsUpdateEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')  # superuser, has all perms
        self.worker = User.objects.get(username='johnq')  # regular user, no config perm

    def test_patch_units_list(self):
        self.client.force_authenticate(user=self.admin)
        new_list = ['none', 'hours', 'ea', 'custom_unit']
        response = self.client.patch('/api/settings/units/', new_list, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, new_list)
        config = Configuration.objects.get(key='units_list')
        self.assertEqual(json.loads(config.value), new_list)

    def test_patch_requires_none_first(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch('/api/settings/units/', ['hours', 'ea'], format='json')
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_empty_list(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch('/api/settings/units/', [], format='json')
        self.assertEqual(response.status_code, 400)

    def test_patch_rejects_duplicates(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch('/api/settings/units/', ['none', 'hours', 'hours'], format='json')
        self.assertEqual(response.status_code, 400)

    def test_patch_requires_can_manage_config(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch('/api/settings/units/', ['none', 'hours'], format='json')
        self.assertEqual(response.status_code, 403)
