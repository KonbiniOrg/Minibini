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


class TaskStatusFieldTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()

    def test_task_default_status_is_pending(self):
        task = Task.objects.create(name='Test Task', job=self.job)
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
        task = Task.objects.create(name='Test Task', job=self.job)
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
        task = Task(name='New Task', job=self.job, status=Task.STATUS_IN_PROGRESS)
        task.full_clean()


class StartWorkOnPendingTaskTest(BaseTestCase):
    """start_work on a pending task promotes it and consumes materials."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job)
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
        other_task = Task.objects.create(name='Other Task', job=self.job)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        old_blep = Blep.objects.create(
            task=other_task, user=self.user, start_time=timezone.now()
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    @patch('apps.inventory.services.MaterialService.consume')
    def test_start_work_consumes_materials_on_first_start(self, mock_consume):
        from apps.inventory.models import Material
        mat = Material.objects.create(job=self.job, task=self.task, description='Test Material')
        TaskLifecycleService.start_work(self.task.pk, self.user)
        mock_consume.assert_called_once_with(mat)

    def test_task_start_consumes_non_inventoried_material_marker(self):
        """Starting a task flips non-inventoried materials to consumed (marker-only).

        No QOH or earmark side effects should occur for non-inventoried PLIs.
        """
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import Earmark, Material, PriceListItem
        cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False},
        )[0]
        non_inv = PriceListItem.objects.create(
            code='PLI-NI-ML', description='Labor',
            is_inventoried=False, qty_on_hand=Decimal('0.00'),
            qty_sold=Decimal('0.00'), accounting_category=cat,
        )
        mat = Material.objects.create(
            job=self.job, task=self.task,
            price_list_item=non_inv,
            description='non-inv',
            quantity=Decimal('2.00'),
        )
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)

        TaskLifecycleService.start_work(self.task.pk, self.user)

        mat.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        non_inv.refresh_from_db()
        self.assertEqual(non_inv.qty_on_hand, Decimal('0.00'))
        self.assertEqual(non_inv.qty_sold, Decimal('0.00'))
        self.assertFalse(
            Earmark.objects.filter(price_list_item=non_inv, job=self.job).exists()
        )

    def test_start_work_assigns_user_when_no_assignee(self):
        self.assertIsNone(self.task.assignee)
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.user)

    def test_start_work_preserves_existing_assignee(self):
        other_user = User.objects.create_user(username='other', password='test')
        self.task.assignee = other_user
        self.task.save()
        TaskLifecycleService.start_work(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, other_user)


class CompleteTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job)
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
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now()
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
        self.task = Task.objects.create(name='Test Task', job=self.job)
        self.user = User.objects.get(username='admin')

    def test_complete_last_task_on_approved_job_advances_to_work_complete(self):
        TaskLifecycleService.complete_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_complete_with_others_remaining_does_not_advance(self):
        Task.objects.create(name='Other Task', job=self.job)
        TaskLifecycleService.complete_task(self.task.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_complete_with_cancelled_siblings_advances(self):
        other = Task.objects.create(name='Other Task', job=self.job)
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
        task = Task.objects.create(name='DraftTask', job=job2)
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
        other = Task.objects.create(name='Extra', job=self.job)
        with patch(
            'apps.jobs.services.JobService.update_status'
        ) as mock_update:
            TaskLifecycleService.complete_task(other.pk)
        mock_update.assert_not_called()


class BlockNoRollupRegressionTest(BaseTestCase):
    """Blocking/unblocking a task must NOT bubble up to Job status."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.task = Task.objects.create(name='Task', job=self.job)

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
        self.task = Task.objects.create(name='Test Task', job=self.job)
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
        self.task = Task.objects.create(name='Test Task', job=self.job)
        self.user = User.objects.get(username='admin')

    def test_cancel_from_pending(self):
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_cancel_from_in_progress_closes_bleps(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now()
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


class StartStopWorkTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Test Task', job=self.job)
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
        other_task = Task.objects.create(name='Other Task', job=self.job)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        old_blep = Blep.objects.create(
            task=other_task, user=self.user, start_time=timezone.now()
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

    def test_start_work_takeover(self):
        other_blep = Blep.objects.create(
            task=self.task, user=self.worker2, start_time=timezone.now()
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user, action='takeover')
        self.assertIn('blep', result)
        other_blep.refresh_from_db()
        self.assertIsNotNone(other_blep.end_time)

    def test_start_work_join_does_not_change_assignee(self):
        self.task.assignee = self.worker2
        self.task.save()
        Blep.objects.create(
            task=self.task, user=self.worker2, start_time=timezone.now()
        )
        TaskLifecycleService.start_work(self.task.pk, self.user, action='join')
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, self.worker2)

    def test_stop_work_closes_blep(self):
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now()
        )
        TaskLifecycleService.stop_work(self.task.pk, self.user)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_no_open_blep_raises(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.stop_work(self.task.pk, self.user)
