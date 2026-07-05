"""Tests for Task-related API endpoints under the new Job-centric model:
Material CRUD, subtasks, terminal task guards.

Reorder and add-from-template are tested in test_api_jobs.py against
/api/jobs/{id}/reorder-tasks/ and /api/jobs/{id}/add-from-template/.
"""

from decimal import Decimal
from rest_framework.test import APIClient
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.core.models import User, AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import TaskService
from apps.contacts.models import Contact
from apps.inventory.models import Material, InventoryItem


def _make_scheme(name_suffix=''):
    """Create a minimal flat-fee RateScheme for tests that don't care about billing."""
    code = f'TST{name_suffix[:4]}'.upper()
    ac, _ = AccountingCategory.objects.get_or_create(
        code=code, defaults={'name': f'Test AC {name_suffix}'},
    )
    return RateScheme.objects.create(
        name=f'S-tst-{name_suffix}', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


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
        self.scheme = _make_scheme('mat')
        self.task = Task.objects.create(
            job=self.job,
            name='Install countertop',
            rate_scheme=self.scheme,
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
            accounting_category=self.category,
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
            {
                # Freeform material: no manual unit_cost — cost comes from a
                # linked expense/PO, and the serializer guard enforces that.
                'description': 'Epoxy glue', 'quantity': '1.00',
                'sell_price': '25.00',
                'accounting_category': self.category.pk,
            },
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
            {
                'description': 'Screws', 'quantity': '10.00',
                'sell_price': '1.00',
                'accounting_category': self.category.pk,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_material_with_pli(self):
        pli = InventoryItem.objects.create(
            code='EPOXY-01', description='Epoxy 2-part', units='tube',
            purchase_price=Decimal('10.00'), selling_price=Decimal('20.00'),
            accounting_category=self.category,
        )
        response = self.client.post(
            f'/api/tasks/{self.task.pk}/materials/',
            {'inventory_item': pli.pk, 'quantity': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['description'], 'Epoxy 2-part')
        self.assertEqual(response.data['unit_cost'], '10.00')
        self.assertEqual(response.data['sell_price'], '20.00')

    def test_create_material_customer_supplied_via_task_endpoint(self):
        """Task 13: the task-nested materials POST must thread
        customer_supplied through to MaterialService.create_on_job just like
        the job-level endpoint — born established at a locked $0."""
        response = self.client.post(
            f'/api/tasks/{self.task.pk}/materials/',
            {
                'description': 'Customer-owned trim', 'quantity': '1.00',
                'accounting_category': self.category.pk,
                'customer_supplied': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        m = Material.objects.get(task=self.task, description='Customer-owned trim')
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('0.00'))
        self.assertEqual(m.sell_price, Decimal('0.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_CUSTOMER)
        # Pricing is locked afterward: a PATCH attempting to price it 400s.
        patch_resp = self.client.patch(
            f'/api/tasks/{self.task.pk}/materials/{m.pk}/',
            {'unit_cost': '5.00'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, 400, patch_resp.content)

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
            job=self.job, name='Other task', rate_scheme=self.scheme,
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
        self.scheme = _make_scheme('sub')
        self.parent_task = Task.objects.create(
            job=self.job,
            name='Parent task',
            rate_scheme=self.scheme,
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
            rate_scheme=self.scheme,
        )
        response = self.client.get(f'/api/tasks/{self.parent_task.pk}/subtasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Child task')

    def test_create_subtask(self):
        response = self.client.post(
            f'/api/tasks/{self.parent_task.pk}/subtasks/',
            {'name': 'New subtask', 'est_qty': '3.00', 'rate_scheme': self.scheme.pk},
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
            {'name': 'Worker subtask', 'est_qty': '1.00', 'rate_scheme': self.scheme.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_create_subtask_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/tasks/{self.parent_task.pk}/subtasks/',
            {'name': 'Fail', 'est_qty': '1.00', 'rate_scheme': self.scheme.pk},
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
        self.scheme = _make_scheme('term')
        self.category = AccountingCategory.objects.get_or_create(
            code='TERM', defaults={'name': 'Term Cat'},
        )[0]

    def _make_task(self, task_status):
        return Task.objects.create(
            job=self.job, name='A task', status=task_status, rate_scheme=self.scheme,
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
            accounting_category=self.category,
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
            accounting_category=self.category,
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
            {'description': 'Yes', 'quantity': '1', 'accounting_category': self.category.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_update_task_rejects_edit_on_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        with self.assertRaises(ValidationError):
            TaskService.update_task(task.pk, name='renamed')

    def test_update_task_allows_sort_order_on_complete_task(self):
        task = self._make_task(Task.STATUS_COMPLETE)
        # sort_order is cosmetic; must remain editable
        TaskService.update_task(task.pk, sort_order=5)
        task.refresh_from_db()
        self.assertEqual(task.sort_order, 5)


class TaskSerializerFlattenTest(TestCase):
    """Phase B6: TaskSerializer exposes billing fields as top-level, no 'charge' key."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='flatuser', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Flat', last_name='Test')
        self.job = Job.objects.create(
            job_number='FLAT-001', name='Flat Serializer Job', contact=self.contact,
        )

    def test_task_serializer_flattens_billing_fields(self):
        """Phase B: rate_scheme, active_modifiers, est_qty, est_worker_time,
        actual_qty are top-level fields. 'charge' is no longer in the payload."""
        from decimal import Decimal
        from apps.jobs.models import RateScheme

        ac = AccountingCategory.objects.create(name='Labor')
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour',
            accounting_category=ac,
        )
        Task.objects.create(
            job=self.job, name='Test',
            rate_scheme=scheme, active_modifiers=['rush'],
            est_qty=Decimal('5'),
        )
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        payload = body['results'] if isinstance(body, dict) and 'results' in body else body
        row = next(t for t in payload if t['name'] == 'Test')
        self.assertEqual(row['rate_scheme'], scheme.pk)
        self.assertEqual(row['active_modifiers'], ['rush'])
        self.assertEqual(row['est_qty'], '5.00')
        self.assertIsNone(row['actual_qty'])
        self.assertNotIn('charge', row)

    def test_post_task_accepts_flat_billing_fields(self):
        """POST /api/jobs/<id>/tasks/ accepts rate_scheme, active_modifiers,
        est_qty, est_worker_time, actual_qty as direct fields (not nested in
        'actuals')."""
        from decimal import Decimal
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme

        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        # Re-fetch user so permission cache is cleared
        self.client.force_authenticate(user=User.objects.get(pk=self.user.pk))

        ac = AccountingCategory.objects.create(name='Labor2')
        scheme = RateScheme.objects.create(
            name='Hourly2', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour',
            accounting_category=ac,
        )
        payload = {
            'name': 'Bench work',
            'description': 'Test',
            'rate_scheme': scheme.pk,
            'active_modifiers': [],
            'est_qty': '5.00',
            'est_worker_time': 'PT5H',
        }
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/', payload,
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        task = Task.objects.get(pk=resp.json()['task_id'])
        self.assertEqual(task.rate_scheme_id, scheme.pk)
        self.assertEqual(task.est_qty, Decimal('5.00'))
        self.assertIsNotNone(task.est_worker_time)
        self.assertIsNone(task.actual_qty)


class TaskListInvoiceFieldTest(TestCase):
    """The task-list endpoints (/api/tasks/{id}/materials/ and /subtasks/) must
    carry the per-atom `invoice` ref so the task-list page can show INVOICED."""

    def setUp(self):
        from apps.core.models import Configuration, AppState
        # NumberGenerationService needs these to auto-generate invoice_number.
        Configuration.objects.get_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{counter:04d}'},
        )
        AppState.objects.get_or_create(key='invoice_counter', defaults={'value': '0'})

        self.client = APIClient()
        self.user = User.objects.create_user(username='tliuser', password='pw')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='L')
        self.job = Job.objects.create(
            job_number='TLI-001', name='TLI Job', contact=self.contact,
        )
        self.scheme = _make_scheme('tli')
        self.category = AccountingCategory.objects.create(name='G', code='GTLI')
        self.task = Task.objects.create(
            job=self.job, name='Parent', rate_scheme=self.scheme,
        )
        self.material = Material.objects.create(
            job=self.job, task=self.task, description='Slab',
            quantity=2, unit_cost=Decimal('5.00'), sell_price=Decimal('10.00'),
            accounting_category=self.category,
        )
        self.subtask = Task.objects.create(
            job=self.job, name='Child', rate_scheme=self.scheme,
            parent_task=self.task,
        )

    def _invoice_atom(self, source_type, source_pk):
        from apps.invoicing.models import (
            Invoice, InvoiceLineItem, InvoiceLineItemSource,
        )
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=Decimal('1'),
            units='none', price=Decimal('10.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li, source_type=source_type, source_pk=source_pk,
        )
        return inv

    def test_materials_endpoint_carries_invoice_ref(self):
        from apps.invoicing.models import InvoiceLineItemSource
        inv = self._invoice_atom(InvoiceLineItemSource.SOURCE_MATERIAL, self.material.pk)
        resp = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(resp.status_code, 200)
        row = resp.data[0]
        self.assertIsNotNone(row['invoice'])
        self.assertEqual(set(row['invoice'].keys()), {'id', 'number'})
        self.assertEqual(row['invoice']['id'], inv.pk)

    def test_materials_endpoint_invoice_null_when_not_invoiced(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/materials/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data[0]['invoice'])

    def test_subtasks_endpoint_carries_invoice_ref(self):
        from apps.invoicing.models import InvoiceLineItemSource
        inv = self._invoice_atom(InvoiceLineItemSource.SOURCE_TASK, self.subtask.pk)
        resp = self.client.get(f'/api/tasks/{self.task.pk}/subtasks/')
        self.assertEqual(resp.status_code, 200)
        row = resp.data[0]
        self.assertIsNotNone(row['invoice'])
        self.assertEqual(row['invoice']['id'], inv.pk)

    def test_subtasks_endpoint_invoice_null_when_not_invoiced(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/subtasks/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data[0]['invoice'])

    def test_task_retrieve_carries_invoice_ref(self):
        from apps.invoicing.models import InvoiceLineItemSource
        inv = self._invoice_atom(InvoiceLineItemSource.SOURCE_TASK, self.task.pk)
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data['invoice'])
        self.assertEqual(set(resp.data['invoice'].keys()), {'id', 'number'})
        self.assertEqual(resp.data['invoice']['id'], inv.pk)

    def test_task_retrieve_invoice_null_when_not_invoiced(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['invoice'])
