"""Tests for jobs app service methods (service-mediated saves)."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, Task, PlanTask, PlanBundle
from apps.jobs.services import JobService, TaskService
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet,
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.inventory.models import Material, PlanMaterial, PriceListItem
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
        self.lit, _ = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': True},
        )


class JobServiceCreateTest(JobsTestBase):
    """Tests for JobService.create_job."""

    def test_create_job(self):
        job = JobService.create_job(name='Test Job', contact=self.contact)
        self.assertIsNotNone(job.pk)
        self.assertTrue(job.job_number.startswith('JOB'))
        self.assertEqual(job.status, Job.STATUS_DRAFT)
        self.assertEqual(job.contact, self.contact)

    def test_create_job_with_description(self):
        job = JobService.create_job(
            name='Full Job', contact=self.contact,
            description='Some work', customer_po_number='CPO-123',
        )
        self.assertEqual(job.description, 'Some work')
        self.assertEqual(job.customer_po_number, 'CPO-123')


class JobServiceUpdateTest(JobsTestBase):
    """Tests for JobService.update_job."""

    def test_update_job(self):
        job = JobService.create_job(name='Old Name', contact=self.contact)
        updated = JobService.update_job(job.pk, name='New Name')
        self.assertEqual(updated.name, 'New Name')

    def test_update_job_persists(self):
        job = JobService.create_job(name='Old', contact=self.contact)
        JobService.update_job(job.pk, name='New')
        refreshed = Job.objects.get(pk=job.pk)
        self.assertEqual(refreshed.name, 'New')

    def test_update_job_not_found(self):
        with self.assertRaises(NotFoundError):
            JobService.update_job(99999, name='Nope')


def _walk_to(job, target_status):
    """Walk a job through its state machine to reach target_status."""
    path = {
        Job.STATUS_DRAFT: [Job.STATUS_DRAFT],
        Job.STATUS_SUBMITTED: [Job.STATUS_SUBMITTED],
        Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
        Job.STATUS_WORK_COMPLETE: [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_WORK_COMPLETE,
        ],
        Job.STATUS_COMPLETED: [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
            Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED,
        ],
    }[target_status]
    for step in path:
        if job.status != step:
            job.status = step
            job.save()


class JobServiceUpdateStatusTest(JobsTestBase):
    """Tests for JobService.update_status (Phase B behavior)."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)

    def test_update_status_changes_value(self):
        updated = JobService.update_status(self.job.pk, Job.STATUS_SUBMITTED)
        self.assertEqual(updated.status, Job.STATUS_SUBMITTED)

    def test_update_status_not_found(self):
        with self.assertRaises(NotFoundError):
            JobService.update_status(99999, Job.STATUS_SUBMITTED)

    def test_update_status_noop_short_circuits(self):
        """Setting a job to its current status returns unchanged without
        saving or firing side-effects."""
        _walk_to(self.job, Job.STATUS_WORK_COMPLETE)

        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release, patch.object(
            Job, 'save', autospec=True,
        ) as mock_save:
            result = JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(result.status, Job.STATUS_WORK_COMPLETE)
        mock_release.assert_not_called()
        mock_save.assert_not_called()

    def test_update_status_fires_release_on_transition_into_work_complete(self):
        _walk_to(self.job, Job.STATUS_APPROVED)

        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release:
            JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        mock_release.assert_called_once()


class TaskServiceUpdateTest(JobsTestBase):
    """Tests for TaskService.update_task."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.task = Task.objects.create(
            job=self.job, name='Task 1', sort_order=1,
        )

    def test_update_task(self):
        updated = TaskService.update_task(self.task.pk, name='Updated Task')
        self.assertEqual(updated.name, 'Updated Task')

    def test_update_task_not_found(self):
        with self.assertRaises(NotFoundError):
            TaskService.update_task(99999, name='Nope')


class TaskServiceReorderTest(JobsTestBase):
    """Tests for TaskService.reorder_tasks."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.t1 = Task.objects.create(
            job=self.job, name='Task 1', sort_order=1,
        )
        self.t2 = Task.objects.create(
            job=self.job, name='Task 2', sort_order=2,
        )

    def test_reorder_down(self):
        TaskService.reorder_tasks(self.t1.pk, 'down')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t1.sort_order, 2)
        self.assertEqual(self.t2.sort_order, 1)

    def test_reorder_up(self):
        TaskService.reorder_tasks(self.t2.pk, 'up')
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        self.assertEqual(self.t2.sort_order, 1)
        self.assertEqual(self.t1.sort_order, 2)


