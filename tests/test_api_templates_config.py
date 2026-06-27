from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Configuration, AccountingCategory
from apps.estimates.models import WorkTemplate, ServiceItem


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


class ServiceItemAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_list_service_items(self):
        response = self.client.get('/api/service-items/')
        self.assertEqual(response.status_code, 200)

    def test_create_service_item(self):
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.get(pk=1)  # from fixture
        response = self.client.post('/api/service-items/', {
            'template_name': 'API Test Template',
            'description': 'Created via API',
            'units': 'hours',
            'rate_scheme': scheme.pk,
            'default_billable_qty': '1.00',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_search_filters_service_items_by_name_or_description(self):
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.get(pk=1)
        for name, desc in [('CNC Routing', 'router pass'), ('Hand Sanding', 'finish work')]:
            self.client.post('/api/service-items/', {
                'template_name': name, 'description': desc, 'units': 'hours',
                'rate_scheme': scheme.pk, 'default_billable_qty': '1.00',
            }, format='json')
        resp = self.client.get('/api/service-items/?search=cnc')
        self.assertEqual(resp.status_code, 200)
        names = [r['template_name'] for r in (resp.data.get('results') if isinstance(resp.data, dict) else resp.data)]
        self.assertIn('CNC Routing', names)
        self.assertNotIn('Hand Sanding', names)


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


class PercentageServiceServiceItemRejectionTest(BaseTestCase):
    """A RateScheme with algorithm=PERCENTAGE must be rejected when assigning
    to a ServiceItem — percentage services are document-level adjustments only."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        from apps.jobs.models import RateScheme
        from apps.core.models import AccountingCategory
        ac = AccountingCategory.objects.create(code='TMP-PCT', name='TMP-PCT')
        self.rush = RateScheme.objects.create(
            name='Rush TT', algorithm=RateScheme.PERCENTAGE, rate='15',
            unit_label='%', accounting_category=ac,
        )

    def test_cannot_assign_percentage_service_to_service_item(self):
        resp = self.client.post('/api/service-items/', {
            'template_name': 'Rush Template',
            'rate_scheme': self.rush.pk,
            'default_billable_qty': '1.00',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
