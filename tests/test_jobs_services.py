"""Tests for jobs app service methods (service-mediated saves)."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.jobs.services import JobService, TaskService
from apps.estimates.models import (
    Estimate, EstWorksheet,
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.inventory.models import Material, PlanMaterial, InventoryItem
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
        Job.STATUS_IN_PROGRESS: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS],
        Job.STATUS_WORK_COMPLETE: [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE,
        ],
        Job.STATUS_COMPLETED: [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
            Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED,
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

    def test_update_status_noop_fires_no_side_effects(self):
        """Setting a job to its current status returns it unchanged and fires
        no status-transition side effects (the consolidated update_job no
        longer short-circuits the save, but that save is a harmless no-op)."""
        _walk_to(self.job, Job.STATUS_WORK_COMPLETE)

        with patch(
            'apps.inventory.services.InventoryService.release_earmarks_for_job'
        ) as mock_release:
            result = JobService.update_status(self.job.pk, Job.STATUS_WORK_COMPLETE)

        self.assertEqual(result.status, Job.STATUS_WORK_COMPLETE)
        mock_release.assert_not_called()

    def test_update_status_fires_release_on_transition_into_work_complete(self):
        _walk_to(self.job, Job.STATUS_IN_PROGRESS)

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
        scheme = RateScheme.objects.create(
            name='TSU scheme', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='ea',
            accounting_category=self.lit,
        )
        self.task = Task.objects.create(
            job=self.job, name='Task 1', sort_order=1,
            rate_scheme=scheme,
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
        scheme = RateScheme.objects.create(
            name='TSR scheme', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='ea',
            accounting_category=self.lit,
        )
        self.t1 = Task.objects.create(
            job=self.job, name='Task 1', sort_order=1,
            rate_scheme=scheme,
        )
        self.t2 = Task.objects.create(
            job=self.job, name='Task 2', sort_order=2,
            rate_scheme=scheme,
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
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Task 1', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )

    def test_create_material(self):
        mat = InventoryService.create_plan_material(
            self.plan_task.pk, description='Steel plate',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('15.00'), accounting_category=self.lit,
        )
        self.assertIsNotNone(mat.pk)
        self.assertEqual(mat.plan_task, self.plan_task)
        self.assertEqual(mat.description, 'Steel plate')

    def test_update_material(self):
        mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task, description='Old', quantity=Decimal('1.00'),
            accounting_category=self.lit,
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
            accounting_category=self.lit,
        )
        pk = mat.pk
        InventoryService.delete_plan_material(pk)
        self.assertFalse(PlanMaterial.objects.filter(pk=pk).exists())

    def test_delete_material_not_found(self):
        with self.assertRaises(NotFoundError):
            InventoryService.delete_plan_material(99999)


class JobServicePopulateFromTemplateTest(JobsTestBase):
    """Tests for JobService.populate_from_template."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.template = WorkTemplate.objects.create(template_name='Standard Build')
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture
        self.task_tmpl_1 = TaskTemplate.objects.create(
            template_name='Cut',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'))
        self.task_tmpl_2 = TaskTemplate.objects.create(
            template_name='Weld',
            rate_scheme=self.scheme, default_billable_qty=Decimal('1.00'))
        TemplateTaskAssociation.objects.create(
            work_template=self.template, task_template=self.task_tmpl_1,
            est_qty=Decimal('2.00'), sort_order=1)
        TemplateTaskAssociation.objects.create(
            work_template=self.template, task_template=self.task_tmpl_2,
            est_qty=Decimal('3.00'), sort_order=2)

    def test_generates_tasks_from_template(self):
        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job).order_by('sort_order')
        self.assertEqual(tasks.count(), 2)

    def test_task_fields_from_template(self):
        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job).order_by('sort_order')

        cut_task = tasks[0]
        self.assertEqual(cut_task.name, 'Cut')
        self.assertEqual(cut_task.rate_scheme, self.scheme)

        weld_task = tasks[1]
        self.assertEqual(weld_task.name, 'Weld')
        self.assertEqual(weld_task.rate_scheme, self.scheme)

    def test_skips_inactive_task_templates(self):
        self.task_tmpl_2.is_active = False
        self.task_tmpl_2.save()

        JobService.populate_from_template(self.job, self.template)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks[0].name, 'Cut')

    def test_template_with_no_associations(self):
        empty_template = WorkTemplate.objects.create(template_name='Empty Template')
        JobService.populate_from_template(self.job, empty_template)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)

    def test_populate_on_approved_job_does_not_validate_status(self):
        """populate_from_template creates tasks without changing the job's
        status, so it works even on a job past draft."""
        _walk_to(self.job, Job.STATUS_APPROVED)
        # Should not raise
        JobService.populate_from_template(self.job, self.template)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)
        self.assertGreater(Task.objects.filter(job=self.job).count(), 0)


class JobServiceCopyFromWorksheetTest(JobsTestBase):
    """Tests for JobService.copy_from_worksheet."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001', status=Estimate.STATUS_ACCEPTED)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture

    def test_copies_tasks(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Weld', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'))

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        job_tasks = Task.objects.filter(job=self.job).order_by('sort_order')
        self.assertEqual(job_tasks.count(), 2)
        self.assertEqual(job_tasks[0].name, 'Cut')
        self.assertEqual(job_tasks[1].name, 'Weld')

    def test_copies_task_fields(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Paint',
            description='Apply primer and topcoat',
            sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = Task.objects.get(job=self.job)
        self.assertEqual(task.name, 'Paint')
        self.assertEqual(task.description, 'Apply primer and topcoat')

    def test_copies_materials(self):
        ws_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        pli = InventoryItem.objects.create(
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

    def test_empty_worksheet(self):
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)

    def test_copy_flat_no_parent_task(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Alpha', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Beta', sort_order=2,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        for task in Task.objects.filter(job=self.job):
            self.assertIsNone(task.parent_task)

    def test_copy_preserves_plan_material_pli_linkage(self):
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        pli = InventoryItem.objects.create(
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

    def test_copy_from_worksheet_carries_units(self):
        """Units set on PlanMaterial are preserved on the resulting Material."""
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=plan_task,
            description='task-attached', quantity=Decimal('5'),
            units='lbs', unit_cost=Decimal('2.00'), sell_price=Decimal('3.00'),
            accounting_category=self.lit)
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=None,
            description='task-less', quantity=Decimal('2'),
            units='ea', unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
            accounting_category=self.lit)

        new_job = JobService.create_job(name='Copy Target', contact=self.contact)
        JobService.copy_from_worksheet(new_job.pk, self.worksheet.pk)

        task_mat = Material.objects.get(job=new_job, task__isnull=False)
        self.assertEqual(task_mat.units, 'lbs')
        loose_mat = Material.objects.get(job=new_job, task__isnull=True)
        self.assertEqual(loose_mat.units, 'ea')

    def test_sets_provenance_on_copied_atoms(self):
        pt = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=pt, description='Steel',
            quantity=Decimal('2'), units='ea', accounting_category=self.lit)

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = Task.objects.get(job=self.job)
        self.assertEqual(task.source_plan_task, pt)
        material = Material.objects.get(job=self.job)
        self.assertEqual(material.source_plan_material.plan_task, pt)

    def test_manual_copy_then_acceptance_does_not_duplicate(self):
        from apps.estimates.carry_over import AtomCarryOverService
        PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut', sort_order=1,
            rate_scheme=self.scheme, est_qty=Decimal('1'))

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)
        AtomCarryOverService.carry_over_for_estimate(self.estimate)

        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
