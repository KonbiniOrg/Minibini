"""Envelope endpoints: self-service (PUT /api/auth/me/schedule-envelope/)
and schedule planning for managers (PUT /api/users/{id}/schedule-envelope/,
gated can_manage_time OR can_manage_config)."""

from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User


def _envelope(**overrides):
    data = {k: [['08:00', '17:00']] for k in ('mon', 'tue', 'wed', 'thu', 'fri')}
    data['sat'] = []
    data['sun'] = []
    data.update(overrides)
    return data


def _grant(user, codename):
    perm = Permission.objects.get(
        codename=codename, content_type__app_label='core')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


class MeScheduleEnvelopeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='env_self', password='x')
        self.client.force_authenticate(user=self.user)

    def test_put_valid_envelope_persists(self):
        envelope = _envelope(mon=[['07:00', '15:00']])
        response = self.client.put(
            '/api/auth/me/schedule-envelope/',
            {'schedule_envelope': envelope}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['schedule_envelope'], envelope)
        self.user.refresh_from_db()
        self.assertEqual(self.user.schedule_envelope, envelope)

    def test_put_null_resets_to_shop_default(self):
        self.user.schedule_envelope = _envelope()
        self.user.save()
        response = self.client.put(
            '/api/auth/me/schedule-envelope/',
            {'schedule_envelope': None}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.schedule_envelope)

    def test_put_invalid_envelope_400s_in_contract_shape(self):
        response = self.client.put(
            '/api/auth/me/schedule-envelope/',
            {'schedule_envelope': _envelope(
                mon=[['08:00', '12:00'], ['11:00', '17:00']])},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_envelope', response.json())

    def test_anonymous_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.put(
            '/api/auth/me/schedule-envelope/',
            {'schedule_envelope': None}, format='json')
        self.assertIn(response.status_code, (401, 403))


class AdminScheduleEnvelopeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.target = User.objects.create_user(username='env_target', password='x')

    def _url(self):
        return f'/api/users/{self.target.pk}/schedule-envelope/'

    def test_time_manager_can_set_envelope(self):
        manager = _grant(
            User.objects.create_user(username='env_timemgr', password='x'),
            'can_manage_time')
        self.client.force_authenticate(user=manager)
        envelope = _envelope(sat=[['09:00', '13:00']])
        response = self.client.put(
            self._url(), {'schedule_envelope': envelope}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.target.refresh_from_db()
        self.assertEqual(self.target.schedule_envelope, envelope)

    def test_config_manager_can_set_envelope(self):
        manager = _grant(
            User.objects.create_user(username='env_cfgmgr', password='x'),
            'can_manage_config')
        self.client.force_authenticate(user=manager)
        response = self.client.put(
            self._url(), {'schedule_envelope': None}, format='json')
        self.assertEqual(response.status_code, 200, response.content)

    def test_plain_user_forbidden(self):
        nobody = User.objects.create_user(username='env_nobody', password='x')
        self.client.force_authenticate(user=nobody)
        response = self.client.put(
            self._url(), {'schedule_envelope': None}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_time_manager_cannot_touch_other_admin_routes(self):
        """The wider gate applies ONLY to the envelope action."""
        manager = _grant(
            User.objects.create_user(username='env_timemgr2', password='x'),
            'can_manage_time')
        self.client.force_authenticate(user=manager)
        response = self.client.get(f'/api/users/{self.target.pk}/')
        self.assertEqual(response.status_code, 403)

    def test_invalid_envelope_rejected(self):
        manager = _grant(
            User.objects.create_user(username='env_timemgr3', password='x'),
            'can_manage_time')
        self.client.force_authenticate(user=manager)
        response = self.client.put(
            self._url(), {'schedule_envelope': {'mon': 'garbage'}},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_envelope', response.json())

    def test_detail_payload_carries_envelope(self):
        admin = _grant(
            User.objects.create_user(username='env_admin', password='x'),
            'can_manage_config')
        self.target.schedule_envelope = _envelope()
        self.target.save()
        self.client.force_authenticate(user=admin)
        response = self.client.get(f'/api/users/{self.target.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['schedule_envelope'], _envelope())
