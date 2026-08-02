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
            'units': 'hour',
            'rate_scheme': scheme.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_create_allowed_for_jobs_atom_without_config(self):
        # Inline "save to catalog" must work for a plan-builder (can_manage_jobs)
        # who lacks can_manage_config.
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme
        u = User.objects.create_user(username='planbuilder', password='x')
        u.user_permissions.add(Permission.objects.get(codename='can_manage_jobs'))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=u.pk))
        scheme = RateScheme.objects.get(pk=1)
        resp = client.post('/api/service-items/', {
            'template_name': 'Inline Saved', 'description': '', 'units': 'hour',
            'rate_scheme': scheme.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201)

    def test_search_filters_service_items_by_name_or_description(self):
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.get(pk=1)
        for name, desc in [('CNC Routing', 'router pass'), ('Hand Sanding', 'finish work')]:
            self.client.post('/api/service-items/', {
                'template_name': name, 'description': desc, 'units': 'hour',
                'rate_scheme': scheme.pk,
            }, format='json')
        resp = self.client.get('/api/service-items/?search=cnc')
        self.assertEqual(resp.status_code, 200)
        names = [r['template_name'] for r in (resp.data.get('results') if isinstance(resp.data, dict) else resp.data)]
        self.assertIn('CNC Routing', names)
        self.assertNotIn('Hand Sanding', names)

    def _atom_client(self, username, *codenames):
        from django.contrib.auth.models import Permission
        u = User.objects.create_user(username=username, password='x')
        for c in codenames:
            u.user_permissions.add(Permission.objects.get(codename=c))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=u.pk))
        return client

    def _make_item(self):
        from apps.estimates.models import ServiceItem
        from apps.jobs.models import RateScheme
        return ServiceItem.objects.create(
            template_name='Perm Target', rate_scheme=RateScheme.objects.get(pk=1)
        )

    def test_financials_atom_can_create_update_delete(self):
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.get(pk=1)
        client = self._atom_client('fin_user', 'can_manage_financials')
        resp = client.post('/api/service-items/', {
            'template_name': 'Fin Created', 'description': '',
            'rate_scheme': scheme.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        resp = client.delete(f'/api/service-items/{item.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_jobs_atom_can_update_and_delete(self):
        # Was config-only; the catalog now belongs to plan-builders too.
        client = self._atom_client('jobs_user', 'can_manage_jobs')
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'y'}, format='json')
        self.assertEqual(resp.status_code, 200)
        resp = client.delete(f'/api/service-items/{item.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_no_atom_user_reads_but_cannot_write(self):
        client = self._atom_client('plain_user')
        resp = client.get('/api/service-items/')
        self.assertEqual(resp.status_code, 200)
        resp = client.post('/api/service-items/', {
            'template_name': 'Nope',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'z'}, format='json')
        self.assertEqual(resp.status_code, 403)


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

    def test_default_material_accounting_category_roundtrip(self):
        cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': str(cat.pk)},
                                 format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_material_accounting_category').value, str(cat.pk))

    def test_default_material_accounting_category_rejects_unknown(self):
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': '999999'},
                                 format='json')
        self.assertEqual(resp.status_code, 400)

    def test_default_material_accounting_category_rejects_inactive(self):
        cat = AccountingCategory.objects.create(
            name='Old Materials', is_active=False, code='OLDMAT')
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': str(cat.pk)},
                                 format='json')
        self.assertEqual(resp.status_code, 400)

    def test_default_material_accounting_category_blank_clears(self):
        Configuration.objects.update_or_create(
            key='default_material_accounting_category', defaults={'value': '5'})
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': ''},
                                 format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_material_accounting_category').value, '')


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
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