class MaterialServiceTest(JobsTestBase):
    """Tests for InventoryService PlanMaterial CRUD."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task 1', sort_order=1,
        )

    def test_create_material(self):
        mat = InventoryService.create_plan_material(
            self.plan_task.pk, description='Steel plate',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('15.00'),
        )
        self.assertIsNotNone(mat.pk)
        self.assertEqual(mat.plan_task, self.plan_task)
        self.assertEqual(mat.description, 'Steel plate')

    def test_update_material(self):
        mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task, description='Old', quantity=Decimal('1.00'),
        )
        updated = InventoryService.update_plan_material(
            mat.pk, description='New', quantity=Decimal('3.00'),
        )
        self.assertEqual(updated.description, 'New')
        self.assertEqual(updated.quantity, Decimal('3.00'))

    def test_delete_material(self):
        mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task, description='Delete me', quantity=Decimal('1.00'),
        )
        pk = mat.pk
        InventoryService.delete_plan_material(pk)
        self.assertFalse(PlanMaterial.objects.filter(pk=pk).exists())

    def test_delete_material_not_found(self):
        with self.assertRaises(NotFoundError):
            InventoryService.delete_plan_material(99999)


class JobServicePopulateFromEstimateTest(JobsTestBase):
    """Tests for JobService.populate_from_estimate."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001',
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_converts_line_items_to_tasks(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Cut steel',
            qty=Decimal('2.00'), units='hours', price=Decimal('50.00'),
            accounting_category=self.lit)
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Weld frame',
            qty=Decimal('3.00'), units='hours', price=Decimal('60.00'),
            accounting_category=self.lit)

        JobService.populate_from_estimate(self.job, self.estimate)

        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 2)

    def test_task_fields_from_manual_line_item(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Custom fabrication',
            qty=Decimal('4.00'), units='pcs', price=Decimal('100.00'),
            accounting_category=self.lit)

        JobService.populate_from_estimate(self.job, self.estimate)
        task = Task.objects.get(job=self.job)

        self.assertEqual(task.name, 'Custom fabrication')
        self.assertEqual(task.est_qty, Decimal('4.00'))
        self.assertEqual(task.units, 'pcs')
        self.assertEqual(task.rate, Decimal('100.00'))

    def test_task_from_catalog_line_item(self):
        pli = PriceListItem.objects.create(
            code='STL-001', description='Steel plate',
            units='sheets', selling_price=Decimal('75.00'),
            accounting_category=self.lit)

        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Steel plate',
            price_list_item=pli,
            qty=Decimal('10.00'), units='none', price=Decimal('0.00'),
            accounting_category=self.lit)

        JobService.populate_from_estimate(self.job, self.estimate)
        task = Task.objects.get(job=self.job)

        self.assertIn('STL-001', task.name)
        self.assertEqual(task.units, 'sheets')
        self.assertEqual(task.rate, Decimal('75.00'))

    def test_empty_estimate_populates_no_tasks(self):
        JobService.populate_from_estimate(self.job, self.estimate)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)

    def test_rejects_draft_estimate(self):
        draft_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-DRAFT',
            status=Estimate.STATUS_DRAFT,
        )
        with self.assertRaises(ValidationError):
            JobService.populate_from_estimate(self.job, draft_estimate)

    def test_rejects_rejected_estimate(self):
        rejected_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-REJ',
            status=Estimate.STATUS_REJECTED,
        )
        with self.assertRaises(ValidationError):
            JobService.populate_from_estimate(self.job, rejected_estimate)

    def test_accepts_open_estimate(self):
        open_estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-OPEN',
            status=Estimate.STATUS_OPEN,
        )
        JobService.populate_from_estimate(self.job, open_estimate)
        # No line items, so 0 tasks
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)


