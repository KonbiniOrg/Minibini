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

    def test_create_task_with_valid_unit(self):
        job = Job.objects.first()
        if not job:
            self.skipTest('No job in fixture')
        response = self.client.post(
            f'/api/jobs/{job.pk}/tasks/',
            {'name': 'Test Task', 'units': 'hours'},
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])

    def test_create_task_with_invalid_unit(self):
        job = Job.objects.first()
        if not job:
            self.skipTest('No job in fixture')
        response = self.client.post(
            f'/api/jobs/{job.pk}/tasks/',
            {'name': 'Test Task', 'units': 'invalid_xyz'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_task_template_serializer_rejects_invalid_unit(self):
        response = self.client.post(
            '/api/task-templates/',
            {'template_name': 'Test', 'units': 'invalid_xyz'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
