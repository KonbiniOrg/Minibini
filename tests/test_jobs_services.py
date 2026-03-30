"""Tests for jobs app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, WorkOrder, Task, TaskBundle
from apps.jobs.services import JobService, WorkOrderService, TaskService
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError
from apps.core.models import AccountingCategory
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
        self.lit = AccountingCategory.objects.create(
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
            job=self.job,
        )

    def test_update_status(self):
        """Update work order status."""
        updated = WorkOrderService.update_status(self.wo.pk, 'blocked')
        self.assertEqual(updated.status, 'blocked')

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
            job=self.job,
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
            job=self.job,
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
            job=self.job,
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


class WorkOrderServiceCreateFromEstimateTest(JobsTestBase):
    """Tests for WorkOrderService.create_from_estimate."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001', status='accepted')

    def test_creates_work_order(self):
        """Creates a work order linked to the estimate's job."""
        wo = WorkOrderService.create_from_estimate(self.estimate)
        self.assertIsNotNone(wo.pk)
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.status, 'incomplete')

    def test_converts_line_items_to_tasks(self):
        """Each estimate line item becomes a task on the work order."""
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Cut steel',
            qty=Decimal('2.00'), units='hrs', price=Decimal('50.00'),
            accounting_category=self.lit)
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Weld frame',
            qty=Decimal('3.00'), units='hrs', price=Decimal('60.00'),
            accounting_category=self.lit)

        wo = WorkOrderService.create_from_estimate(self.estimate)

        tasks = Task.objects.filter(work_order=wo)
        self.assertEqual(tasks.count(), 2)

    def test_task_fields_from_manual_line_item(self):
        """Manual line item task gets description, qty, units, price."""
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Custom fabrication',
            qty=Decimal('4.00'), units='pcs', price=Decimal('100.00'),
            accounting_category=self.lit)

        wo = WorkOrderService.create_from_estimate(self.estimate)
        task = Task.objects.get(work_order=wo)

        self.assertEqual(task.name, 'Custom fabrication')
        self.assertEqual(task.est_qty, Decimal('4.00'))
        self.assertEqual(task.units, 'pcs')
        self.assertEqual(task.rate, Decimal('100.00'))

    def test_task_from_catalog_line_item(self):
        """Catalog line item task gets PLI code in name and falls back to PLI fields."""
        pli = PriceListItem.objects.create(
            code='STL-001', description='Steel plate',
            units='sheets', selling_price=Decimal('75.00'))

        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Steel plate',
            price_list_item=pli,
            qty=Decimal('10.00'), units='', price=Decimal('0.00'),
            accounting_category=self.lit)

        wo = WorkOrderService.create_from_estimate(self.estimate)
        task = Task.objects.get(work_order=wo)

        self.assertIn('STL-001', task.name)
        self.assertEqual(task.units, 'sheets')  # fell back to PLI
        self.assertEqual(task.rate, Decimal('75.00'))  # fell back to PLI

    def test_empty_estimate_creates_empty_work_order(self):
        """Estimate with no line items creates a work order with no tasks."""
        wo = WorkOrderService.create_from_estimate(self.estimate)
        self.assertEqual(Task.objects.filter(work_order=wo).count(), 0)

    def test_rejects_draft_estimate(self):
        """Draft estimate cannot create a work order."""
        draft_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-DRAFT', status='draft')

        with self.assertRaises(ValidationError):
            WorkOrderService.create_from_estimate(draft_estimate)

    def test_rejects_rejected_estimate(self):
        """Rejected estimate cannot create a work order."""
        rejected_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-REJ', status='rejected')

        with self.assertRaises(ValidationError):
            WorkOrderService.create_from_estimate(rejected_estimate)

    def test_accepts_open_estimate(self):
        """Open estimate can create a work order."""
        open_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-OPEN', status='open')

        wo = WorkOrderService.create_from_estimate(open_estimate)
        self.assertIsNotNone(wo.pk)


