"""Tests for jobs app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, WorkOrder, Task
from apps.jobs.services import JobService, WorkOrderService, TaskService
from apps.inventory.models import Material
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError
from apps.core.models import LineItemType
from apps.contacts.models import Contact, Business


class JobsTestBase(TestCase):
    """Shared setUp for jobs service tests."""
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@test.com', work_number='555-1234',
        )
        self.business = Business.objects.create(
            business_name='Test Biz', business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.lit = LineItemType.objects.create(
            code='SVC', name='Service', taxable=True,
        )


class JobServiceCreateTest(JobsTestBase):
    """Tests for JobService.create_job."""

    def test_create_job(self):
        """Create a job with auto-generated number."""
        job = JobService.create_job(
            name='Test Job', contact=self.contact,
        )
        self.assertIsNotNone(job.pk)
        self.assertTrue(job.job_number.startswith('JOB'))
        self.assertEqual(job.status, 'draft')
        self.assertEqual(job.contact, self.contact)

    def test_create_job_with_description(self):
        """Create a job with optional fields."""
        job = JobService.create_job(
            name='Full Job', contact=self.contact,
            description='Some work', customer_po_number='CPO-123',
        )
        self.assertEqual(job.description, 'Some work')
        self.assertEqual(job.customer_po_number, 'CPO-123')


class JobServiceUpdateTest(JobsTestBase):
    """Tests for JobService.update_job."""

    def test_update_job(self):
        """Update job fields."""
        job = JobService.create_job(name='Old Name', contact=self.contact)
        updated = JobService.update_job(job.pk, name='New Name')
        self.assertEqual(updated.name, 'New Name')

    def test_update_job_persists(self):
        """Update should persist to database."""
        job = JobService.create_job(name='Old', contact=self.contact)
        JobService.update_job(job.pk, name='New')
        refreshed = Job.objects.get(pk=job.pk)
        self.assertEqual(refreshed.name, 'New')

    def test_update_job_not_found(self):
        """Nonexistent job raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            JobService.update_job(99999, name='Nope')


class WorkOrderServiceStatusTest(JobsTestBase):
    """Tests for WorkOrderService.update_status."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.wo = WorkOrder.objects.create(
            job=self.job, status='draft',
        )

    def test_update_status(self):
        """Update work order status."""
        updated = WorkOrderService.update_status(self.wo.pk, 'incomplete')
        self.assertEqual(updated.status, 'incomplete')

    def test_update_status_not_found(self):
        """Nonexistent WO raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            WorkOrderService.update_status(99999, 'incomplete')


class TaskServiceUpdateTest(JobsTestBase):
    """Tests for TaskService.update_task."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.wo = WorkOrder.objects.create(
            job=self.job, status='draft',
        )
        self.task = Task.objects.create(
            work_order=self.wo, name='Task 1', sort_order=1,
        )

    def test_update_task(self):
        """Update task fields."""
        updated = TaskService.update_task(self.task.pk, name='Updated Task')
        self.assertEqual(updated.name, 'Updated Task')

    def test_update_task_not_found(self):
        """Nonexistent task raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            TaskService.update_task(99999, name='Nope')


class TaskServiceReorderTest(JobsTestBase):
    """Tests for TaskService.reorder_tasks."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.wo = WorkOrder.objects.create(
            job=self.job, status='draft',
        )
        self.t1 = Task.objects.create(
            work_order=self.wo, name='Task 1', sort_order=1,
        )
        self.t2 = Task.objects.create(
            work_order=self.wo, name='Task 2', sort_order=2,
        )

    def test_reorder_down(self):
        """Move task 1 down — swap with task 2."""
        TaskService.reorder_tasks(self.t1.pk, 'down')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.t2.sort_order, 1)

    def test_reorder_up(self):
        """Move task 2 up — swap with task 1."""
        TaskService.reorder_tasks(self.t2.pk, 'up')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t2.sort_order, 1)
        self.assertEqual(self.t1.sort_order, 2)


class MaterialServiceTest(JobsTestBase):
    """Tests for InventoryService material CRUD."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.wo = WorkOrder.objects.create(
            job=self.job, status='draft',
        )
        self.task = Task.objects.create(
            work_order=self.wo, name='Task 1', sort_order=1,
        )

    def test_create_material(self):
        """Create a material on a task."""
        mat = InventoryService.create_material(
            self.task.pk, description='Steel plate',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('15.00'),
        )
        self.assertIsNotNone(mat.pk)
        self.assertEqual(mat.task, self.task)
        self.assertEqual(mat.description, 'Steel plate')

    def test_update_material(self):
        """Update a material."""
        mat = Material.objects.create(
            task=self.task, description='Old', quantity=Decimal('1.00'),
        )
        updated = InventoryService.update_material(
            mat.pk, description='New', quantity=Decimal('3.00'),
        )
        self.assertEqual(updated.description, 'New')
        self.assertEqual(updated.quantity, Decimal('3.00'))

    def test_delete_material(self):
        """Delete a material."""
        mat = Material.objects.create(
            task=self.task, description='Delete me', quantity=Decimal('1.00'),
        )
        pk = mat.pk
        InventoryService.delete_material(pk)
        self.assertFalse(Material.objects.filter(pk=pk).exists())

    def test_delete_material_not_found(self):
        """Nonexistent material raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            InventoryService.delete_material(99999)
