# tests/test_units_serializer_validation.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job


class TaskSerializerUnitsValidationTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # Use the admin superuser from fixtures
        self.user = User.objects.filter(is_superuser=True).first()
        self.client.force_authenticate(user=self.user)

    # NOTE: Task serializer no longer carries a `units` field — billing identity
    # (units, rate, accounting category) lives on ServicePrice via TaskCharge after
    # the rate-scheme-billing-identity migration. Unit validation for Tasks is
    # therefore not tested here. Unit validation for TaskTemplate (which still
    # has a `units` field on the templates side) remains below.

    def test_task_template_serializer_rejects_invalid_unit(self):
        response = self.client.post(
            '/api/task-templates/',
            {'template_name': 'Test', 'units': 'invalid_xyz'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