class WorkOrderServiceCreateFromTemplateTest(JobsTestBase):
    """Tests for WorkOrderService.create_from_template."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.template = WorkOrderTemplate.objects.create(
            template_name='Standard Build')
        self.task_tmpl_1 = TaskTemplate.objects.create(
            template_name='Cut', units='hrs', rate=Decimal('50.00'),
            accounting_category=self.lit)
        self.task_tmpl_2 = TaskTemplate.objects.create(
            template_name='Weld', units='hrs', rate=Decimal('60.00'),
            accounting_category=self.lit)
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template, task_template=self.task_tmpl_1,
            est_qty=Decimal('2.00'), sort_order=1)
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template, task_template=self.task_tmpl_2,
            est_qty=Decimal('3.00'), sort_order=2)

    def test_creates_work_order(self):
        """Creates a work order linked to job and template."""
        wo = WorkOrderService.create_from_template(self.template, self.job)
        self.assertIsNotNone(wo.pk)
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.template, self.template)
        self.assertEqual(wo.status, 'incomplete')

    def test_generates_tasks_from_template(self):
        """Each active template association generates a task."""
        wo = WorkOrderService.create_from_template(self.template, self.job)
        tasks = Task.objects.filter(work_order=wo).order_by('sort_order')
        self.assertEqual(tasks.count(), 2)

    def test_task_fields_from_template(self):
        """Generated tasks inherit fields from the task template."""
        wo = WorkOrderService.create_from_template(self.template, self.job)
        tasks = Task.objects.filter(work_order=wo).order_by('sort_order')

        cut_task = tasks[0]
        self.assertEqual(cut_task.name, 'Cut')
        self.assertEqual(cut_task.units, 'hrs')
        self.assertEqual(cut_task.rate, Decimal('50.00'))
        self.assertEqual(cut_task.est_qty, Decimal('2.00'))
        self.assertEqual(cut_task.accounting_category, self.lit)

        weld_task = tasks[1]
        self.assertEqual(weld_task.name, 'Weld')
        self.assertEqual(weld_task.est_qty, Decimal('3.00'))

    def test_skips_inactive_task_templates(self):
        """Inactive task templates are not generated."""
        self.task_tmpl_2.is_active = False
        self.task_tmpl_2.save()

        wo = WorkOrderService.create_from_template(self.template, self.job)
        tasks = Task.objects.filter(work_order=wo)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks[0].name, 'Cut')

    def test_rejects_inactive_template(self):
        """Inactive work order template raises ValidationError."""
        self.template.is_active = False
        self.template.save()

        with self.assertRaises(ValidationError):
            WorkOrderService.create_from_template(self.template, self.job)

    def test_template_with_no_associations(self):
        """Template with no task associations creates empty work order."""
        empty_template = WorkOrderTemplate.objects.create(
            template_name='Empty Template')

        wo = WorkOrderService.create_from_template(empty_template, self.job)
        self.assertEqual(Task.objects.filter(work_order=wo).count(), 0)


class WorkOrderServiceCreateDirectTest(JobsTestBase):
    """Tests for WorkOrderService.create_direct."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)

    def test_creates_incomplete_work_order(self):
        """Creates a work order in incomplete status."""
        wo = WorkOrderService.create_direct(self.job)
        self.assertIsNotNone(wo.pk)
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.status, 'incomplete')

    def test_accepts_kwargs(self):
        """Passes extra kwargs through to WorkOrder.create."""
        template = WorkOrderTemplate.objects.create(
            template_name='Test Template')
        wo = WorkOrderService.create_direct(self.job, template=template)
        self.assertEqual(wo.template, template)