class JobServicePopulateFromTemplateTest(JobsTestBase):
    """Tests for JobService.populate_from_template."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.template = WorkTemplate.objects.create(template_name='Standard Build')
        self.task_tmpl_1 = TaskTemplate.objects.create(
            template_name='Cut', units='hours', rate=Decimal('50.00'),
            accounting_category=self.lit)
        self.task_tmpl_2 = TaskTemplate.objects.create(
            template_name='Weld', units='hours', rate=Decimal('60.00'),
            accounting_category=self.lit)
        TemplateTaskAssociation.objects.create(
            work_template=self.template, task_template=self.task_tmpl_1,
            est_qty=Decimal('2.00'), sort_order=1)
        TemplateTaskAssociation.objects.create(
            work_template=self.template, task_template=self.task_tmpl_2,
            est_qty=Decimal('3.00'), sort_order=2)

    def test_links_template_to_job(self):
        JobService.populate_from_template(self.job, self.template)
        self.job.refresh_from_db()
        self.assertEqual(self.job.template, self.template)

    def test_generates_tasks_from_template(self):
        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job).order_by('sort_order')
        self.assertEqual(tasks.count(), 2)

    def test_task_fields_from_template(self):
        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job).order_by('sort_order')

        cut_task = tasks[0]
        self.assertEqual(cut_task.name, 'Cut')
        self.assertEqual(cut_task.units, 'hours')
        self.assertEqual(cut_task.rate, Decimal('50.00'))
        self.assertEqual(cut_task.est_qty, Decimal('2.00'))
        self.assertEqual(cut_task.accounting_category, self.lit)

        weld_task = tasks[1]
        self.assertEqual(weld_task.name, 'Weld')
        self.assertEqual(weld_task.est_qty, Decimal('3.00'))

    def test_skips_inactive_task_templates(self):
        self.task_tmpl_2.is_active = False
        self.task_tmpl_2.save()

        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks[0].name, 'Cut')

    def test_rejects_inactive_template(self):
        self.template.is_active = False
        self.template.save()

        with self.assertRaises(ValidationError):
            JobService.populate_from_template(self.job, self.template)

    def test_template_with_no_associations(self):
        empty_template = WorkTemplate.objects.create(template_name='Empty Template')
        JobService.populate_from_template(self.job, empty_template)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)

    def test_populate_on_approved_job_does_not_validate_status(self):
        """populate_from_template saves via update_fields=['template'] so
        it does not trigger status-transition validation even on a job
        past draft."""
        _walk_to(self.job, Job.STATUS_APPROVED)
        # Should not raise
        JobService.populate_from_template(self.job, self.template)
        self.job.refresh_from_db()
        self.assertEqual(self.job.template, self.template)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)


class JobServiceCopyFromWorksheetTest(JobsTestBase):
    """Tests for JobService.copy_from_worksheet."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001', status=Estimate.STATUS_ACCEPTED)
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate)

    def test_copies_tasks(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', units='hours',
            rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            accounting_category=self.lit, sort_order=1)
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Weld', units='hours',
            rate=Decimal('60.00'), est_qty=Decimal('3.00'),
            accounting_category=self.lit, sort_order=2)

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        job_tasks = Task.objects.filter(job=self.job).order_by('sort_order')
        self.assertEqual(job_tasks.count(), 2)
        self.assertEqual(job_tasks[0].name, 'Cut')
        self.assertEqual(job_tasks[0].rate, Decimal('50.00'))
        self.assertEqual(job_tasks[1].name, 'Weld')
        self.assertEqual(job_tasks[1].est_qty, Decimal('3.00'))

    def test_copies_task_fields(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Paint',
            description='Apply primer and topcoat',
            units='sq ft', rate=Decimal('5.00'), est_qty=Decimal('100.00'),
            accounting_category=self.lit, mapping_strategy='direct', sort_order=1)

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = Task.objects.get(job=self.job)
        self.assertEqual(task.name, 'Paint')
        self.assertEqual(task.description, 'Apply primer and topcoat')
        self.assertEqual(task.units, 'sq ft')
        self.assertEqual(task.accounting_category, self.lit)

    def test_copies_materials(self):
        ws_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1)
        pli = PriceListItem.objects.create(
            code='STL-001', description='Steel plate',
            purchase_price=Decimal('50.00'),
            accounting_category=self.lit)
        PlanMaterial(
            plan_task=ws_task, est_worksheet=self.worksheet,
            price_list_item=pli,
            description='Steel plate', quantity=Decimal('5.00'),
            unit_cost=Decimal('50.00'), sell_price=Decimal('75.00')).save()

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        job_task = Task.objects.get(job=self.job)
        materials = Material.objects.filter(task=job_task)
        self.assertEqual(materials.count(), 1)
        mat = materials[0]
        self.assertEqual(mat.description, 'Steel plate')
        self.assertEqual(mat.quantity, Decimal('5.00'))
        self.assertEqual(mat.unit_cost, Decimal('50.00'))
        self.assertEqual(mat.sell_price, Decimal('75.00'))
        self.assertEqual(mat.price_list_item, pli)

    def test_bundles_are_dropped_on_copy(self):
        """PlanBundles on the worksheet are NOT copied; bundled PlanTasks become flat Tasks."""
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet, name='Assembly',
            sort_order=1, accounting_category=self.lit)
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Assemble part A',
            bundle=bundle, mapping_strategy='bundle', sort_order=1)
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Assemble part B',
            bundle=bundle, mapping_strategy='bundle', sort_order=2)

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        job_tasks = Task.objects.filter(job=self.job).order_by('sort_order')
        self.assertEqual(job_tasks.count(), 2)

    def test_empty_worksheet(self):
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)

    def test_copy_flat_no_parent_task(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Alpha', sort_order=1)
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Beta', sort_order=2)
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        for task in Task.objects.filter(job=self.job):
            self.assertIsNone(task.parent_task)

    def test_copy_preserves_plan_material_pli_linkage(self):
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1)
        pli = PriceListItem.objects.create(
            code='LINK-001', description='Linked item',
            purchase_price=Decimal('10.00'), selling_price=Decimal('20.00'),
            accounting_category=self.lit)
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=plan_task, price_list_item=pli,
            description='Linked', quantity=Decimal('2.00'))
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        job_task = Task.objects.get(job=self.job)
        material = job_task.materials.get()
        self.assertEqual(material.price_list_item, pli)

    def test_job_not_found(self):
        with self.assertRaises(NotFoundError):
            JobService.copy_from_worksheet(99999, self.worksheet.pk)

    def test_worksheet_not_found(self):
        with self.assertRaises(NotFoundError):
            JobService.copy_from_worksheet(self.job.pk, 99999)

    def test_template_arg_sets_job_template(self):
        """Optional template arg is linked onto the job."""
        template = WorkTemplate.objects.create(template_name='Used')
        JobService.copy_from_worksheet(
            self.job.pk, self.worksheet.pk, template=template,
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.template, template)

    def test_no_template_arg_leaves_job_template_none(self):
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.template)
