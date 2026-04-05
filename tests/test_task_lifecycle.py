from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, WorkOrder, Blep
from apps.jobs.services import TaskLifecycleService
from apps.core.models import User


class TaskStatusFieldTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)

    def test_task_default_status_is_pending(self):
        task = Task.objects.create(
            name='Test Task',
            work_order=self.wo,
        )
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
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)

    def _create_task_with_status(self, status):
        """Create a task and set its status bypassing clean()."""
        task = Task.objects.create(
            name='Test Task',
            work_order=self.wo,
        )
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    # Valid transitions
    def test_pending_to_in_progress(self):
        task = self._create_task_with_status(Task.STATUS_PENDING)
        task.status = Task.STATUS_IN_PROGRESS
        task.full_clean()  # should not raise

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
        task.full_clean()  # should not raise

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
        task = Task(
            name='New Task',
            work_order=self.wo,
            status=Task.STATUS_IN_PROGRESS,
        )
        task.full_clean()  # should not raise


class WorkOrderStatusTest(BaseTestCase):
    """Test WorkOrder status: no draft state, transition validation."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()

    def _make_wo(self, status=WorkOrder.STATUS_INCOMPLETE):
        wo = WorkOrder.objects.create(job=self.job)
        if status != WorkOrder.STATUS_INCOMPLETE:
            WorkOrder.objects.filter(pk=wo.pk).update(status=status)
            wo.refresh_from_db()
        return wo

    def test_new_wo_starts_incomplete(self):
        wo = WorkOrder.objects.create(job=self.job)
        self.assertEqual(wo.status, WorkOrder.STATUS_INCOMPLETE)

    def test_draft_not_in_choices(self):
        values = {c[0] for c in WorkOrder.WORK_ORDER_STATUS_CHOICES}
        self.assertNotIn('draft', values)

    def test_incomplete_to_complete(self):
        wo = self._make_wo(WorkOrder.STATUS_INCOMPLETE)
        wo.status = WorkOrder.STATUS_COMPLETE
        wo.full_clean()  # Should not raise

    def test_incomplete_to_blocked(self):
        wo = self._make_wo(WorkOrder.STATUS_INCOMPLETE)
        wo.status = WorkOrder.STATUS_BLOCKED
        wo.full_clean()  # Should not raise

    def test_blocked_to_incomplete(self):
        wo = self._make_wo(WorkOrder.STATUS_BLOCKED)
        wo.status = WorkOrder.STATUS_INCOMPLETE
        wo.full_clean()  # Should not raise

    def test_complete_is_terminal(self):
        wo = self._make_wo(WorkOrder.STATUS_COMPLETE)
        wo.status = WorkOrder.STATUS_INCOMPLETE
        with self.assertRaises(ValidationError):
            wo.full_clean()


class StartWorkOnPendingTaskTest(BaseTestCase):
    """start_work on a pending task promotes it and consumes materials."""
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)
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

    def test_start_work_rejects_worksheet_task(self):
        from apps.estimates.models import EstWorksheet
        ws = EstWorksheet.objects.create(job=self.job)
        ws_task = Task.objects.create(name='WS Task', est_worksheet=ws)
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(ws_task.pk, self.user)

    def test_start_work_closes_users_other_open_blep(self):
        other_task = Task.objects.create(name='Other Task', work_order=self.wo)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        old_blep = Blep.objects.create(
            task=other_task, user=self.user, start_time=timezone.now()
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    @patch('apps.inventory.services.InventoryService.consume_material')
    def test_start_work_consumes_materials_on_first_start(self, mock_consume):
        from apps.inventory.models import Material
        mat = Material.objects.create(task=self.task, description='Test Material')
        TaskLifecycleService.start_work(self.task.pk, self.user)
        mock_consume.assert_called_once_with(mat)


class CompleteTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)
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

    def test_complete_last_task_auto_completes_wo(self):
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_COMPLETE)

    def test_complete_task_does_not_auto_complete_wo_if_others_remain(self):
        other_task = Task.objects.create(name='Other Task', work_order=self.wo)
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_INCOMPLETE)

    def test_complete_with_cancelled_siblings_auto_completes_wo(self):
        other_task = Task.objects.create(name='Other Task', work_order=self.wo)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_CANCELLED)
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_COMPLETE)


class BlockTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)
        self.user = User.objects.get(username='admin')

    def test_block_from_pending(self):
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)

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

    def test_unblock_rejects_non_blocked(self):
        with self.assertRaises(ValidationError):
            TaskLifecycleService.unblock_task(self.task.pk)


class TaskBlockedWorkOrderBlockedTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)

    def test_workorder_blocked_when_task_blocked(self):
        TaskLifecycleService.block_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_BLOCKED)

    def test_workorder_stays_blocked_if_already_blocked(self):
        WorkOrder.objects.filter(pk=self.wo.pk).update(status=WorkOrder.STATUS_BLOCKED)
        task2 = Task.objects.create(name='Task 2', work_order=self.wo)
        TaskLifecycleService.block_task(task2.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_BLOCKED)

    def test_worksheet_task_block_does_not_affect_workorder(self):
        """Blocking a task on an EstWorksheet should not try to block a WorkOrder."""
        from apps.estimates.models import EstWorksheet
        ws = EstWorksheet.objects.create(job=self.job)
        ws_task = Task.objects.create(name='WS Task', est_worksheet=ws)
        TaskLifecycleService.block_task(ws_task.pk)
        ws_task.refresh_from_db()
        self.assertEqual(ws_task.status, Task.STATUS_BLOCKED)


class CancelTaskTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)
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

    def test_cancel_rejects_complete(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_task(self.task.pk)

    def test_cancel_last_non_terminal_triggers_wo_auto_complete(self):
        other_task = Task.objects.create(name='Other Task', work_order=self.wo)
        Task.objects.filter(pk=other_task.pk).update(status=Task.STATUS_COMPLETE)
        TaskLifecycleService.cancel_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, WorkOrder.STATUS_COMPLETE)


class StartStopWorkTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Test Task', work_order=self.wo)
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
        # pending and in_progress are both startable; anything else must reject.
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.user)

    def test_start_work_closes_users_other_blep(self):
        other_task = Task.objects.create(name='Other Task', work_order=self.wo)
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
        # Both bleps should be open
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
