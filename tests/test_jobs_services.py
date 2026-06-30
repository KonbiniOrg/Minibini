"""Tests for jobs app service methods (service-mediated saves)."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.jobs.services import JobService, TaskService
from apps.estimates.models import (
    Estimate, EstWorksheet,
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
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
            name='TSU scheme', algorithm=RateScheme.ENTERED_QTY,
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
            name='TSR scheme', algorithm=RateScheme.ENTERED_QTY,
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


class JobServicePopulateFromTemplateTest(JobsTestBase):
    """Tests for JobService.populate_from_template."""

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.template = WorkTemplate.objects.create(template_name='Standard Build')
        self.scheme = RateScheme.objects.get(pk=1)  # from fixture
        self.task_tmpl_1 = ServiceItem.objects.create(
            template_name='Cut',
            rate_scheme=self.scheme)
        self.task_tmpl_2 = ServiceItem.objects.create(
            template_name='Weld',
            rate_scheme=self.scheme)
        TemplateTaskAssociation.objects.create(
            work_template=self.template, service_item=self.task_tmpl_1,
            est_qty=Decimal('2.00'), sort_order=1)
        TemplateTaskAssociation.objects.create(
            work_template=self.template, service_item=self.task_tmpl_2,
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

    def test_skips_inactive_service_items(self):
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
