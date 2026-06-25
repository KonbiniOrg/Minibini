from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, PlanTask, ServiceItem
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.contacts.models import Contact, Business

User = get_user_model()


class PlanMaterialsApiTest(APITestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='cat', code='PM01')
        self.user = User.objects.create_user('pmapi_u', password='p')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)  # clear permission cache
        self.client.force_login(self.user)
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Biz', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='JOB-PM-1', contact=contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme_ac = AccountingCategory.objects.create(name='pmapi-sc', code='PMAPI-SC')
        self.scheme = ServiceItem.objects.create(
            name='S-pmapi', algorithm=ServiceItem.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.scheme_ac,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Task 1',
            service_item=self.scheme,
            est_qty=Decimal('1'),
        )

    def test_post_without_plan_task_creates_worksheet_level(self):
        """POST to plan-materials without plan_task creates a task-less PlanMaterial."""
        url = f'/api/est-worksheets/{self.worksheet.pk}/plan-materials/'
        resp = self.client.post(url, {
            'description': 'loose bolt',
            'quantity': '5',
            'unit_cost': '1.50',
            'sell_price': '2.00',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        mat = PlanMaterial.objects.get(pk=resp.data['plan_material_id'])
        self.assertIsNone(mat.plan_task)
        self.assertEqual(mat.est_worksheet, self.worksheet)
        self.assertEqual(mat.description, 'loose bolt')

    def test_post_with_plan_task_creates_task_attached(self):
        """POST to plan-materials with plan_task attaches to the given task."""
        url = f'/api/est-worksheets/{self.worksheet.pk}/plan-materials/'
        resp = self.client.post(url, {
            'description': 'task bolt',
            'quantity': '3',
            'plan_task': self.plan_task.pk,
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        mat = PlanMaterial.objects.get(pk=resp.data['plan_material_id'])
        self.assertEqual(mat.plan_task, self.plan_task)
        self.assertEqual(mat.est_worksheet, self.worksheet)

    def test_get_plan_materials_lists_all_worksheet_materials(self):
        """GET plan-materials returns both task-level and worksheet-level items."""
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=None, description='loose',
            accounting_category=self.cat,
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=self.plan_task, description='task-attached',
            accounting_category=self.cat,
        )
        url = f'/api/est-worksheets/{self.worksheet.pk}/plan-materials/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)

    def test_patch_plan_material(self):
        """PATCH plan-materials/{id}/ updates the material."""
        mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=None, description='old desc',
            accounting_category=self.cat,
        )
        url = f'/api/est-worksheets/{self.worksheet.pk}/plan-materials/{mat.pk}/'
        resp = self.client.patch(url, {'description': 'new desc'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        mat.refresh_from_db()
        self.assertEqual(mat.description, 'new desc')

    def test_delete_plan_material(self):
        """DELETE plan-materials/{id}/ removes the material."""
        mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=None, description='to delete',
            accounting_category=self.cat,
        )
        url = f'/api/est-worksheets/{self.worksheet.pk}/plan-materials/{mat.pk}/'
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(PlanMaterial.objects.filter(pk=mat.pk).exists())
