"""Tests for worksheet UI API endpoints: PlanMaterial CRUD, reorder, add-from-template."""

from decimal import Decimal
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, PlanTask, RateScheme
from apps.contacts.models import Contact
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.inventory.models import PlanMaterial, PriceListItem


class PlanMaterialCRUDTest(TestCase):
    """Tests for PlanMaterial CRUD nested under /api/plan-tasks/{id}/materials/."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='matuser', password='testpass',
        )
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.user.user_permissions.add(perm)
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Mat', last_name='Test')
        self.job = Job.objects.create(
            job_number='MAT-001', name='Material Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme_ac = AccountingCategory.objects.create(
            name='Mat-scheme', code='MAT-SC-AWUI',
        )
        self.scheme = RateScheme.objects.create(
            name='S-mat-awui', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.scheme_ac,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install countertop',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        self.category = AccountingCategory.objects.create(
            name='General', code='GEN',
        )
        self.material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task,
            description='Granite slab',
            quantity=2,
            unit_cost=Decimal('50.00'),
            sell_price=Decimal('100.00'),
        )

    def test_list_materials(self):
        response = self.client.get(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['description'], 'Granite slab')

    def test_list_materials_authenticated_only(self):
        """Any authenticated user can list materials (no special permission needed)."""
        viewer = User.objects.create_user(username='viewer', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.get(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/'
        )
        self.assertEqual(response.status_code, 200)

    def test_create_material(self):
        response = self.client.post(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/',
            {'description': 'Epoxy glue', 'quantity': '1.00', 'unit_cost': '15.00', 'sell_price': '25.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['description'], 'Epoxy glue')
        self.assertEqual(PlanMaterial.objects.filter(plan_task=self.plan_task).count(), 2)

    def test_create_material_with_pli(self):
        pli = PriceListItem.objects.create(
            code='EPOXY-01', description='Epoxy 2-part', units='tube',
            purchase_price=Decimal('10.00'), selling_price=Decimal('20.00'),
            accounting_category=self.category,
        )
        response = self.client.post(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/',
            {'price_list_item': pli.pk, 'quantity': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        # PlanMaterial.save populates from PLI
        self.assertEqual(response.data['description'], 'Epoxy 2-part')

    def test_update_material(self):
        response = self.client.patch(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/{self.material.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.material.refresh_from_db()
        self.assertEqual(self.material.quantity, Decimal('5.00'))

    def test_delete_material(self):
        response = self.client.delete(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/{self.material.pk}/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('deleted', response.data['message'].lower())
        self.assertFalse(PlanMaterial.objects.filter(pk=self.material.pk).exists())

    def test_create_requires_can_manage_jobs(self):
        viewer = User.objects.create_user(username='viewer2', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.post(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/',
            {'description': 'Nope', 'quantity': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_update_requires_can_manage_jobs(self):
        viewer = User.objects.create_user(username='viewer3', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.patch(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/{self.material.pk}/',
            {'quantity': '99.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_requires_can_manage_jobs(self):
        viewer = User.objects.create_user(username='viewer4', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.delete(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/{self.material.pk}/'
        )
        self.assertEqual(response.status_code, 403)

    def test_material_not_found_returns_404(self):
        response = self.client.patch(
            f'/api/plan-tasks/{self.plan_task.pk}/materials/99999/',
            {'quantity': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_material_on_wrong_task_returns_404(self):
        other_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Other task',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        response = self.client.patch(
            f'/api/plan-tasks/{other_task.pk}/materials/{self.material.pk}/',
            {'quantity': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)


class ReorderTest(TestCase):
    """Tests for reorder and reorder-in-bundle on EstWorksheetViewSet."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='reorderuser', password='testpass',
        )
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.user.user_permissions.add(perm)
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Reorder', last_name='Test')
        self.job = Job.objects.create(
            job_number='REORD-001', name='Reorder Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.category = AccountingCategory.objects.create(
            name='Labor', code='LAB', is_active=True,
        )
        self.scheme = RateScheme.objects.create(
            name='S-reord-awui', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.category,
        )

        self.task1 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task A', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.task2 = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task B', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )

    def test_reorder_task_down(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/reorder/',
            {'item_type': 'task', 'item_id': self.task1.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.assertGreater(self.task1.sort_order, self.task2.sort_order)

    def test_reorder_task_up(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/reorder/',
            {'item_type': 'task', 'item_id': self.task2.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.assertLess(self.task2.sort_order, self.task1.sort_order)

    def test_reorder_invalid_direction(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/reorder/',
            {'item_type': 'task', 'item_id': self.task1.pk, 'direction': 'sideways'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('direction', response.data)

    def test_reorder_invalid_item_type(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/reorder/',
            {'item_type': 'widget', 'item_id': self.task1.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('item_type', response.data)

    def test_reorder_requires_can_manage_jobs(self):
        viewer = User.objects.create_user(username='reordviewer', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/reorder/',
            {'item_type': 'task', 'item_id': self.task1.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class AddFromTemplateTest(TestCase):
    """Tests for add-from-template on EstWorksheetViewSet."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='tmpluser', password='testpass',
        )
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.user.user_permissions.add(perm)
        self.client.force_authenticate(user=self.user)

        self.category = AccountingCategory.objects.create(
            name='Labor', code='LAB2', is_active=True,
        )
        self.contact = Contact.objects.create(first_name='Tmpl', last_name='Test')
        self.job = Job.objects.create(
            job_number='TMPL-001', name='Template Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        # Phase B requires PlanTask.rate_scheme; templates used by add-from-template
        # must carry a default scheme so the created PlanTask inherits one.
        self.template_scheme = RateScheme.objects.create(
            name='Tmpl default scheme', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('2.50'), unit_label='sqft',
            accounting_category=self.category,
        )
        self.task_template = TaskTemplate.objects.create(
            template_name='Standard Sanding',
            description='Sand and prep surfaces',
            units='sqft',
            rate=Decimal('2.50'),
            accounting_category=self.category,
            rate_scheme=self.template_scheme,
            default_billable_qty=Decimal('1.00'),
        )

    def test_add_from_template_success(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': self.task_template.pk, 'est_qty': '100.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Standard Sanding')
        self.assertEqual(response.data['rate_scheme'], self.template_scheme.pk)
        self.assertEqual(response.data['est_qty'], '100.00')
        # 100 × $2.50 scheme rate = $250.00
        self.assertEqual(response.data['amount'], '250.00')
        # Verify it was created in the DB
        self.assertTrue(
            PlanTask.objects.filter(
                est_worksheet=self.worksheet, name='Standard Sanding'
            ).exists()
        )

    def test_add_from_template_explicit_billing_overrides_template_defaults(self):
        """Passing billing fields to add-from-template uses the caller's values."""
        from apps.jobs.models import RateScheme
        scheme = RateScheme.objects.create(
            name='Hourly', rate='75.00', unit_label='hr',
            algorithm=RateScheme.ENTERED_QTY,
            accounting_category=self.category,
        )
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {
                'task_template_id': self.task_template.pk,
                'rate_scheme': scheme.rate_scheme_id,
                'est_qty': '8.00',
                'active_modifiers': ['overtime'],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rate_scheme'], scheme.rate_scheme_id)
        self.assertEqual(response.data['est_qty'], '8.00')
        self.assertEqual(response.data['active_modifiers'], ['overtime'])

    def test_add_from_template_default_qty(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': self.task_template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        task = PlanTask.objects.get(
            est_worksheet=self.worksheet, name='Standard Sanding'
        )
        self.assertIsNotNone(task)

    def test_add_from_template_missing_template(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': 99999, 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.data)

    def test_add_from_template_missing_template_id(self):
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('task_template_id', response.data)

    def test_add_from_template_requires_can_manage_jobs(self):
        viewer = User.objects.create_user(username='tmplviewer', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': self.task_template.pk, 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_add_from_template_non_draft_worksheet(self):
        self.worksheet.status = EstWorksheet.STATUS_FINAL
        self.worksheet.save()
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': self.task_template.pk, 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('detail', response.data)

    def test_add_from_template_inherits_template_defaults_when_request_omits_billing(self):
        """When the caller doesn't send billing fields, template defaults are inherited."""
        from apps.jobs.models import RateScheme

        scheme = RateScheme.objects.create(
            name='Default Inheritance Test', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('45.00'), unit_label='hour',
            accounting_category=self.category,
        )
        template_with_defaults = TaskTemplate.objects.create(
            template_name='Template With Defaults',
            description='Has billing defaults',
            units='hr',
            rate=Decimal('45.00'),
            accounting_category=self.category,
            rate_scheme=scheme,
            default_billable_qty=Decimal('3.0'),
            default_active_modifiers=['rush'],
        )

        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {'task_template_id': template_with_defaults.pk},  # NO billing fields
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rate_scheme'], scheme.rate_scheme_id)
        self.assertEqual(response.data['est_qty'], '3.00')
        self.assertEqual(response.data['active_modifiers'], ['rush'])
