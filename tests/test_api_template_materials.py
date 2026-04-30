from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory
from apps.estimates.models import WorkTemplate
from apps.inventory.models import TemplateMaterial

User = get_user_model()


class TemplateMaterialApiTest(APITestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cat', code='TM01')
        # Worker: no permission atoms
        self.worker = User.objects.create_user('tm_worker', password='p')
        # Config manager
        self.config_user = User.objects.create_user('tm_config', password='p')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.config_user.user_permissions.add(perm)
        self.config_user = User.objects.get(pk=self.config_user.pk)  # clear permission cache
        self.template = WorkTemplate.objects.create(
            template_name='Widget Template',
            is_active=True,
        )

    def test_crud_requires_can_manage_config(self):
        """Worker (no atoms) gets 403 on POST; can_manage_config user gets 201."""
        url = f'/api/work-templates/{self.template.pk}/materials/'
        payload = {'description': 'screws', 'quantity': '10', 'unit_cost': '0.50', 'sell_price': '1.00'}

        # Worker cannot create
        self.client.force_login(self.worker)
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)

        # Config user can create
        self.client.force_login(self.config_user)
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_list_create_retrieve_update_delete(self):
        """Full CRUD cycle against /api/work-templates/{id}/materials/."""
        self.client.force_login(self.config_user)
        base_url = f'/api/work-templates/{self.template.pk}/materials/'

        # List — empty initially
        resp = self.client.get(base_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

        # Create
        resp = self.client.post(base_url, {
            'description': 'bolt', 'quantity': '4', 'unit_cost': '0.25', 'sell_price': '0.50',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        mat_id = resp.data['template_material_id']
        self.assertEqual(TemplateMaterial.objects.get(pk=mat_id).description, 'bolt')

        # List — now has one
        resp = self.client.get(base_url)
        self.assertEqual(len(resp.data), 1)

        # Retrieve
        resp = self.client.get(f'{base_url}{mat_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['description'], 'bolt')

        # Update
        resp = self.client.patch(f'{base_url}{mat_id}/', {'description': 'nut'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(TemplateMaterial.objects.get(pk=mat_id).description, 'nut')

        # Delete
        resp = self.client.delete(f'{base_url}{mat_id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(TemplateMaterial.objects.filter(pk=mat_id).exists())

    def test_read_is_allowed_for_authenticated_worker(self):
        """GET (list) is allowed for any authenticated user."""
        TemplateMaterial.objects.create(
            work_template=self.template, description='nail', quantity=Decimal('20'),
        )
        self.client.force_login(self.worker)
        url = f'/api/work-templates/{self.template.pk}/materials/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
