from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.inventory.models import Material, PlanMaterial, InventoryItem
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets"]')
        cls.user = User.objects.create_user(username='u', password='p')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        cls.user.user_permissions.add(perm)
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.pli = InventoryItem.objects.create(
            code='PLI', units='sheets', description='X',
            purchase_price=Decimal('10'), selling_price=Decimal('20'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def setUp(self):
        self.client.force_login(self.user)


class FreeformMaterialRequiresCategoryTests(_Setup):
    def test_post_freeform_material_without_category_fails(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {'description': 'x', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_post_freeform_material_with_category_succeeds(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {
                'description': 'x', 'quantity': '1',
                'accounting_category': self.cat.pk,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_post_pli_linked_material_without_explicit_category_succeeds(self):
        # PLI fills in the category via _populate_from_pli, so no explicit
        # accounting_category is needed in the request.
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {
                'inventory_item': self.pli.pk,
                'quantity': '1',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        m = Material.objects.get(job=self.job)
        self.assertEqual(m.accounting_category_id, self.cat.pk)


class FreeformPlanMaterialRequiresCategoryTests(_Setup):
    def test_post_freeform_plan_material_without_category_fails(self):
        ws = EstWorksheet.objects.create(job=self.job)
        resp = self.client.post(
            f'/api/est-worksheets/{ws.pk}/plan-materials/',
            {'description': 'x', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)


class ModelLevelNotNullTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none"]')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_creating_freeform_material_without_category_raises(self):
        m = Material(
            job=self.job, description='x', quantity=Decimal('1'),
        )
        with self.assertRaises(ValidationError):
            m.save()  # full_clean inside save raises on missing category
