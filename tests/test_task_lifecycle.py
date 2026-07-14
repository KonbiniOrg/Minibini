from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import TaskLifecycleService
from apps.core.models import User


def _approve_job(job):
    """Walk a fixture job to APPROVED status."""
    for step in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        if job.status != step:
            job.status = step
            job.save()


def _log_time(task, user=None):
    """Give a task a closed Blep so an elapsed-time task has recorded time."""
    now = timezone.now()
    if user is None:
        user = User.objects.first()
    Blep.objects.create(
        task=task, user=user, start_time=now - timedelta(hours=1), end_time=now,
    )


class TaskStatusFieldTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()

    def test_task_default_status_is_pending(self):
        task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        self.assertEqual(task.status, Task.STATUS_PENDING)

    def test_task_status_choices(self):
        expected = [
            (Task.STATUS_PENDING, 'Pending'),
            (Task.STATUS_IN_PROGRESS, 'In Progress'),
            (Task.STATUS_BLOCKED, 'Blocked'),
            (Task.STATUS_COMPLETE, 'Complete'),
            (Task.STATUS_CANCELLED, 'Cancelled'),
        ]
        self.assertEqual(Task.TASK_STATUS_CHOICES, expected)


class TaskTransitionValidationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()

    def _create_task_with_status(self, status):
        task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    # Valid transitions
    def test_pending_to_in_progress(self):
        task = self._create_task_with_status(Task.STATUS_PENDING)
        task.status = Task.STATUS_IN_PROGRESS
        task.full_clean()

    def test_pending_to_blocked(self):
        task = self._create_task_with_status(Task.STATUS_PENDING)
        task.status = Task.STATUS_BLOCKED
        task.full_clean()

    def test_pending_to_complete(self):
        task = self._create_task_with_status(Task.STATUS_PENDING)
        task.status = Task.STATUS_COMPLETE
        task.full_clean()

    def test_pending_to_cancelled(self):
        task = self._create_task_with_status(Task.STATUS_PENDING)
        task.status = Task.STATUS_CANCELLED
        task.full_clean()

    def test_in_progress_to_blocked(self):
        task = self._create_task_with_status(Task.STATUS_IN_PROGRESS)
        task.status = Task.STATUS_BLOCKED
        task.full_clean()

    def test_in_progress_to_complete(self):
        task = self._create_task_with_status(Task.STATUS_IN_PROGRESS)
        task.status = Task.STATUS_COMPLETE
        task.full_clean()

    def test_in_progress_to_cancelled(self):
        task = self._create_task_with_status(Task.STATUS_IN_PROGRESS)
        task.status = Task.STATUS_CANCELLED
        task.full_clean()

    def test_blocked_to_in_progress(self):
        task = self._create_task_with_status(Task.STATUS_BLOCKED)
        task.status = Task.STATUS_IN_PROGRESS
        task.full_clean()

    def test_blocked_to_cancelled(self):
        task = self._create_task_with_status(Task.STATUS_BLOCKED)
        task.status = Task.STATUS_CANCELLED
        task.full_clean()

    def test_blocked_to_complete(self):
        task = self._create_task_with_status(Task.STATUS_BLOCKED)
        task.status = Task.STATUS_COMPLETE
        task.full_clean()

    # Invalid transitions
    def test_complete_to_in_progress_raises(self):
        task = self._create_task_with_status(Task.STATUS_COMPLETE)
        task.status = Task.STATUS_IN_PROGRESS
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_cancelled_to_in_progress_raises(self):
        task = self._create_task_with_status(Task.STATUS_CANCELLED)
        task.status = Task.STATUS_IN_PROGRESS
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_in_progress_to_pending_raises(self):
        task = self._create_task_with_status(Task.STATUS_IN_PROGRESS)
        task.status = Task.STATUS_PENDING
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_new_task_no_transition_validation(self):
        """New task (no pk) should not trigger transition validation."""
        task = Task(name='New Task', job=self.job, status=Task.STATUS_IN_PROGRESS, rate_scheme_id=1)
        task.full_clean()