class WorkOrderServiceCopyFromWorksheetTest(JobsTestBase):
    """Tests for WorkOrderService.copy_from_worksheet."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001', status='accepted')
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate)
        self.wo = WorkOrder.objects.create(job=self.job, status='draft')

    def test_copies_tasks(self):
        """Tasks are copied from worksheet to work order."""
        Task.objects.create(
            est_worksheet=self.worksheet, name='Cut', units='hrs',
            rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            accounting_category=self.lit, sort_order=1)
        Task.objects.create(
            est_worksheet=self.worksheet, name='Weld', units='hrs',
            rate=Decimal('60.00'), est_qty=Decimal('3.00'),
            accounting_category=self.lit, sort_order=2)

        WorkOrderService.copy_from_worksheet(self.wo.pk, self.worksheet.pk)

        wo_tasks = Task.objects.filter(work_order=self.wo).order_by('sort_order')
        self.assertEqual(wo_tasks.count(), 2)
        self.assertEqual(wo_tasks[0].name, 'Cut')
        self.assertEqual(wo_tasks[0].rate, Decimal('50.00'))
        self.assertEqual(wo_tasks[1].name, 'Weld')
        self.assertEqual(wo_tasks[1].est_qty, Decimal('3.00'))

    def test_copies_task_fields(self):
        """All task fields are copied faithfully."""
        Task.objects.create(
            est_worksheet=self.worksheet, name='Paint',
            description='Apply primer and topcoat',
            units='sq ft', rate=Decimal('5.00'), est_qty=Decimal('100.00'),
            accounting_category=self.lit, mapping_strategy='direct', sort_order=1)

        WorkOrderService.copy_from_worksheet(self.wo.pk, self.worksheet.pk)

        task = Task.objects.get(work_order=self.wo)
        self.assertEqual(task.name, 'Paint')
        self.assertEqual(task.description, 'Apply primer and topcoat')
        self.assertEqual(task.units, 'sq ft')
        self.assertEqual(task.accounting_category, self.lit)
        self.assertEqual(task.mapping_strategy, 'direct')

    def test_copies_materials(self):
        """Materials on tasks are copied to the new tasks."""
        ws_task = Task.objects.create(
            est_worksheet=self.worksheet, name='Cut',
            sort_order=1)
        pli = PriceListItem.objects.create(
            code='STL-001', description='Steel plate',
            purchase_price=Decimal('50.00'))
        Material(
            task=ws_task, price_list_item=pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'), sell_price=Decimal('75.00')).save()

        WorkOrderService.copy_from_worksheet(self.wo.pk, self.worksheet.pk)

        wo_task = Task.objects.get(work_order=self.wo)
        materials = Material.objects.filter(task=wo_task)
        self.assertEqual(materials.count(), 1)
        mat = materials[0]
        self.assertEqual(mat.description, 'Steel plate')
        self.assertEqual(mat.quantity, Decimal('5.00'))
        self.assertEqual(mat.unit_cost, Decimal('50.00'))
        self.assertEqual(mat.sell_price, Decimal('75.00'))
        self.assertEqual(mat.price_list_item, pli)

    def test_copies_bundles_and_remaps_tasks(self):
        """TaskBundles are copied, and bundled tasks point to the new bundles."""
        bundle = TaskBundle.objects.create(
            est_worksheet=self.worksheet, name='Assembly',
            sort_order=1, accounting_category=self.lit)
        Task.objects.create(
            est_worksheet=self.worksheet, name='Assemble part A',
            bundle=bundle, mapping_strategy='bundle', sort_order=1)
        Task.objects.create(
            est_worksheet=self.worksheet, name='Assemble part B',
            bundle=bundle, mapping_strategy='bundle', sort_order=2)

        WorkOrderService.copy_from_worksheet(self.wo.pk, self.worksheet.pk)

        wo_bundles = TaskBundle.objects.filter(work_order=self.wo)
        self.assertEqual(wo_bundles.count(), 1)
        wo_bundle = wo_bundles[0]
        self.assertEqual(wo_bundle.name, 'Assembly')
        self.assertEqual(wo_bundle.accounting_category, self.lit)

        bundled_tasks = Task.objects.filter(
            work_order=self.wo, bundle=wo_bundle).order_by('sort_order')
        self.assertEqual(bundled_tasks.count(), 2)
        self.assertEqual(bundled_tasks[0].name, 'Assemble part A')
        self.assertEqual(bundled_tasks[1].name, 'Assemble part B')

    def test_empty_worksheet(self):
        """Empty worksheet copies nothing."""
        WorkOrderService.copy_from_worksheet(self.wo.pk, self.worksheet.pk)
        self.assertEqual(Task.objects.filter(work_order=self.wo).count(), 0)
        self.assertEqual(TaskBundle.objects.filter(work_order=self.wo).count(), 0)

    def test_work_order_not_found(self):
        """Nonexistent work order raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            WorkOrderService.copy_from_worksheet(99999, self.worksheet.pk)

    def test_worksheet_not_found(self):
        """Nonexistent worksheet raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            WorkOrderService.copy_from_worksheet(self.wo.pk, 99999)
