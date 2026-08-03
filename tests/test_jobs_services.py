"""Tests for jobs app service methods (service-mediated saves)."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService, TaskService
from apps.estimates.models import (
    Estimate,
    WorkTemplate, ServiceItem, TemplateTaskAssociation,
)
from apps.inventory.models import Material, InventoryItem
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError
from apps.core.models import AccountingCategory, User
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
        self.task = Task(
            job=self.job, name='Task 1', sort_order=1,
        )
        self.task.stamp_from_scheme(scheme)
        self.task.save()

    def test_update_task(self):
        updated = TaskService.update_task(self.task.pk, name='Updated Task')
        self.assertEqual(updated.name, 'Updated Task')

    def test_update_task_not_found(self):
        with self.assertRaises(NotFoundError):
            TaskService.update_task(99999, name='Nope')


class HourPairFillTest(JobsTestBase):
    """Task 8: est_qty <-> est_worker_time pair-fill for hour-unit schemes.

    Pair-fill is a convenience, not an invariant: it only fires when exactly
    one of the pair is provided, keys on scheme.unit_label == HOUR_UNIT (not
    algorithm), and never overwrites a value the caller already supplied.
    """

    def setUp(self):
        super().setUp()
        self.job = JobService.create_job(name='Test', contact=self.contact)
        self.hour_scheme = RateScheme.objects.create(
            name='HPF hour scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.lit,
        )
        self.ea_scheme = RateScheme.objects.create(
            name='HPF ea scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='ea',
            accounting_category=self.lit,
        )

    # --- create_direct ---

    def test_hour_scheme_create_derives_worker_time_from_qty(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2.5'))
        self.assertEqual(task.est_worker_time, timedelta(hours=2.5))

    def test_hour_scheme_create_derives_qty_from_worker_time(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_worker_time=timedelta(minutes=90))
        self.assertEqual(task.est_qty, Decimal('1.50'))

    def test_non_hour_scheme_never_pair_fills(self):
        task = TaskService.create_direct(
            self.job, 'Sheets', rate_scheme_id=self.ea_scheme.pk,
            est_qty=Decimal('4'))
        self.assertIsNone(task.est_worker_time)

    def test_hour_scheme_both_provided_passes_through(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('10'), est_worker_time=timedelta(hours=12))
        self.assertEqual(task.est_qty, Decimal('10'))
        self.assertEqual(task.est_worker_time, timedelta(hours=12))

    def test_hour_scheme_derived_worker_time_satisfies_assignee_guard(self):
        """Assigning at create only requires est_worker_time on the fields
        dict — a bare est_qty must derive one BEFORE that guard runs, or an
        hour-scheme task with only a quantity could never be assigned at
        create time."""
        worker = User.objects.create_user(username='hpf_w1', password='x')
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('3'), assignee_id=worker.pk)
        self.assertEqual(task.assignee_id, worker.pk)
        self.assertEqual(task.est_worker_time, timedelta(hours=3))

    # --- update_task ---

    def test_update_qty_alone_resyncs_worker_time(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2'))
        TaskService.update_task(task.pk, est_qty=Decimal('3'))
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=3))

    def test_update_worker_time_alone_resyncs_qty(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2'))
        TaskService.update_task(task.pk, est_worker_time=timedelta(hours=5))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('5.00'))

    def test_update_clearing_qty_does_not_clear_worker_time(self):
        """Clearing est_qty (setting it to None) must not null out an
        already-set est_worker_time — the fill only runs when exactly one
        of the pair is present in kwargs, and it never writes None."""
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2'))
        self.assertEqual(task.est_worker_time, timedelta(hours=2))
        TaskService.update_task(task.pk, est_qty=None)
        task.refresh_from_db()
        self.assertIsNone(task.est_qty)
        self.assertEqual(task.est_worker_time, timedelta(hours=2))

    def test_update_both_provided_passes_through(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2'))
        TaskService.update_task(
            task.pk, est_qty=Decimal('9'), est_worker_time=timedelta(hours=1))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('9'))
        self.assertEqual(task.est_worker_time, timedelta(hours=1))

    def test_update_non_hour_scheme_never_pair_fills(self):
        """A non-hour-scheme task's est_worker_time must survive an
        est_qty-alone update completely unchanged — set it to a value that
        would NOT match a (wrongly) derived one, so this test only passes
        if the unit_label == HOUR_UNIT guard is actually gating the fill,
        not merely because est_worker_time started out None."""
        task = TaskService.create_direct(
            self.job, 'Sheets', rate_scheme_id=self.ea_scheme.pk,
            est_qty=Decimal('4'), est_worker_time=timedelta(hours=99))
        TaskService.update_task(task.pk, est_qty=Decimal('6'))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('6'))
        self.assertEqual(task.est_worker_time, timedelta(hours=99))

    def test_update_unit_label_change_uses_new_unit_for_fill(self):
        """Task-owned money (Phase 1): update_task's pair-fill keys off the
        task's own unit_label — via the `unit_label` kwarg when it's part
        of the same update, else the task's current value — never a
        RateScheme lookup. There is no re-stamp-via-rate_scheme mechanism
        on update_task; `rate_scheme` is a create-only stamp trigger
        (TaskSerializer/TaskService.create_direct), and switching a task's
        billing unit post-creation is a direct unit_label edit."""
        task = TaskService.create_direct(
            self.job, 'Sheets', rate_scheme_id=self.ea_scheme.pk,
            est_qty=Decimal('4'))
        TaskService.update_task(
            task.pk, unit_label=self.hour_scheme.unit_label, est_qty=Decimal('4'))
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=4))

    # --- assign ---

    def test_assign_backfills_qty_when_none(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_worker_time=timedelta(hours=4))
        # est_qty should already be derived at create, so blank it out to
        # exercise assign()'s own back-fill independent of create_direct's.
        task.est_qty = None
        task.save()
        worker = User.objects.create_user(username='hpf_w2', password='x')
        TaskService.assign(task, assignee_id=worker.pk,
                            est_worker_time=timedelta(hours=6))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('6.00'))

    def test_assign_does_not_overwrite_existing_qty(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2'), est_worker_time=timedelta(hours=2))
        worker = User.objects.create_user(username='hpf_w3', password='x')
        TaskService.assign(task, assignee_id=worker.pk,
                            est_worker_time=timedelta(hours=9))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertEqual(task.est_worker_time, timedelta(hours=9))


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
        self.t1 = Task(
            job=self.job, name='Task 1', sort_order=1,
        )
        self.t1.stamp_from_scheme(scheme)
        self.t1.save()
        self.t2 = Task(
            job=self.job, name='Task 2', sort_order=2,
        )
        self.t2.stamp_from_scheme(scheme)
        self.t2.save()

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
        self.assertEqual(cut_task.source_scheme, self.scheme)

        weld_task = tasks[1]
        self.assertEqual(weld_task.name, 'Weld')
        self.assertEqual(weld_task.source_scheme, self.scheme)

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

    def test_template_task_derives_worker_time_for_hour_scheme(self):
        """Task 8: the fixture scheme (pk=1) is unit_label='hour' — template
        associations only carry est_qty, so generate_task's pair-fill is what
        makes template-generated tasks schedulable."""
        JobService.populate_from_template(self.job, self.template)
        cut_task = Task.objects.get(job=self.job, name='Cut')
        self.assertEqual(cut_task.est_worker_time, timedelta(hours=2))
