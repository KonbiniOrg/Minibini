from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Configuration, LineItemType
from apps.estimates.models import WorkOrderTemplate, TaskTemplate


class WorkOrderTemplateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_wo_templates(self):
        response = self.client.get('/api/work-order-templates/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_wo_template(self):
        template = WorkOrderTemplate.objects.first()
        if template:
            response = self.client.get(f'/api/work-order-templates/{template.pk}/')
            self.assertEqual(response.status_code, 200)


class TaskTemplateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_task_templates(self):
        response = self.client.get('/api/task-templates/')
        self.assertEqual(response.status_code, 200)

    def test_create_task_template(self):
        response = self.client.post('/api/task-templates/', {
            'template_name': 'API Test Template',
            'description': 'Created via API',
            'units': 'hr',
        }, format='json')
        self.assertEqual(response.status_code, 201)


class ConfigurationAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_get_settings(self):
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)

    def test_list_line_item_types(self):
        response = self.client.get('/api/accounting-categories/')
        self.assertEqual(response.status_code, 200)
