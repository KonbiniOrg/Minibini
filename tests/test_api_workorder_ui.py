"""Tests for work order UI API endpoints: Material CRUD, subtasks, reorder, add-from-template."""

from decimal import Decimal
from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, WorkOrder
from apps.contacts.models import Contact
from apps.estimates.models import TaskTemplate
from apps.inventory.models import Material, PriceListItem


class MaterialCRUDTest(TestCase):
    """Tests for Material CRUD nested under /api/tasks/{id}/materials/."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='matuser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Mat', last_name='Test')
        self.job = Job.objects.create(
            job_number='MAT-001', name='Material Job', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo,
            name='Install countertop',
            units='each',
            rate=100,
            est_qty=1,
        )
        self.material = Material.objects.create(
            task=self.task,
            description='Granite slab',
            quantity=2,
            unit_cost=Decimal('50.00'),
            sell_price=Decimal('100.00'),
        )

    def test_list_materials(self):
        response = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['description'], 'Granite slab')

    def test_list_materials_any_authenticated_user(self):
        """Any authenticated user can list materials (no special permission needed)."""
        viewer = User.objects.create_user(username='viewer', password='testpass')
        self.client.force_authenticate(user=viewer)
        response = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(response.status_code, 200)

    def test_list_materials_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(response.status_code, 403)

    def test_create_material(self):
        response = self.client.post(
            f'/api/tasks/{self.task.pk}/materials/',
            {'description': 'Epoxy glue', 'quantity': '1.00', 'unit_cost': '15.00', 'sell_price': '25.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['description'], 'Epoxy glue')
        self.assertEqual(Material.objects.filter(task=self.task).count(), 2)

    def test_create_material_any_authenticated_user(self):
        """Any authenticated user can create materials (workers record actuals)."""
        worker = User.objects.create_user(username='worker', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/tasks/{self.task.pk}/materials/',
            {'description': 'Screws', 'quantity': '10.00', 'unit_cost': '0.50', 'sell_price': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_material_with_pli(self):
        pli = PriceListItem.objects.create(
            code='EPOXY-01', description='Epoxy 2-part', units='tube',
            purchase_price=Decimal('10.00'), selling_price=Decimal('20.00'),
        )
        response = self.client.post(
            f'/api/tasks/{self.task.pk}/materials/',
            {'price_list_item': pli.pk, 'quantity': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['description'], 'Epoxy 2-part')
        self.assertEqual(response.data['unit_cost'], '10.00')
        self.assertEqual(response.data['sell_price'], '20.00')

    def test_update_material(self):
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['quantity'], '5.00')

    def test_update_material_any_authenticated_user(self):
        worker = User.objects.create_user(username='worker2', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/',
            {'quantity': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_material(self):
        response = self.client.delete(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['message'], 'Material deleted.')
        self.assertFalse(Material.objects.filter(pk=self.material.pk).exists())

    def test_delete_material_any_authenticated_user(self):
        worker = User.objects.create_user(username='worker3', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.delete(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/'
        )
        self.assertEqual(response.status_code, 200)

    def test_material_not_found(self):
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/99999/',
            {'quantity': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_material_wrong_task(self):
        """Material on a different task should not be accessible."""
        task2 = Task.objects.create(
            work_order=self.wo, name='Other task', units='each', rate=50, est_qty=1,
        )
        response = self.client.patch(
            f'/api/tasks/{task2.pk}/materials/{self.material.pk}/',
            {'quantity': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)


class SubtaskCRUDTest(TestCase):
    """Tests for subtask list/create nested under /api/tasks/{id}/subtasks/."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='subuser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Sub', last_name='Test')
        self.job = Job.objects.create(
            job_number='SUB-001', name='Subtask Job', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)
        self.parent_task = Task.objects.create(
            work_order=self.wo,
            name='Parent task',
            units='each',
            rate=100,
            est_qty=1,
        )

    def test_list_subtasks_empty(self):
        response = self.client.get(f'/api/tasks/{self.parent_task.pk}/subtasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_list_subtasks(self):
        Task.objects.create(
            work_order=self.wo,
            parent_task=self.parent_task,
            name='Child task',
            units='hr',
            rate=50,
            est_qty=2,
        )
        response = self.client.get(f'/api/tasks/{self.parent_task.pk}/subtasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Child task')

    def test_create_subtask(self):
        response = self.client.post(
            f'/api/tasks/{self.parent_task.pk}/subtasks/',
            {'name': 'New subtask', 'units': 'hours', 'rate': '25.00', 'est_qty': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'New subtask')
        # Verify parent_task and work_order are auto-set
        child = Task.objects.get(pk=response.data['task_id'])
        self.assertEqual(child.parent_task_id, self.parent_task.pk)
        self.assertEqual(child.work_order_id, self.wo.pk)

    def test_create_subtask_any_authenticated_user(self):
        worker = User.objects.create_user(username='subworker', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/tasks/{self.parent_task.pk}/subtasks/',
            {'name': 'Worker subtask', 'units': 'ea', 'rate': '10.00', 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_subtask_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/tasks/{self.parent_task.pk}/subtasks/',
            {'name': 'Fail', 'units': 'ea', 'rate': '10.00', 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class ReorderTasksTest(TestCase):
    """Tests for POST /api/work-orders/{id}/reorder/."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='reorduser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Reord', last_name='Test')
        self.job = Job.objects.create(
            job_number='REORD-001', name='Reorder Job', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task_a = Task.objects.create(
            work_order=self.wo, name='Task A', units='each', rate=10, est_qty=1, sort_order=0,
        )
        self.task_b = Task.objects.create(
            work_order=self.wo, name='Task B', units='each', rate=20, est_qty=1, sort_order=1,
        )
        self.task_c = Task.objects.create(
            work_order=self.wo, name='Task C', units='each', rate=30, est_qty=1, sort_order=2,
        )

    def test_reorder_down(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_a.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.task_a.refresh_from_db()
        self.task_b.refresh_from_db()
        self.assertEqual(self.task_a.sort_order, 1)
        self.assertEqual(self.task_b.sort_order, 0)

    def test_reorder_up(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_c.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.task_c.refresh_from_db()
        self.task_b.refresh_from_db()
        self.assertEqual(self.task_c.sort_order, 1)
        self.assertEqual(self.task_b.sort_order, 2)

    def test_reorder_up_at_top(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_a.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Already at top', response.data['detail'])

    def test_reorder_down_at_bottom(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_c.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Already at bottom', response.data['detail'])

    def test_reorder_invalid_direction(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_a.pk, 'direction': 'left'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_missing_task_id(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_task_not_on_wo(self):
        other_wo = WorkOrder.objects.create(job=self.job)
        other_task = Task.objects.create(
            work_order=other_wo, name='Other', units='each', rate=10, est_qty=1, sort_order=0,
        )
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': other_task.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_reorder_any_authenticated_user(self):
        worker = User.objects.create_user(username='reordworker', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/reorder/',
            {'task_id': self.task_b.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)


class AddFromTemplateTest(TestCase):
    """Tests for POST /api/work-orders/{id}/add-from-template/."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='tmpluser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='Tmpl', last_name='Test')
        self.job = Job.objects.create(
            job_number='TMPL-001', name='Template Job', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)
        self.template = TaskTemplate.objects.create(
            template_name='Paint room',
            description='Paint all walls',
            units='sqft',
            rate=Decimal('2.50'),
        )

    def test_add_from_template_success(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'task_template_id': self.template.pk, 'est_qty': '100.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Paint room')
        self.assertEqual(response.data['units'], 'sqft')
        self.assertEqual(response.data['rate'], '2.50')
        self.assertEqual(response.data['est_qty'], '100.00')
        # Verify task was created on the WO
        self.assertEqual(Task.objects.filter(work_order=self.wo).count(), 1)

    def test_add_from_template_default_qty(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'task_template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['est_qty'], '1.00')

    def test_add_from_template_missing_template(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'task_template_id': 99999, 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_add_from_template_missing_template_id(self):
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_add_from_template_any_authenticated_user(self):
        worker = User.objects.create_user(username='tmplworker', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'task_template_id': self.template.pk, 'est_qty': '5.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_add_from_template_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/work-orders/{self.wo.pk}/add-from-template/',
            {'task_template_id': self.template.pk, 'est_qty': '1.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class TerminalTaskGuardTest(TestCase):
    """Completed and cancelled tasks reject material/subtask mutations."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='termuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Term', last_name='Test')
        self.job = Job.objects.create(
            job_number='TERM-001', name='Terminal Job', contact=self.contact,
        )
        self.wo = WorkOrder.objects.create(job=self.job)

    def _make_task(self, task_status):
        return Task.objects.create(
            work_order=self.wo, name='A task', units='each',
            rate=10, est_qty=1, status=task_status,
        )

    def test_cannot_add_material_to_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        response = self.client.post(
            f'/api/tasks/{task.pk}/materials/',
            {'description': 'Nope', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('complete', response.data['detail'].lower())

    def test_cannot_add_material_to_cancelled_task(self):
        task = self._make_task(Task.STATUS_CANCELLED)
        response = self.client.post(
            f'/api/tasks/{task.pk}/materials/',
            {'description': 'Nope', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_edit_material_on_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        mat = Material.objects.create(
            task=task, description='Existing', quantity=1,
            unit_cost=Decimal('5.00'), sell_price=Decimal('10.00'),
        )
        response = self.client.patch(
            f'/api/tasks/{task.pk}/materials/{mat.pk}/',
            {'quantity': '99'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_delete_material_on_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        mat = Material.objects.create(
            task=task, description='Existing', quantity=1,
            unit_cost=Decimal('5.00'), sell_price=Decimal('10.00'),
        )
        response = self.client.delete(
            f'/api/tasks/{task.pk}/materials/{mat.pk}/',
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_add_subtask_to_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        response = self.client.post(
            f'/api/tasks/{task.pk}/subtasks/',
            {'name': 'Nope', 'units': 'ea', 'rate': '10', 'est_qty': '1'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_can_list_materials_on_complete_task(self):
        """Reading is still allowed on terminal tasks."""
        task = self._make_task(Task.STATUS_COMPLETE)
        response = self.client.get(f'/api/tasks/{task.pk}/materials/')
        self.assertEqual(response.status_code, 200)

    def test_can_list_subtasks_on_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        response = self.client.get(f'/api/tasks/{task.pk}/subtasks/')
        self.assertEqual(response.status_code, 200)

    def test_can_add_material_to_in_progress_task(self):
        """Non-terminal statuses are fine."""
        task = self._make_task(Task.STATUS_IN_PROGRESS)
        response = self.client.post(
            f'/api/tasks/{task.pk}/materials/',
            {'description': 'Yes', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