class StartWorkOnPendingTaskTest(BaseTestCase):
    """start_work on a pending task promotes it and consumes materials."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        self.user = User.objects.get(username='admin')

    def test_start_work_promotes_pending_to_in_progress(self):
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_start_work_creates_blep(self):
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        blep = result['blep']
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.task, self.task)

    def test_start_work_rejects_terminal_status(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.user)

    def test_start_work_closes_users_other_open_blep(self):
        other_task = Task.objects.create(name='Other Task', job=self.job, rate_scheme_id=1)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Over-minimum so it is CLOSED (not cancelled) when start_work switches tasks.
        old_blep = Blep.objects.create(
            task=other_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30)
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    @patch('apps.inventory.services.MaterialService.consume')
    def test_start_work_consumes_materials_on_first_start(self, mock_consume):
        from apps.inventory.models import Material
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first()
        mat = Material.objects.create(
            job=self.job, task=self.task, description='Test Material',
            accounting_category=cat,
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        mock_consume.assert_called_once_with(mat)

    def test_task_start_blocks_on_provisional_material(self):
        """Starting a task whose material is provisional (no inventory_item)
        now REFUSES — the promote-time consumption sweep raises rather than
        silently flipping a not-yet-priced material to consumed. The atomic
        start_work rolls back, leaving task and material pending.
        """
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import Earmark, Material
        cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False},
        )[0]
        mat = Material.objects.create(
            job=self.job, task=self.task,
            inventory_item=None,
            accounting_category=cat,
            description='no-item',
            quantity=Decimal('2.00'),
        )
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)

        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.user)

        mat.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        self.assertFalse(
            Earmark.objects.filter(job=self.job).exists()
        )

    def test_start_work_assigns_user_when_no_assignee(self):
        self.assertIsNone(self.task.assignee)
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.user)

    def test_start_work_preserves_existing_assignee(self):
        other_user = User.objects.create_user(username='other', password='test')
        self.task.assignee = other_user
        self.task.est_worker_time = timedelta(hours=1)
        self.task.save()
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, other_user)


class OnBehalfStartStopTest(BaseTestCase):
    """A manager (can_manage_time) can start/stop work on behalf of another
    worker; the blep is attributed to that worker. Without can_manage_time,
    acting on another user's behalf is rejected."""

    def setUp(self):
        super().setUp()
        from apps.jobs.services import BlepPermissionError
        from django.contrib.auth.models import Permission
        self.BlepPermissionError = BlepPermissionError
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='OB Task', job=self.job, rate_scheme_id=1)
        self.manager = User.objects.get(username='admin')
        perm = Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core',
        )
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)  # refresh perm cache
        self.worker = User.objects.create_user(username='ob_worker', password='x')
        self.plain = User.objects.create_user(username='ob_plain', password='x')

    def test_start_on_behalf_creates_blep_for_target_and_runs_lifecycle(self):
        result = TaskLifecycleService.start_work(
            self.task.pk, self.manager, on_behalf_of=self.worker,
        )
        blep = result['blep']
        self.assertEqual(blep.user, self.worker)
        self.assertIsNone(blep.end_time)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        self.assertEqual(self.task.assignee, self.worker)

    def test_start_on_behalf_requires_manage_time(self):
        with self.assertRaises(self.BlepPermissionError):
            TaskLifecycleService.start_work(
                self.task.pk, self.plain, on_behalf_of=self.worker,
            )

    def test_stop_on_behalf_closes_targets_open_blep(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Over-minimum so the manager's on-behalf stop CLOSES it (not cancels).
        blep = Blep.objects.create(
            task=self.task, user=self.worker,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        TaskLifecycleService.stop_work(
            self.task.pk, self.manager, on_behalf_of=self.worker,
        )
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_on_behalf_requires_manage_time(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=self.task, user=self.worker, start_time=timezone.now(),
        )
        with self.assertRaises(self.BlepPermissionError):
            TaskLifecycleService.stop_work(
                self.task.pk, self.plain, on_behalf_of=self.worker,
            )

    def test_stop_on_behalf_leaves_actors_own_blep_alone(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # worker_blep is over-minimum so it is CLOSED (not cancelled) on stop.
        worker_blep = Blep.objects.create(
            task=self.task, user=self.worker,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        manager_blep = Blep.objects.create(
            task=self.task, user=self.manager, start_time=timezone.now(),
        )
        TaskLifecycleService.stop_work(
            self.task.pk, self.manager, on_behalf_of=self.worker,
        )
        worker_blep.refresh_from_db()
        manager_blep.refresh_from_db()
        self.assertIsNotNone(worker_blep.end_time)
        self.assertIsNone(manager_blep.end_time)


class CompleteTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        _log_time(self.task)
        self.user = User.objects.get(username='admin')

    def test_complete_from_in_progress(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_complete_from_pending(self):
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_complete_closes_open_bleps(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        # Over-minimum so completing the task CLOSES it (not cancels).
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30)
        )
        TaskLifecycleService.complete_task(self.task.pk)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_complete_from_blocked(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_complete_from_blocked_clears_reason(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_BLOCKED, blocked_reason='Waiting on parts'
        )
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, '')


class JobAutoWorkCompleteTest(BaseTestCase):
    """Auto-advance of Job -> work_complete when all tasks reach terminal states."""

    def setUp(self):
        super().setUp()
        fixture_job = Job.objects.first()
        self.job = Job.objects.create(
            job_number='J-AUTO-001',
            contact=fixture_job.contact,
        )
        _approve_job(self.job)
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        _log_time(self.task)
        self.user = User.objects.get(username='admin')

    def test_complete_last_task_on_approved_job_advances_to_work_complete(self):
        TaskLifecycleService.complete_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_complete_with_others_remaining_advances_to_in_progress(self):
        """Completing one task of several advances APPROVED→IN_PROGRESS
        (Bug 1: work has started) but not all the way to WORK_COMPLETE."""
        Task.objects.create(name='Other Task', job=self.job, rate_scheme_id=1)
        TaskLifecycleService.complete_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_complete_with_cancelled_siblings_advances(self):
        other = Task.objects.create(name='Other Task', job=self.job, rate_scheme_id=1)
        Task.objects.filter(pk=other.pk).update(status=Task.STATUS_CANCELLED)
        TaskLifecycleService.complete_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_cancel_last_pending_task_on_approved_job_advances(self):
        """Cancelling the last pending task auto-advances to work_complete."""
        TaskLifecycleService.cancel_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_no_auto_advance_when_job_not_approved(self):
        """Completing the last task on a DRAFT job does NOT change job status."""
        job2 = Job.objects.create(
            job_number='J-AUTO-DRAFT', contact=self.job.contact,
        )
        self.assertEqual(job2.status, Job.STATUS_DRAFT)
        task = Task.objects.create(name='DraftTask', job=job2, rate_scheme_id=1)
        _log_time(task)
        TaskLifecycleService.complete_task(task.pk)
        job2.refresh_from_db()
        self.assertEqual(job2.status, Job.STATUS_DRAFT)

    def test_no_auto_advance_when_job_already_work_complete(self):
        """A job already in work_complete does not get mutated by task completion."""
        # Walk the job to work_complete via valid transitions.
        self.job.status = Job.STATUS_IN_PROGRESS
        self.job.save()
        self.job.status = Job.STATUS_WORK_COMPLETE
        self.job.save()
        # Create another task somehow (bypass the expectation by updating status
        # directly). Then complete it: the _check_job_work_complete guard only
        # fires when job.status == APPROVED or IN_PROGRESS, so this is a no-op.
        other = Task.objects.create(name='Extra', job=self.job, rate_scheme_id=1)
        _log_time(other)
        with patch(
            'apps.jobs.services.JobService.update_status'
        ) as mock_update:
            TaskLifecycleService.complete_task(other.pk)
        mock_update.assert_not_called()


class CompleteTaskActualQtyTest(BaseTestCase):
    """An ENTERED_QTY task needs a worker-entered quantity (> 0) before it
    can be completed. Fixture rate schemes: 1=elapsed_time, 2=entered_qty."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.entered_qty_task = Task.objects.create(
            name='CNC job', job=self.job, rate_scheme_id=2,
        )
        self.elapsed_task = Task.objects.create(
            name='Labor', job=self.job, rate_scheme_id=1,
        )
        _log_time(self.elapsed_task)

    def test_entered_qty_task_without_add_qty_raises(self):
        from apps.jobs.services import TaskActualQtyRequired
        with self.assertRaises(TaskActualQtyRequired):
            TaskLifecycleService.complete_task(self.entered_qty_task.pk)

    def test_prompt_carries_unit_label_and_current_qty(self):
        from decimal import Decimal
        from apps.jobs.services import TaskActualQtyRequired
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('9'),
        )
        with self.assertRaises(TaskActualQtyRequired) as ctx:
            TaskLifecycleService.complete_task(self.entered_qty_task.pk)
        self.assertEqual(ctx.exception.current_qty, Decimal('9'))
        self.assertTrue(ctx.exception.unit_label)

    def test_entered_qty_task_completes_with_add_qty_from_null(self):
        from decimal import Decimal
        TaskLifecycleService.complete_task(
            self.entered_qty_task.pk, add_qty=Decimal('5'),
        )
        self.entered_qty_task.refresh_from_db()
        self.assertEqual(self.entered_qty_task.status, Task.STATUS_COMPLETE)
        self.assertEqual(self.entered_qty_task.actual_qty, Decimal('5'))

    def test_add_qty_increments_existing_total(self):
        from decimal import Decimal
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('9'),
        )
        TaskLifecycleService.complete_task(
            self.entered_qty_task.pk, add_qty=Decimal('5'),
        )
        self.entered_qty_task.refresh_from_db()
        self.assertEqual(self.entered_qty_task.actual_qty, Decimal('14'))

    def test_entered_qty_task_with_existing_value_still_prompts(self):
        """Settle-up: completion ALWAYS round-trips through the prompt,
        even when a total is already on record."""
        from decimal import Decimal
        from apps.jobs.services import TaskActualQtyRequired
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('3'),
        )
        with self.assertRaises(TaskActualQtyRequired):
            TaskLifecycleService.complete_task(self.entered_qty_task.pk)

    def test_zero_add_qty_completes_when_total_positive(self):
        from decimal import Decimal
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('3'),
        )
        TaskLifecycleService.complete_task(
            self.entered_qty_task.pk, add_qty=Decimal('0'),
        )
        self.entered_qty_task.refresh_from_db()
        self.assertEqual(self.entered_qty_task.status, Task.STATUS_COMPLETE)
        self.assertEqual(self.entered_qty_task.actual_qty, Decimal('3'))

    def test_negative_add_qty_corrects_at_completion(self):
        from decimal import Decimal
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('9'),
        )
        TaskLifecycleService.complete_task(
            self.entered_qty_task.pk, add_qty=Decimal('-2'),
        )
        self.entered_qty_task.refresh_from_db()
        self.assertEqual(self.entered_qty_task.actual_qty, Decimal('7'))

    def test_zero_add_qty_with_no_total_rejected(self):
        from decimal import Decimal
        with self.assertRaises(ValidationError):
            TaskLifecycleService.complete_task(
                self.entered_qty_task.pk, add_qty=Decimal('0'),
            )

    def test_add_qty_taking_final_to_zero_rejected(self):
        from decimal import Decimal
        Task.objects.filter(pk=self.entered_qty_task.pk).update(
            actual_qty=Decimal('3'),
        )
        with self.assertRaises(ValidationError):
            TaskLifecycleService.complete_task(
                self.entered_qty_task.pk, add_qty=Decimal('-3'),
            )
        self.entered_qty_task.refresh_from_db()
        self.assertNotEqual(self.entered_qty_task.status, Task.STATUS_COMPLETE)

    def test_elapsed_time_task_with_logged_time_completes(self):
        # self.elapsed_task has a blep from setUp — no actual_qty param needed.
        TaskLifecycleService.complete_task(self.elapsed_task.pk)
        self.elapsed_task.refresh_from_db()
        self.assertEqual(self.elapsed_task.status, Task.STATUS_COMPLETE)

    def test_elapsed_time_task_without_logged_time_raises(self):
        from apps.jobs.services import TaskTimeRequired
        untracked = Task.objects.create(
            name='Untracked', job=self.job, rate_scheme_id=1,
        )
        with self.assertRaises(TaskTimeRequired):
            TaskLifecycleService.complete_task(untracked.pk)


class AddActualQtyTest(BaseTestCase):
    """TaskLifecycleService.add_actual_qty applies a signed increment to
    Task.actual_qty. Every mid-work write is an add — there is no replace.
    Fixture rate schemes: 1=elapsed_time, 2=entered_qty."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        self.Decimal = Decimal
        self.job = Job.objects.first()
        self.task = Task.objects.create(
            name='Press parts', job=self.job, rate_scheme_id=2,
        )
        self.elapsed_task = Task.objects.create(
            name='Labor', job=self.job, rate_scheme_id=1,
        )

    def test_add_from_null_starts_total(self):
        TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('5'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, self.Decimal('5'))

    def test_add_onto_existing_accumulates(self):
        Task.objects.filter(pk=self.task.pk).update(
            actual_qty=self.Decimal('9'))
        TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('5'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, self.Decimal('14'))

    def test_negative_delta_subtracts(self):
        Task.objects.filter(pk=self.task.pk).update(
            actual_qty=self.Decimal('50'))
        TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('-45'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, self.Decimal('5'))

    def test_zero_delta_rejected(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('0'))

    def test_delta_taking_total_below_zero_rejected(self):
        Task.objects.filter(pk=self.task.pk).update(
            actual_qty=self.Decimal('3'))
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('-4'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, self.Decimal('3'))

    def test_non_decimal_rejected(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(self.task.pk, 'garbage')

    def test_wrong_scheme_rejected(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(
                self.elapsed_task.pk, self.Decimal('5'))

    def test_complete_task_rejected(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_COMPLETE, actual_qty=self.Decimal('5'))
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('1'))

    def test_cancelled_task_rejected(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_CANCELLED)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('1'))

    def test_sequential_adds_sum(self):
        TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('2'))
        TaskLifecycleService.add_actual_qty(self.task.pk, self.Decimal('3.5'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, self.Decimal('5.5'))

    def test_returns_task_with_new_total(self):
        task = TaskLifecycleService.add_actual_qty(
            self.task.pk, self.Decimal('7'))
        self.assertEqual(task.actual_qty, self.Decimal('7'))


class PriorSessionQtyStartWorkTest(BaseTestCase):
    """Starting work while holding an open blep on an ENTERED_QTY task
    returns a prior_session_qty conflict (own gesture only) so the SPA can
    settle the old session first. Fixture schemes: 1=elapsed, 2=entered."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        self.Decimal = Decimal
        self.user = User.objects.first()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.eq_task = Task.objects.create(
            name='CNC', job=self.job, rate_scheme_id=2,
        )
        Task.objects.filter(pk=self.eq_task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        self.prior_blep = Blep.objects.create(
            task=self.eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        self.new_task = Task.objects.create(
            name='Sanding', job=self.job, rate_scheme_id=1,
        )

    def test_own_start_prompts_for_prior_session(self):
        result = TaskLifecycleService.start_work(self.new_task.pk, self.user)
        self.assertEqual(result.get('conflict'), 'prior_session_qty')
        self.assertEqual(result['prior_task']['task_id'], self.eq_task.pk)
        self.assertEqual(result['prior_task']['name'], 'CNC')
        self.assertEqual(result['unit_label'], 'minute')
        self.assertEqual(
            self.Decimal(result['current_qty']), self.Decimal('9'))
        # Nothing mutated: old blep open, no new blep.
        self.prior_blep.refresh_from_db()
        self.assertIsNone(self.prior_blep.end_time)
        self.assertFalse(
            Blep.objects.filter(task=self.new_task).exists())

    def test_flag_proceeds_and_closes_prior(self):
        result = TaskLifecycleService.start_work(
            self.new_task.pk, self.user, prior_qty_handled=True)
        self.assertIn('blep', result)
        self.prior_blep.refresh_from_db()
        self.assertIsNotNone(self.prior_blep.end_time)

    def test_elapsed_prior_does_not_prompt(self):
        # Swap the prior session onto an elapsed-time task.
        self.prior_blep.delete()
        elapsed_prior = Task.objects.create(
            name='Labor', job=self.job, rate_scheme_id=1,
        )
        Task.objects.filter(pk=elapsed_prior.pk).update(
            status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=elapsed_prior, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        result = TaskLifecycleService.start_work(self.new_task.pk, self.user)
        self.assertIn('blep', result)

    def test_on_behalf_start_does_not_prompt(self):
        from tests.base import grant_atoms
        manager = User.objects.create_user(username='psq_mgr', password='x')
        manager = grant_atoms(manager, 'can_manage_time')
        result = TaskLifecycleService.start_work(
            self.new_task.pk, manager, on_behalf_of=self.user)
        self.assertIn('blep', result)
        self.prior_blep.refresh_from_db()
        self.assertIsNotNone(self.prior_blep.end_time)

    def test_same_task_restart_does_not_prompt(self):
        result = TaskLifecycleService.start_work(self.eq_task.pk, self.user)
        self.assertIn('blep', result)

    def test_prior_prompt_evaluated_before_active_worker(self):
        other = User.objects.create_user(username='psq_other', password='x')
        Task.objects.filter(pk=self.new_task.pk).update(
            status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=self.new_task, user=other, start_time=timezone.now())
        first = TaskLifecycleService.start_work(self.new_task.pk, self.user)
        self.assertEqual(first.get('conflict'), 'prior_session_qty')
        second = TaskLifecycleService.start_work(
            self.new_task.pk, self.user, prior_qty_handled=True)
        self.assertEqual(second.get('conflict'), 'active_worker')


class CancelTaskPriorSessionTest(BaseTestCase):
    """Cancelling a task retains recorded quantities just as it retains
    bleps (parity with elapsed-time tasks, whose closed bleps survive
    cancellation). So the canceller's own open ENTERED_QTY session gets a
    skippable prior_session_qty offer before the task settles. Internal
    callers (CO acceptance) pass no user and never prompt."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        self.Decimal = Decimal
        self.user = User.objects.first()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.eq_task = Task.objects.create(
            name='CNC', job=self.job, rate_scheme_id=2,
        )
        Task.objects.filter(pk=self.eq_task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        self.blep = Blep.objects.create(
            task=self.eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )

    def test_own_open_session_prompts_and_mutates_nothing(self):
        result = TaskLifecycleService.cancel_task(
            self.eq_task.pk, user=self.user)
        self.assertEqual(result.get('conflict'), 'prior_session_qty')
        self.assertEqual(result['prior_task']['task_id'], self.eq_task.pk)
        self.assertEqual(
            self.Decimal(result['current_qty']), self.Decimal('9'))
        self.eq_task.refresh_from_db()
        self.assertEqual(self.eq_task.status, Task.STATUS_IN_PROGRESS)
        self.blep.refresh_from_db()
        self.assertIsNone(self.blep.end_time)

    def test_flag_proceeds_with_cancel(self):
        result = TaskLifecycleService.cancel_task(
            self.eq_task.pk, user=self.user, prior_qty_handled=True)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)
        self.blep.refresh_from_db()
        self.assertIsNotNone(self.blep.end_time)

    def test_no_user_never_prompts(self):
        """Internal bulk callers (change-order acceptance) pass no user."""
        result = TaskLifecycleService.cancel_task(self.eq_task.pk)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)

    def test_elapsed_task_never_prompts(self):
        elapsed = Task.objects.create(
            name='Labor', job=self.job, rate_scheme_id=1,
        )
        Task.objects.filter(pk=elapsed.pk).update(
            status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=elapsed, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        result = TaskLifecycleService.cancel_task(elapsed.pk, user=self.user)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)

    def test_other_workers_session_never_prompts(self):
        """A manager cancelling a task someone else is working doesn't know
        the count — their session closes silently (same as complete)."""
        other = User.objects.create_user(username='ctps_other', password='x')
        self.blep.delete()
        Blep.objects.create(
            task=self.eq_task, user=other,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        result = TaskLifecycleService.cancel_task(
            self.eq_task.pk, user=self.user)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)


class BlockTaskOwnSessionTest(BaseTestCase):
    """Blocking is how a worker records "I can't proceed" — usually
    discovered mid-session, so the requester's OWN open blep must not veto
    the block. It resolves like every other own-gesture (settle-first on
    ENTERED_QTY, plain close otherwise); only OTHER workers' open sessions
    keep the active_workers refusal."""

    def setUp(self):
        super().setUp()
        from decimal import Decimal
        self.Decimal = Decimal
        self.user = User.objects.first()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.eq_task = Task.objects.create(
            name='CNC', job=self.job, rate_scheme_id=2,
        )
        Task.objects.filter(pk=self.eq_task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        self.blep = Blep.objects.create(
            task=self.eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )

    def test_own_entered_qty_session_prompts_and_mutates_nothing(self):
        result = TaskLifecycleService.block_task(
            self.eq_task.pk, reason='saw blade broke', user=self.user)
        self.assertEqual(result.get('conflict'), 'prior_session_qty')
        self.assertEqual(result['prior_task']['task_id'], self.eq_task.pk)
        self.assertEqual(
            self.Decimal(result['current_qty']), self.Decimal('9'))
        self.eq_task.refresh_from_db()
        self.assertEqual(self.eq_task.status, Task.STATUS_IN_PROGRESS)
        self.blep.refresh_from_db()
        self.assertIsNone(self.blep.end_time)

    def test_flag_proceeds_with_block_and_closes_own_session(self):
        result = TaskLifecycleService.block_task(
            self.eq_task.pk, reason='saw blade broke',
            user=self.user, prior_qty_handled=True)
        self.assertEqual(result.status, Task.STATUS_BLOCKED)
        self.eq_task.refresh_from_db()
        self.assertEqual(self.eq_task.status, Task.STATUS_BLOCKED)
        self.assertEqual(self.eq_task.blocked_reason, 'saw blade broke')
        self.blep.refresh_from_db()
        self.assertIsNotNone(self.blep.end_time)

    def test_own_elapsed_session_blocks_without_prompt(self):
        elapsed = Task.objects.create(
            name='Labor', job=self.job, rate_scheme_id=1,
        )
        Task.objects.filter(pk=elapsed.pk).update(
            status=Task.STATUS_IN_PROGRESS)
        blep = Blep.objects.create(
            task=elapsed, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        result = TaskLifecycleService.block_task(
            elapsed.pk, reason='waiting on parts', user=self.user)
        self.assertEqual(result.status, Task.STATUS_BLOCKED)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_other_workers_session_still_refuses(self):
        other = User.objects.create_user(username='btos_other', password='x')
        other_blep = Blep.objects.create(
            task=self.eq_task, user=other,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        result = TaskLifecycleService.block_task(
            self.eq_task.pk, reason='x', user=self.user)
        self.assertEqual(result.get('conflict'), 'active_workers')
        # Only the OTHER worker is listed — the requester's own session
        # is not a conflict.
        listed = [w['user_id'] for w in result['workers']]
        self.assertEqual(listed, [other.pk])
        self.eq_task.refresh_from_db()
        self.assertEqual(self.eq_task.status, Task.STATUS_IN_PROGRESS)
        # Nothing closed on either session.
        self.blep.refresh_from_db()
        other_blep.refresh_from_db()
        self.assertIsNone(self.blep.end_time)
        self.assertIsNone(other_blep.end_time)

    def test_no_user_refuses_on_any_open_blep(self):
        """Caller without user attribution can't claim any session as its
        own — the pre-existing refusal stands."""
        result = TaskLifecycleService.block_task(self.eq_task.pk)
        self.assertEqual(result.get('conflict'), 'active_workers')


class BlockNoRollupRegressionTest(BaseTestCase):
    """Blocking/unblocking a task must NOT bubble up to Job status."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='Task', job=self.job, rate_scheme_id=1)

    def test_block_task_does_not_change_job_status(self):
        original = self.job.status
        TaskLifecycleService.block_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, original)

    def test_unblock_task_does_not_change_job_status(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        original = self.job.status
        TaskLifecycleService.unblock_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, original)


class BlockTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        self.user = User.objects.get(username='admin')

    def test_block_from_pending(self):
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)

    def test_block_stores_reason(self):
        TaskLifecycleService.block_task(self.task.pk, reason='Waiting on parts')
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, 'Waiting on parts')

    def test_block_without_reason_stores_empty(self):
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, '')

    def test_block_from_in_progress(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)

    def test_block_rejects_if_open_bleps(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now()
        )
        result = TaskLifecycleService.block_task(self.task.pk)
        self.assertIn('conflict', result)
        self.assertEqual(result['conflict'], 'active_workers')
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_block_rejects_complete(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.block_task(self.task.pk)

    def test_unblock(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        self.task.refresh_from_db()
        TaskLifecycleService.unblock_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_unblock_clears_blocked_reason(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_BLOCKED, blocked_reason='Waiting on parts'
        )
        TaskLifecycleService.unblock_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, '')

    def test_unblock_rejects_non_blocked(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.unblock_task(self.task.pk)


class CancelTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        self.user = User.objects.get(username='admin')

    def test_cancel_from_pending(self):
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_cancel_from_in_progress_closes_bleps(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        # Over-minimum so cancelling the task CLOSES the blep (not cancels it).
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30)
        )
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_cancel_from_blocked(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        self.task.refresh_from_db()
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_cancel_from_blocked_clears_reason(self):
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_BLOCKED, blocked_reason='Waiting on parts'
        )
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, '')

    def test_cancel_rejects_complete(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_task(self.task.pk)

    def test_cancel_detaches_pending_materials_to_job(self):
        # A cancelled task must not keep "needed" materials captive: pending
        # rows ride back to the job as loose materials (task=NULL), keeping
        # their earmark; the user releases them by hand if truly unwanted.
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import Earmark, InventoryItem, Material
        from apps.inventory.services import MaterialService
        _approve_job(self.job)
        cat = AccountingCategory.objects.first()
        pli = InventoryItem.objects.create(
            code='CANCEL-DETACH', accounting_category=cat,
            qty_on_hand=Decimal('0'),
        )
        m = MaterialService.create_on_job(
            job=self.job, task=self.task,
            description='sheet', quantity=Decimal('2'), inventory_item=pli,
        )
        TaskLifecycleService.cancel_task(self.task.pk)
        m.refresh_from_db()
        self.assertIsNone(m.task_id)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(inventory_item=pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('2'))

    def test_cancel_leaves_consumed_materials_attached(self):
        # Consumed rows are history of work actually done on the task before
        # cancellation — they stay attached.
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import InventoryItem, Material
        from apps.inventory.services import MaterialService
        _approve_job(self.job)
        cat = AccountingCategory.objects.first()
        pli = InventoryItem.objects.create(
            code='CANCEL-KEEP', accounting_category=cat,
            qty_on_hand=Decimal('5'),
        )
        m = MaterialService.create_on_job(
            job=self.job, task=self.task,
            description='rod', quantity=Decimal('1'), inventory_item=pli,
        )
        MaterialService.consume(m)
        TaskLifecycleService.cancel_task(self.task.pk)
        m.refresh_from_db()
        self.assertEqual(m.task_id, self.task.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)


class StartStopWorkTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme_id=1)
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        self.user = User.objects.get(username='admin')
        self.worker2 = User.objects.create_user(username='worker2', password='test')

    def test_start_work_creates_blep(self):
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        blep = result['blep']
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)
        self.assertEqual(blep.user, self.user)

    def test_start_work_rejects_non_startable_status(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.user)

    def test_start_work_closes_users_other_blep(self):
        other_task = Task.objects.create(name='Other Task', job=self.job, rate_scheme_id=1)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Over-minimum so it is CLOSED (not cancelled) when start_work switches tasks.
        old_blep = Blep.objects.create(
            task=other_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30)
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    def test_start_work_conflict_returns_worker_info(self):
        Blep.objects.create(
            task=self.task, user=self.worker2, start_time=timezone.now()
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        self.assertIn('conflict', result)
        self.assertEqual(result['conflict'], 'active_worker')
        self.assertIn('join', result['options'])
        self.assertIn('takeover', result['options'])

    def test_start_work_join(self):
        Blep.objects.create(
            task=self.task, user=self.worker2, start_time=timezone.now()
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user, action='join')
        self.assertIn('blep', result)
        open_bleps = Blep.objects.filter(task=self.task, end_time__isnull=True)
        self.assertEqual(open_bleps.count(), 2)

    def test_start_work_takeover_over_minimum_closes_displaced_blep(self):
        """Takeover RESOLVES the displaced blep then restarts via the normal
        path. An over-minimum displaced blep is real work: it is CLOSED (still
        exists, end_time set + floored), the task stays in_progress, and the
        taking-over worker gets an open blep.
        """
        from apps.core.models import Shift
        now = timezone.now()
        # Enclosing open shift for worker2 so the soon-to-be-closed blep
        # satisfies the shift-enclosure invariant.
        Shift.objects.create(
            user=self.worker2, start_time=now - timedelta(days=1),
        )
        # worker2 has an OPEN over-minute blep on the in_progress task.
        other_blep = Blep.objects.create(
            task=self.task, user=self.worker2,
            start_time=now - timedelta(minutes=30),
        )
        result = TaskLifecycleService.start_work(
            self.task.pk, self.user, action='takeover'
        )
        # Displaced real-work blep is CLOSED, not deleted.
        self.assertTrue(Blep.objects.filter(pk=other_blep.pk).exists())
        other_blep.refresh_from_db()
        self.assertIsNotNone(other_blep.end_time)
        # end_time floored to the minute (Blep.save() normalization).
        self.assertEqual(other_blep.end_time.second, 0)
        self.assertEqual(other_blep.end_time.microsecond, 0)
        # Task stays in_progress; new worker has an open blep.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        new_blep = result['blep']
        self.assertEqual(new_blep.user, self.user)
        self.assertIsNone(new_blep.end_time)

    def test_start_work_takeover_sub_minimum_only_activity_cancels_and_restarts(self):
        """A sub-minute displaced blep that was the task's ONLY activity is an
        accidental start: takeover CANCELS it (deleted/gone), which reverts the
        task to pending and un-consumes materials. The restart via the normal
        pending path then re-promotes (re-consuming materials), reassigns the
        task to the taking-over worker, and opens that worker's blep.
        """
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import Material, InventoryItem
        # Material on the task so we can confirm re-consumption.
        cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False},
        )[0]
        non_inv = InventoryItem.objects.create(
            code='PLI-NI-TKO', description='Labor',
            qty_on_hand=Decimal('0.00'),
            qty_sold=Decimal('0.00'), accounting_category=cat,
        )
        mat = Material.objects.create(
            job=self.job, task=self.task, inventory_item=non_inv,
            description='non-inv', quantity=Decimal('2.00'),
        )
        # The task was promoted by worker2's start, so its material is consumed.
        Material.objects.filter(pk=mat.pk).update(
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        now = timezone.now()
        # worker2 has an OPEN sub-minute blep that is the task's only activity.
        other_blep = Blep.objects.create(
            task=self.task, user=self.worker2, start_time=now,
        )
        result = TaskLifecycleService.start_work(
            self.task.pk, self.user, action='takeover'
        )
        # Displaced sub-minute blep is CANCELLED (deleted), not closed.
        self.assertFalse(Blep.objects.filter(pk=other_blep.pk).exists())
        # Task ended in_progress (re-promoted by the restart), reassigned to the
        # taking-over worker, who has an open blep.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        self.assertEqual(self.task.assignee, self.user)
        new_blep = result['blep']
        self.assertEqual(new_blep.user, self.user)
        self.assertIsNone(new_blep.end_time)
        # Material was re-consumed via the pending->in_progress promotion.
        mat.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_start_work_takeover_sub_minimum_with_prior_activity_no_revert(self):
        """A sub-minute displaced blep on a task that had PRIOR activity (a
        closed blep) is deleted on takeover, but the task is NOT reverted to
        pending (it was not the first/only activity). Task stays in_progress and
        the taking-over worker gets a blep — no spurious revert.
        """
        from apps.core.models import Shift
        now = timezone.now()
        # Prior closed blep => task is not first/only activity.
        Shift.objects.create(
            user=self.worker2, start_time=now - timedelta(days=1),
        )
        prior = Blep.objects.create(
            task=self.task, user=self.worker2,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        # worker2's OPEN sub-minute blep.
        other_blep = Blep.objects.create(
            task=self.task, user=self.worker2, start_time=now,
        )
        result = TaskLifecycleService.start_work(
            self.task.pk, self.user, action='takeover'
        )
        # Sub-minute open blep deleted; the prior closed blep survives.
        self.assertFalse(Blep.objects.filter(pk=other_blep.pk).exists())
        self.assertTrue(Blep.objects.filter(pk=prior.pk).exists())
        # No spurious revert: task stays in_progress.
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        new_blep = result['blep']
        self.assertEqual(new_blep.user, self.user)
        self.assertIsNone(new_blep.end_time)

    def test_start_work_join_does_not_change_assignee(self):
        self.task.assignee = self.worker2
        self.task.est_worker_time = timedelta(hours=1)
        self.task.save()
        Blep.objects.create(
            task=self.task, user=self.worker2, start_time=timezone.now()
        )
        TaskLifecycleService.start_work(self.task.pk, self.user, action='join')
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.worker2)

    def test_stop_work_closes_blep(self):
        # Over-minimum so stop_work CLOSES it (a sub-minimum blep is cancelled).
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30)
        )
        TaskLifecycleService.stop_work(self.task.pk, self.user)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_no_open_blep_raises(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.stop_work(self.task.pk, self.user)
