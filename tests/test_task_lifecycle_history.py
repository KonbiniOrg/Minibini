"""Task lifecycle transitions must be history-visible (plan A1).

Every status transition performed by TaskLifecycleService lands in the
job-domain history table as an audit diff (block/unblock/complete/cancel
and the pending->in_progress promotion), and cancel_work's deliberate
in_progress->pending revert writes an explicit action row. worker_queue
is cosmetic and stays out of the audit trail entirely.

Also covers the relocated "assigned work needs an estimated worker time"
invariant: it lives on the explicit assign gestures (TaskService.assign /
create_direct / update_task), NOT on Task.clean() — auto-assign on
start_work deliberately skips it, so the model must accept that state and
later lifecycle saves must not choke on it.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from tests.base import BaseTestCase
from apps.core.models import JobHistory, User
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import (
    TaskLifecycleService, TaskService, TaskWorkerTimeRequired,
)


def _approve_job(job):
    for step in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        if job.status != step:
            job.status = step
            job.save()


def _log_time(task, user, hours=1):
    now = timezone.now()
    Blep.objects.create(
        task=task, user=user,
        start_time=now - timedelta(hours=hours), end_time=now,
    )


def _task_audits(task):
    """Audit rows for this task, excluding the creation marker."""
    return [
        e for e in JobHistory.objects.filter(
            object_type='task', object_id=task.pk, entry_type='audit',
        )
        if not (e.changes or {}).get('_created')
    ]


def _task_actions(task):
    return list(JobHistory.objects.filter(
        object_type='task', object_id=task.pk, entry_type='action',
    ))


class TaskLifecycleHistoryTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.worker = User.objects.get(username='johnq')
        self.task = Task.objects.create(
            name='History task', job=self.job, rate_scheme_id=1,
        )

    def _diffs(self):
        """Merge all audit diffs for the task into {field: (old, new)}."""
        merged = {}
        for entry in _task_audits(self.task):
            for field, change in (entry.changes or {}).items():
                merged[field] = (change['old'], change['new'])
        return merged

    def test_block_task_records_status_and_reason(self):
        TaskLifecycleService.block_task(self.task.pk, reason='waiting on glue')
        diffs = self._diffs()
        self.assertIn('status', diffs)
        self.assertEqual(diffs['status'], ('pending', 'blocked'))
        self.assertIn('blocked_reason', diffs)
        self.assertEqual(diffs['blocked_reason'][1], 'waiting on glue')

    def test_unblock_task_records_status(self):
        TaskLifecycleService.block_task(self.task.pk, reason='waiting')
        TaskLifecycleService.unblock_task(self.task.pk)
        diffs = {}
        for entry in _task_audits(self.task):
            changes = entry.changes or {}
            if changes.get('status', {}).get('new') == 'in_progress':
                diffs = changes
        self.assertEqual(diffs['status']['old'], 'blocked')
        self.assertEqual(diffs['status']['new'], 'in_progress')

    def test_complete_task_records_status(self):
        _log_time(self.task, self.worker)
        TaskLifecycleService.complete_task(self.task.pk)
        diffs = self._diffs()
        self.assertIn('status', diffs)
        self.assertEqual(diffs['status'][1], 'complete')

    def test_cancel_task_records_status(self):
        TaskLifecycleService.cancel_task(self.task.pk)
        diffs = self._diffs()
        self.assertIn('status', diffs)
        self.assertEqual(diffs['status'][1], 'cancelled')

    def test_start_work_promotion_records_status(self):
        TaskLifecycleService.start_work(self.task.pk, self.worker)
        diffs = self._diffs()
        self.assertIn('status', diffs)
        self.assertEqual(diffs['status'], ('pending', 'in_progress'))

    def test_worker_queue_never_appears_in_history(self):
        # Assign (with est time) then start work — the bump-to-front updates
        # worker_queue, which must stay out of the audit trail.
        TaskService.assign(
            self.task, self.worker.pk, worker_queue=3,
            est_worker_time=timedelta(hours=1),
        )
        TaskLifecycleService.start_work(self.task.pk, self.worker)
        for entry in _task_audits(self.task):
            self.assertNotIn('worker_queue', entry.changes or {})

    def test_cancel_work_revert_records_action_row(self):
        TaskLifecycleService.start_work(self.task.pk, self.worker)
        TaskLifecycleService.cancel_work(self.task.pk, self.worker)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        actions = _task_actions(self.task)
        self.assertTrue(
            any('revert' in (a.changes or {}).get('_action', '').lower()
                for a in actions),
            f'expected a revert action row, got {actions!r}',
        )


class AssignedWorkerTimeInvariantTest(BaseTestCase):
    """The assigned=>est_worker_time invariant lives on the explicit assign
    gestures, not the model — auto-assign deliberately violates it."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        _approve_job(self.job)
        self.worker = User.objects.get(username='johnq')

    def test_model_accepts_assignee_without_est_worker_time(self):
        # The state auto-assign creates must be a legal model state.
        task = Task.objects.create(
            name='Auto-assigned shape', job=self.job, rate_scheme_id=1,
            assignee=self.worker,
        )
        self.assertIsNone(task.est_worker_time)

    def test_auto_assigned_task_without_est_time_completes(self):
        task = Task.objects.create(
            name='No estimate', job=self.job, rate_scheme_id=1,
        )
        # start_work auto-assigns the first worker with no est time.
        TaskLifecycleService.start_work(task.pk, self.worker)
        task.refresh_from_db()
        self.assertEqual(task.assignee, self.worker)
        self.assertIsNone(task.est_worker_time)
        _log_time(task, self.worker)
        TaskLifecycleService.stop_work(task.pk, self.worker)
        TaskLifecycleService.complete_task(task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_COMPLETE)

    def test_auto_assigned_task_without_est_time_blocks(self):
        task = Task.objects.create(
            name='No estimate blocks', job=self.job, rate_scheme_id=1,
        )
        TaskLifecycleService.start_work(task.pk, self.worker)
        result = TaskLifecycleService.block_task(
            task.pk, reason='hm', user=self.worker)
        self.assertNotIsInstance(result, dict)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.STATUS_BLOCKED)

    def test_assign_service_requires_worker_time(self):
        task = Task.objects.create(
            name='Explicit assign', job=self.job, rate_scheme_id=1,
        )
        with self.assertRaises(TaskWorkerTimeRequired):
            TaskService.assign(task, self.worker.pk)

    def test_create_direct_with_assignee_requires_worker_time(self):
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                self.job, 'Created assigned', rate_scheme_id=1,
                assignee_id=self.worker.pk,
            )

    def test_update_task_assigning_requires_worker_time(self):
        task = Task.objects.create(
            name='Patch assign', job=self.job, rate_scheme_id=1,
        )
        with self.assertRaises(ValidationError):
            TaskService.update_task(task.pk, assignee=self.worker)

    def test_update_task_assigning_with_worker_time_succeeds(self):
        task = Task.objects.create(
            name='Patch assign ok', job=self.job, rate_scheme_id=1,
        )
        updated = TaskService.update_task(
            task.pk, assignee=self.worker,
            est_worker_time=timedelta(hours=2),
        )
        self.assertEqual(updated.assignee, self.worker)
