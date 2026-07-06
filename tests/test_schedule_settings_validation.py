import json

from rest_framework.test import APIClient
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase
from apps.core.models import User, Configuration


def _admin():
    user = User.objects.create_user(username='cfg_admin', password='pass')
    perm = Permission.objects.get(codename='can_manage_config')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


def _envelope(**overrides):
    data = {k: [['08:00', '17:00']] for k in ('mon', 'tue', 'wed', 'thu', 'fri')}
    data['sat'] = []
    data['sun'] = []
    data.update(overrides)
    return data


class ScheduleSettingsValidationTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_envelope_must_be_valid_json(self):
        response = self.client.patch('/api/settings/', {
            'schedule_week_envelope': 'not-json{',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_week_envelope', response.json())

    def test_envelope_rejects_overlapping_intervals(self):
        response = self.client.patch('/api/settings/', {
            'schedule_week_envelope': _envelope(
                mon=[['08:00', '12:00'], ['11:00', '17:00']]),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_week_envelope', response.json())

    def test_envelope_rejects_end_before_start(self):
        response = self.client.patch('/api/settings/', {
            'schedule_week_envelope': _envelope(mon=[['17:00', '08:00']]),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_week_envelope', response.json())

    def test_valid_envelope_dict_accepted_and_stored_as_json(self):
        envelope = _envelope(mon=[['08:00', '12:00'], ['12:30', '17:00']], sat=[['09:00', '13:00']])
        response = self.client.patch('/api/settings/', {
            'schedule_week_envelope': envelope,
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        stored = Configuration.objects.get(key='schedule_week_envelope').value
        self.assertEqual(json.loads(stored), envelope)

    def test_valid_envelope_json_string_accepted(self):
        envelope = _envelope()
        response = self.client.patch('/api/settings/', {
            'schedule_week_envelope': json.dumps(envelope),
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        stored = Configuration.objects.get(key='schedule_week_envelope').value
        self.assertEqual(json.loads(stored), envelope)

    def test_buffer_must_be_non_negative_integer(self):
        response = self.client.patch('/api/settings/', {
            'schedule_task_buffer_minutes': '-1',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_task_buffer_minutes', response.json())

    def test_horizon_days_must_be_positive_integer(self):
        response = self.client.patch('/api/settings/', {
            'schedule_horizon_days': '0',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_horizon_days', response.json())

    def test_valid_schedule_settings_accepted(self):
        response = self.client.patch('/api/settings/', {
            'schedule_task_buffer_minutes': '15',
            'schedule_horizon_days': '5',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Configuration.objects.get(key='schedule_task_buffer_minutes').value,
            '15',
        )

    def test_workday_keys_are_gone_from_schedule_validation(self):
        """The retired schedule_workday_start/_end keys are now just unknown
        passthrough keys — no schedule validation fires on them."""
        response = self.client.patch('/api/settings/', {
            'schedule_workday_start': 'not-a-time',
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_non_schedule_keys_still_work(self):
        # Sanity: the validator doesn't reject unrelated keys.
        response = self.client.patch('/api/settings/', {
            'some_other_key': 'whatever',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(key='some_other_key').value,
            'whatever',
        )
