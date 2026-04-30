"""Tests for Task-related API endpoints under the new Job-centric model:
Material CRUD, subtasks, terminal task guards.

Reorder and add-from-template are tested in test_api_jobs.py against
/api/jobs/{id}/reorder-tasks/ and /api/jobs/{id}/add-from-template/.
"""

from decimal import Decimal
from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task
from apps.contacts.models import Contact
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
        self.task = Task.objects.create(
            job=self.job,
            name='Install countertop',
            units='each',
            rate=100,
            est_qty=1,
        )
        self.category = AccountingCategory.objects.create(
            name='General', code='GEN',
        )
        self.material = Material.objects.create(
            job=self.job,
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
            accounting_category=self.category,
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

    def test_update_material_description(self):
        """PATCH with description-only update succeeds."""
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/',
            {'description': 'Updated slab'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['description'], 'Updated slab')

    def test_update_material_quantity_rejected(self):
        """PATCH with quantity is rejected; quantity changes go through draw-more/restock."""
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_update_material_any_authenticated_user(self):
        worker = User.objects.create_user(username='worker2', password='testpass')
        self.client.force_authenticate(user=worker)
        response = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{self.material.pk}/',
            {'description': 'Worker update'},
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
            {'description': 'nonexistent'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_material_wrong_task(self):
        """Material on a different task should not be accessible."""
        task2 = Task.objects.create(
            job=self.job, name='Other task', units='each', rate=50, est_qty=1,
        )
        response = self.client.patch(
            f'/api/tasks/{task2.pk}/materials/{self.material.pk}/',
            {'description': 'wrong task'},
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
        self.parent_task = Task.objects.create(
            job=self.job,
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
            job=self.job,
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
        # Verify parent_task and job are auto-set
        child = Task.objects.get(pk=response.data['task_id'])
        self.assertEqual(child.parent_task_id, self.parent_task.pk)
        self.assertEqual(child.job_id, self.job.pk)

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

    def _make_task(self, task_status):
        return Task.objects.create(
            job=self.job, name='A task', units='each',
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
            job=self.job, task=task, description='Existing', quantity=1,
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
            job=self.job, task=task, description='Existing', quantity=1,
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
