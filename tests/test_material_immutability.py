from decimal import Decimal
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, PlanMaterial, TemplateMaterial, PriceListItem,
)
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import Job, Task, PlanTask


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def setUp(self):
        self.client.force_login(self.user)
        # Grant permissions used across test classes (individual tests may add more).
        from django.contrib.auth.models import Permission
        self.user.user_permissions.set([
            Permission.objects.get(codename='can_manage_jobs'),
        ])


class MaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_material_description_rejected(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('immutable', str(resp.json()).lower())

    def test_patch_pli_linked_material_units_rejected(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_material_unit_cost_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))

    def test_patch_pli_linked_material_sell_price_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'sell_price': '78.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.sell_price, Decimal('78.00'))

    def test_patch_freeform_material_description_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=None,
            description='start', quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.description, 'NEW')

    def test_patch_freeform_material_units_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=None,
            description='x', quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.units, 'lbs')


class PlanMaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_plan_material_description_rejected(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_plan_material_unit_cost_allowed(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)


class TemplateMaterialImmutabilityTests(_Setup):
    def _grant_can_manage_config(self):
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'),
        )

    def test_patch_pli_linked_template_material_description_rejected(self):
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        self._grant_can_manage_config()
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_template_material_unit_cost_rejected(self):
        # TemplateMaterial does NOT get the pricing carve-out.
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        self._grant_can_manage_config()
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_template_material_quantity_allowed(self):
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        self._grant_can_manage_config()
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
