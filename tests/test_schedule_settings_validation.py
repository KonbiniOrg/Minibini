from rest_framework.test import APIClient
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase
from apps.core.models import User, Configuration


def _admin():
    user = User.objects.create_user(username='cfg_admin', password='pass')
    perm = Permission.objects.get(codename='can_manage_config')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


class ScheduleSettingsValidationTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_admin())

    def test_workday_start_must_parse(self):
        response = self.client.patch('/api/settings/', {
            'schedule_workday_start': 'not-a-time',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('schedule_workday_start', response.json())

    def test_lunch_must_fit_in_workday(self):
        # First seed valid baseline values so cross-key checks have inputs.
        for k, v in {
            'schedule_workday_start': '08:00',
            'schedule_workday_end': '17:00',
            'schedule_lunch_start': '12:00',
            'schedule_lunch_length_minutes': '60',
            'schedule_task_buffer_minutes': '10',
            'schedule_horizon_days': '3',
        }.items():
            Configuration.objects.update_or_create(key=k, defaults={'value': v})

        response = self.client.patch('/api/settings/', {
            'schedule_lunch_start': '16:30',
            'schedule_lunch_length_minutes': '60',  # ends at 17:30 > 17:00 EOD
        }, format='json')
        self.assertEqual(response.status_code, 400)
        body = response.json()
        # At least one of the lunch-related errors fires.
        self.assertTrue(
            'schedule_lunch_length_minutes' in body
            or 'schedule_lunch_start' in body,
            body,
        )

    def test_valid_schedule_settings_accepted(self):
        response = self.client.patch('/api/settings/', {
            'schedule_workday_start': '07:00',
            'schedule_workday_end': '16:00',
            'schedule_lunch_start': '11:30',
            'schedule_lunch_length_minutes': '45',
            'schedule_task_buffer_minutes': '15',
            'schedule_horizon_days': '5',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Configuration.objects.get(key='schedule_workday_start').value,
            '07:00',
        )

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
