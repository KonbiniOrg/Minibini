from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Configuration, AccountingCategory
from apps.estimates.models import WorkTemplate, TaskTemplate


class WorkTemplateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_work_templates(self):
        response = self.client.get('/api/work-templates/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_work_template(self):
        template = WorkTemplate.objects.first()
        if template:
            response = self.client.get(f'/api/work-templates/{template.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_old_work_order_templates_route_gone(self):
        response = self.client.get('/api/work-order-templates/')
        self.assertEqual(response.status_code, 404)


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
        from apps.jobs.models import ServiceItem
        scheme = ServiceItem.objects.get(pk=1)  # from fixture
        response = self.client.post('/api/task-templates/', {
            'template_name': 'API Test Template',
            'description': 'Created via API',
            'units': 'hours',
            'service_item': scheme.pk,
            'default_billable_qty': '1.00',
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

    def test_list_accounting_categories(self):
        response = self.client.get('/api/accounting-categories/')
        self.assertEqual(response.status_code, 200)


class PercentageServiceTaskTemplateRejectionTest(BaseTestCase):
    """A ServiceItem with algorithm=PERCENTAGE must be rejected when assigning
    to a TaskTemplate — percentage services are document-level adjustments only."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        from apps.jobs.models import ServiceItem
        from apps.core.models import AccountingCategory
        ac = AccountingCategory.objects.create(code='TMP-PCT', name='TMP-PCT')
        self.rush = ServiceItem.objects.create(
            name='Rush TT', algorithm=ServiceItem.PERCENTAGE, rate='15',
            unit_label='%', accounting_category=ac,
        )

    def test_cannot_assign_percentage_service_to_task_template(self):
        resp = self.client.post('/api/task-templates/', {
            'template_name': 'Rush Template',
            'service_item': self.rush.pk,
            'default_billable_qty': '1.00',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
