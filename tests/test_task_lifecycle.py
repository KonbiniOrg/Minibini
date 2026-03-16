from django.core.exceptions import ValidationError

from tests.base import BaseTestCase
from apps.jobs.models import Task, WorkOrder


class TaskStatusFieldTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')

    def test_task_default_status_is_pending(self):
        task = Task.objects.create(
            name='Test Task',
            work_order=self.wo,
        )
        self.assertEqual(task.status, 'pending')

    def test_task_status_choices(self):
        expected = [
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('blocked', 'Blocked'),
            ('complete', 'Complete'),
            ('cancelled', 'Cancelled'),
        ]
        self.assertEqual(Task.TASK_STATUS_CHOICES, expected)


class TaskTransitionValidationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')

    def _create_task_with_status(self, status):
        """Create a task and set its status bypassing clean()."""
        task = Task.objects.create(
            name='Test Task',
            work_order=self.wo,
        )
        if status != 'pending':
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    # Valid transitions
    def test_pending_to_in_progress(self):
        task = self._create_task_with_status('pending')
        task.status = 'in_progress'
        task.full_clean()  # should not raise

    def test_pending_to_blocked(self):
        task = self._create_task_with_status('pending')
        task.status = 'blocked'
        task.full_clean()

    def test_pending_to_complete(self):
        task = self._create_task_with_status('pending')
        task.status = 'complete'
        task.full_clean()

    def test_pending_to_cancelled(self):
        task = self._create_task_with_status('pending')
        task.status = 'cancelled'
        task.full_clean()

    def test_in_progress_to_blocked(self):
        task = self._create_task_with_status('in_progress')
        task.status = 'blocked'
        task.full_clean()

    def test_in_progress_to_complete(self):
        task = self._create_task_with_status('in_progress')
        task.status = 'complete'
        task.full_clean()

    def test_in_progress_to_cancelled(self):
        task = self._create_task_with_status('in_progress')
        task.status = 'cancelled'
        task.full_clean()

    def test_blocked_to_in_progress(self):
        task = self._create_task_with_status('blocked')
        task.status = 'in_progress'
        task.full_clean()

    def test_blocked_to_cancelled(self):
        task = self._create_task_with_status('blocked')
        task.status = 'cancelled'
        task.full_clean()

    # Invalid transitions
    def test_complete_to_in_progress_raises(self):
        task = self._create_task_with_status('complete')
        task.status = 'in_progress'
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_cancelled_to_in_progress_raises(self):
        task = self._create_task_with_status('cancelled')
        task.status = 'in_progress'
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_in_progress_to_pending_raises(self):
        task = self._create_task_with_status('in_progress')
        task.status = 'pending'
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_blocked_to_complete_raises(self):
        task = self._create_task_with_status('blocked')
        task.status = 'complete'
        with self.assertRaises(ValidationError) as ctx:
            task.full_clean()
        self.assertIn('status', str(ctx.exception))

    def test_new_task_no_transition_validation(self):
        """New task (no pk) should not trigger transition validation."""
        task = Task(
            name='New Task',
            work_order=self.wo,
            status='in_progress',
        )
        task.full_clean()  # should not raise
