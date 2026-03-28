# Task Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add status tracking to Tasks (pending/in_progress/blocked/complete/cancelled) with lifecycle operations that connect time tracking (Bleps) and inventory consumption.

**Architecture:** TaskLifecycleService in the existing service layer handles all transitions and side effects (Blep creation/closing, material consumption) in single transactional methods. A new TaskLifecycleMixin adds nested action endpoints to WorkOrderViewSet. WorkOrder auto-completes when all tasks reach terminal states.

**Tech Stack:** Django 5.2, Django REST Framework, existing InventoryService

**Reference docs:**
- `docs/2026-03-15-task-lifecycle-design.md` — approved design spec

---

## Chunk 1: Model Changes and Transition Validation

### Task 1: Add status field to Task model

**Files:**
- Modify: `apps/jobs/models.py:129-147`
- Test: `tests/test_task_lifecycle.py` (create)

- [ ] **Step 1: Write failing test for Task status field**

```python
# tests/test_task_lifecycle.py
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Task, WorkOrder
from tests.base import BaseTestCase


class TaskStatusFieldTest(BaseTestCase):
    """Test that Task has a status field with correct choices and default."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')

    def test_task_default_status_is_pending(self):
        task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )
        self.assertEqual(task.status, 'pending')

    def test_task_status_choices(self):
        expected_values = {'pending', 'in_progress', 'blocked', 'complete', 'cancelled'}
        actual_values = {choice[0] for choice in Task.TASK_STATUS_CHOICES}
        self.assertEqual(actual_values, expected_values)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_lifecycle.TaskStatusFieldTest -v2`
Expected: FAIL — `AttributeError: type object 'Task' has no attribute 'TASK_STATUS_CHOICES'`

- [ ] **Step 3: Add status field and choices to Task model**

In `apps/jobs/models.py`, add after line 129 (`class Task(models.Model):`):

```python
    TASK_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('blocked', 'Blocked'),
        ('complete', 'Complete'),
        ('cancelled', 'Cancelled'),
    ]
```

Add after line 140 (`est_qty` field), before `line_item_type`:

```python
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default='pending')
```

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations jobs`

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_task_lifecycle.TaskStatusFieldTest -v2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_task_lifecycle.py
git commit -m "feat: add status field to Task model"
```

### Task 2: Add transition validation to Task.clean()

**Files:**
- Modify: `apps/jobs/models.py:149-160` (Task.clean)
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests for Task transitions**

Append to `tests/test_task_lifecycle.py`:

```python
class TaskTransitionValidationTest(BaseTestCase):
    """Test that Task.clean() enforces valid status transitions."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')

    def _make_task(self, status='pending'):
        task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )
        if status != 'pending':
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    def test_pending_to_in_progress(self):
        task = self._make_task('pending')
        task.status = 'in_progress'
        task.full_clean()  # Should not raise

    def test_pending_to_blocked(self):
        task = self._make_task('pending')
        task.status = 'blocked'
        task.full_clean()  # Should not raise

    def test_pending_to_complete(self):
        task = self._make_task('pending')
        task.status = 'complete'
        task.full_clean()  # Should not raise

    def test_pending_to_cancelled(self):
        task = self._make_task('pending')
        task.status = 'cancelled'
        task.full_clean()  # Should not raise

    def test_in_progress_to_blocked(self):
        task = self._make_task('in_progress')
        task.status = 'blocked'
        task.full_clean()  # Should not raise

    def test_in_progress_to_complete(self):
        task = self._make_task('in_progress')
        task.status = 'complete'
        task.full_clean()  # Should not raise

    def test_in_progress_to_cancelled(self):
        task = self._make_task('in_progress')
        task.status = 'cancelled'
        task.full_clean()  # Should not raise

    def test_blocked_to_in_progress(self):
        task = self._make_task('blocked')
        task.status = 'in_progress'
        task.full_clean()  # Should not raise

    def test_blocked_to_cancelled(self):
        task = self._make_task('blocked')
        task.status = 'cancelled'
        task.full_clean()  # Should not raise

    def test_complete_is_terminal(self):
        task = self._make_task('complete')
        task.status = 'in_progress'
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_cancelled_is_terminal(self):
        task = self._make_task('cancelled')
        task.status = 'in_progress'
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_in_progress_to_pending_invalid(self):
        task = self._make_task('in_progress')
        task.status = 'pending'
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_blocked_to_complete_invalid(self):
        task = self._make_task('blocked')
        task.status = 'complete'
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_no_validation_on_new_task(self):
        """New tasks (no pk) should not trigger transition validation."""
        task = Task(
            work_order=self.wo, name="New task",
            units="hours", rate="10.00", est_qty="1",
            status='pending',
        )
        task.full_clean()  # Should not raise
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.TaskTransitionValidationTest -v2`
Expected: `test_complete_is_terminal`, `test_cancelled_is_terminal`, `test_in_progress_to_pending_invalid`, and `test_blocked_to_complete_invalid` should FAIL (no transition validation yet)

- [ ] **Step 3: Add transition validation to Task.clean()**

Replace the `clean()` method in `apps/jobs/models.py` Task class. The existing `clean()` handles container and bundle validation. Add transition validation before the existing checks:

```python
    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_BLOCKED = 'blocked'
    STATUS_COMPLETE = 'complete'
    STATUS_CANCELLED = 'cancelled'

    VALID_TRANSITIONS = {
        STATUS_PENDING: [STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_IN_PROGRESS: [STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_BLOCKED: [STATUS_IN_PROGRESS, STATUS_CANCELLED],
        STATUS_COMPLETE: [],
        STATUS_CANCELLED: [],
    }

    def clean(self):
        from django.core.exceptions import ValidationError

        # Status transition validation (updates only)
        if self.pk:
            try:
                old_task = Task.objects.get(pk=self.pk)
                old_status = old_task.status
                if old_status != self.status:
                    valid_next = self.VALID_TRANSITIONS.get(old_status, [])
                    if self.status not in valid_next:
                        raise ValidationError(
                            f'Cannot transition Task from {old_status} to {self.status}. '
                            f'Valid transitions: {", ".join(valid_next) if valid_next else "none (terminal state)"}'
                        )
            except Task.DoesNotExist:
                pass

        # Must belong to exactly one container
        if self.work_order and self.est_worksheet:
            raise ValidationError("Task cannot be attached to both WorkOrder and EstWorksheet")
        if not self.work_order and not self.est_worksheet:
            raise ValidationError("Task must be attached to either WorkOrder or EstWorksheet")
        # Bundle consistency
        if self.mapping_strategy == 'bundle' and not self.bundle:
            raise ValidationError("Bundled tasks must have a bundle assigned")
        if self.bundle and self.mapping_strategy != 'bundle':
            raise ValidationError("Tasks with a bundle must use 'bundle' mapping strategy")
```

Note: The `clean()` transition validation exists as a safety net for direct model saves. The `TaskLifecycleService` methods perform their own validation and use `Task.objects.filter().update()` to bypass `save()`/`full_clean()` for status changes, avoiding the extra DB query and redundant validation. This follows the pattern where the service owns all business logic and the model provides a safety net.

- [ ] **Step 4: Run tests to verify all pass**

Run: `python manage.py test tests.test_task_lifecycle.TaskTransitionValidationTest -v2`
Expected: All PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python manage.py test`
Expected: All existing tests pass. If any fail because existing code sets task status in ways that violate transitions, fix those tests (they're likely using `QuerySet.update()` which bypasses `clean()`).

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py tests/test_task_lifecycle.py
git commit -m "feat: add status transition validation to Task.clean()"
```

### Task 3: Remove draft state from WorkOrder and add transition validation

WorkOrders are living documents — unlike estimates, they never go through a draft/finalize step. They should start in `incomplete` and always be open to changes. The `draft` state serves no purpose and creates a confusing activation step.

This task removes `draft`, updates all creation paths, and adds transition validation. Follow the same pattern as `Job.clean()`.

**Files:**
- Modify: `apps/jobs/models.py:111-127` (WorkOrder class)
- Modify: `apps/jobs/services.py` (WorkOrderService.create_direct, create_from_template)
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests for WorkOrder status changes**

Append to `tests/test_task_lifecycle.py`:

```python
class WorkOrderStatusTest(BaseTestCase):
    """Test WorkOrder status: no draft state, transition validation."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        self.job = Job.objects.first()

    def _make_wo(self, status='incomplete'):
        wo = WorkOrder.objects.create(job=self.job)
        if status != 'incomplete':
            WorkOrder.objects.filter(pk=wo.pk).update(status=status)
            wo.refresh_from_db()
        return wo

    def test_new_wo_starts_incomplete(self):
        wo = WorkOrder.objects.create(job=self.job)
        self.assertEqual(wo.status, 'incomplete')

    def test_draft_not_in_choices(self):
        values = {c[0] for c in WorkOrder.WORK_ORDER_STATUS_CHOICES}
        self.assertNotIn('draft', values)

    def test_incomplete_to_complete(self):
        wo = self._make_wo('incomplete')
        wo.status = 'complete'
        wo.full_clean()  # Should not raise

    def test_incomplete_to_blocked(self):
        wo = self._make_wo('incomplete')
        wo.status = 'blocked'
        wo.full_clean()  # Should not raise

    def test_blocked_to_incomplete(self):
        wo = self._make_wo('blocked')
        wo.status = 'incomplete'
        wo.full_clean()  # Should not raise

    def test_complete_is_terminal(self):
        wo = self._make_wo('complete')
        wo.status = 'incomplete'
        with self.assertRaises(ValidationError):
            wo.full_clean()
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.WorkOrderStatusTest -v2`
Expected: `test_new_wo_starts_incomplete` and `test_draft_not_in_choices` FAIL (WO still defaults to `draft`)

- [ ] **Step 3: Update WorkOrder model**

In `apps/jobs/models.py`, replace the WorkOrder status choices and default, and add `clean()`:

```python
class WorkOrder(AbstractWorkContainer):
    WORK_ORDER_STATUS_CHOICES = [
        ('incomplete', 'Incomplete'),
        ('blocked', 'Blocked'),
        ('complete', 'Complete'),
    ]

    VALID_TRANSITIONS = {
        'incomplete': ['blocked', 'complete'],
        'blocked': ['incomplete'],
        'complete': [],
    }

    work_order_id = models.AutoField(primary_key=True)
    status = models.CharField(max_length=20, choices=WORK_ORDER_STATUS_CHOICES, default='incomplete')

    def clean(self):
        super().clean()
        if self.pk:
            try:
                old_wo = WorkOrder.objects.get(pk=self.pk)
                old_status = old_wo.status
                if old_status != self.status:
                    valid_next = self.VALID_TRANSITIONS.get(old_status, [])
                    if self.status not in valid_next:
                        raise ValidationError(
                            f'Cannot transition WorkOrder from {old_status} to {self.status}. '
                            f'Valid transitions: {", ".join(valid_next) if valid_next else "none (terminal state)"}'
                        )
            except WorkOrder.DoesNotExist:
                pass

    class Meta:
        db_table = 'workorders'
```

- [ ] **Step 4: Update WorkOrderService creation methods**

In `apps/jobs/services.py`, update `create_direct()` and `create_from_template()` to remove the explicit `status='draft'` (the new default `'incomplete'` will be used automatically):

In `create_direct()` (~line 106): remove `status='draft'` from the `WorkOrder.objects.create()` call.

In `create_from_template()` (~line 88): change `status='draft'` to remove it (or leave it — default handles it).

`create_from_estimate()` already uses `status='incomplete'` — no change needed.

- [ ] **Step 5: Create migration**

Run: `python manage.py makemigrations jobs`

This migration changes the default and choices. Any existing `draft` WOs in the dev database will need a data migration or manual update. Add a data migration that updates `draft` → `incomplete`:

```python
# In the generated migration, add a RunPython operation:
def migrate_draft_to_incomplete(apps, schema_editor):
    WorkOrder = apps.get_model('jobs', 'WorkOrder')
    WorkOrder.objects.filter(status='draft').update(status='incomplete')
```

- [ ] **Step 6: Remove `reopen` status action from WorkOrderViewSet**

In `apps/api/work_orders/views.py`, the `reopen` action was the only way to go from `draft → incomplete`. With no draft state, `reopen` is only for `blocked → incomplete`. Keep the action but update the comment to clarify its purpose. The `requires_reason` is still appropriate for unblocking.

- [ ] **Step 7: Run tests to verify all pass**

Run: `python manage.py test tests.test_task_lifecycle.WorkOrderStatusTest -v2`
Expected: All PASS

- [ ] **Step 8: Run full test suite**

Run: `python manage.py test`
Expected: Check for any existing tests that create WOs with `status='draft'` or expect draft behavior. Fix those tests to use `'incomplete'` or remove the explicit status (new default handles it).

- [ ] **Step 9: Commit**

```bash
git add apps/jobs/models.py apps/jobs/services.py apps/jobs/migrations/ apps/api/work_orders/views.py tests/test_task_lifecycle.py
git commit -m "feat: remove draft state from WorkOrder, add transition validation"
```

---

## Chunk 2: TaskLifecycleService

### Task 4: Implement start_task

**Files:**
- Modify: `apps/jobs/services.py` (add TaskLifecycleService after TaskService, ~line 341)
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests for start_task**

Append to `tests/test_task_lifecycle.py`:

```python
from unittest.mock import patch
from django.utils import timezone


class StartTaskTest(BaseTestCase):
    """Test TaskLifecycleService.start_task()."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.user = User.objects.first()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_start_task_changes_status(self):
        from apps.jobs.services import TaskLifecycleService
        result = TaskLifecycleService.start_task(self.task.pk, self.user)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')

    def test_start_task_creates_blep(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        TaskLifecycleService.start_task(self.task.pk, self.user)
        blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)

    def test_start_task_rejects_non_pending(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_task(self.task.pk, self.user)

    def test_start_task_rejects_worksheet_task(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.estimates.models import EstWorksheet
        ws = EstWorksheet.objects.create(job=self.job)
        ws_task = Task.objects.create(
            est_worksheet=ws, name="WS task",
            units="hours", rate="10.00", est_qty="1",
        )
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_task(ws_task.pk, self.user)

    def test_start_task_closes_users_other_open_blep(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        other_task = Task.objects.create(
            work_order=self.wo, name="Other task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=other_task.pk).update(status='in_progress')
        old_blep = Blep.objects.create(
            task=other_task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.start_task(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    def test_start_task_consumes_materials(self):
        from apps.jobs.services import TaskLifecycleService
        with patch('apps.inventory.services.InventoryService.consume_material') as mock_consume:
            from apps.inventory.models import Material
            material = Material.objects.create(
                task=self.task, description="Test material",
                quantity=5, unit_cost="10.00", sell_price="15.00",
            )
            TaskLifecycleService.start_task(self.task.pk, self.user)
            mock_consume.assert_called_once_with(material)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_task_lifecycle.StartTaskTest -v2`
Expected: FAIL — `ImportError: cannot import name 'TaskLifecycleService'`

- [ ] **Step 3: Implement TaskLifecycleService.start_task**

Add to the end of `apps/jobs/services.py`:

```python
class TaskLifecycleService:
    """Service for Task lifecycle operations (start, complete, block, etc.)."""

    @staticmethod
    def start_task(task_pk, user):
        """Start a pending task: consume materials, close user's other bleps, create blep.

        Transition: pending → in_progress
        Only valid on WorkOrder tasks where WO is not draft.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if not task.work_order:
                raise ValidationError("Lifecycle operations are only valid on WorkOrder tasks.")
            if task.status != 'pending':
                raise ValidationError(
                    f"Cannot start task: status is '{task.status}', must be 'pending'."
                )

            # Close user's open blep on any task
            from apps.jobs.models import Blep
            Blep.objects.filter(
                user=user, end_time__isnull=True,
            ).update(end_time=timezone.now())

            # Transition status (use .update() to bypass save()/full_clean() overhead —
            # service owns all validation, model clean() is just a safety net)
            Task.objects.filter(pk=task.pk).update(status='in_progress')

            # Consume materials
            from apps.inventory.services import InventoryService
            for material in task.materials.all():
                InventoryService.consume_material(material)

            # Create blep
            blep = Blep.objects.create(
                task=task, user=user, start_time=timezone.now(),
            )

            return {'task': task, 'blep': blep}
```

Also add `from django.utils import timezone` to the imports at the top of the file if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.StartTaskTest -v2`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_task_lifecycle.py
git commit -m "feat: implement TaskLifecycleService.start_task"
```

### Task 5: Implement complete_task

**Files:**
- Modify: `apps/jobs/services.py`
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests for complete_task**

Append to `tests/test_task_lifecycle.py`:

```python
class CompleteTaskTest(BaseTestCase):
    """Test TaskLifecycleService.complete_task()."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.user = User.objects.first()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_complete_from_in_progress(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'complete')

    def test_complete_from_pending(self):
        from apps.jobs.services import TaskLifecycleService
        TaskLifecycleService.complete_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'complete')

    def test_complete_closes_open_bleps(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.complete_task(self.task.pk)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_complete_rejects_blocked(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='blocked')
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.complete_task(self.task.pk)

    def test_complete_last_task_auto_completes_wo(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, 'complete')

    def test_complete_task_does_not_auto_complete_wo_if_others_remain(self):
        from apps.jobs.services import TaskLifecycleService
        other_task = Task.objects.create(
            work_order=self.wo, name="Other task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, 'incomplete')

    def test_complete_with_cancelled_siblings_auto_completes_wo(self):
        from apps.jobs.services import TaskLifecycleService
        other_task = Task.objects.create(
            work_order=self.wo, name="Cancelled task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=other_task.pk).update(status='cancelled')
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        TaskLifecycleService.complete_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, 'complete')
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.CompleteTaskTest -v2`
Expected: FAIL — `AttributeError: type object 'TaskLifecycleService' has no attribute 'complete_task'`

- [ ] **Step 3: Implement complete_task**

Add to `TaskLifecycleService` in `apps/jobs/services.py`:

```python
    @staticmethod
    def complete_task(task_pk):
        """Complete a task: close open bleps, check for WO auto-completion.

        Transition: pending → complete or in_progress → complete
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if task.status not in ('pending', 'in_progress'):
                raise ValidationError(
                    f"Cannot complete task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )

            # Close open bleps
            from apps.jobs.models import Blep
            Blep.objects.filter(
                task=task, end_time__isnull=True,
            ).update(end_time=timezone.now())

            Task.objects.filter(pk=task.pk).update(status='complete')
            task.status = 'complete'  # keep in-memory instance in sync

            TaskLifecycleService._check_wo_auto_complete(task)

            return task

    @staticmethod
    def _check_wo_auto_complete(task):
        """If all tasks on the WO are complete or cancelled, auto-complete the WO."""
        wo = task.work_order
        if not wo:
            return
        pending_tasks = Task.objects.filter(
            work_order=wo,
        ).exclude(
            status__in=['complete', 'cancelled'],
        ).exists()
        if not pending_tasks:
            WorkOrderService.update_status(wo.pk, 'complete')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.CompleteTaskTest -v2`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_task_lifecycle.py
git commit -m "feat: implement TaskLifecycleService.complete_task with WO auto-completion"
```

### Task 6: Implement block_task and unblock_task

**Files:**
- Modify: `apps/jobs/services.py`
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_task_lifecycle.py`:

```python
class BlockTaskTest(BaseTestCase):
    """Test TaskLifecycleService.block_task() and unblock_task()."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.user = User.objects.first()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_block_from_pending(self):
        from apps.jobs.services import TaskLifecycleService
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'blocked')

    def test_block_from_in_progress(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        TaskLifecycleService.block_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'blocked')

    def test_block_rejects_if_open_bleps(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        result = TaskLifecycleService.block_task(self.task.pk)
        self.assertIn('conflict', result)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')  # Not changed

    def test_block_rejects_complete(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='complete')
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.block_task(self.task.pk)

    def test_unblock(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='blocked')
        self.task.refresh_from_db()
        TaskLifecycleService.unblock_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')

    def test_unblock_rejects_non_blocked(self):
        from apps.jobs.services import TaskLifecycleService
        with self.assertRaises(ValidationError):
            TaskLifecycleService.unblock_task(self.task.pk)
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.BlockTaskTest -v2`
Expected: FAIL

- [ ] **Step 3: Implement block_task and unblock_task**

Add to `TaskLifecycleService` in `apps/jobs/services.py`:

```python
    @staticmethod
    def block_task(task_pk):
        """Block a task. Rejects if any worker has an open blep.

        Transition: pending → blocked or in_progress → blocked
        Returns conflict info dict if open bleps exist, otherwise returns the task.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if task.status not in ('pending', 'in_progress'):
                raise ValidationError(
                    f"Cannot block task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )

            # Check for open bleps
            from apps.jobs.models import Blep
            open_bleps = Blep.objects.filter(
                task=task, end_time__isnull=True,
            ).select_related('user')
            if open_bleps.exists():
                workers = [
                    {'user_id': b.user_id, 'name': str(b.user), 'blep_id': b.blep_id, 'started_at': b.start_time}
                    for b in open_bleps
                ]
                return {'conflict': 'active_workers', 'workers': workers}

            Task.objects.filter(pk=task.pk).update(status='blocked')
            task.status = 'blocked'
            return task

    @staticmethod
    def unblock_task(task_pk):
        """Unblock a task. No blep created.

        Transition: blocked → in_progress
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if task.status != 'blocked':
                raise ValidationError(
                    f"Cannot unblock task: status is '{task.status}', must be 'blocked'."
                )

            Task.objects.filter(pk=task.pk).update(status='in_progress')
            task.status = 'in_progress'
            return task
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.BlockTaskTest -v2`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_task_lifecycle.py
git commit -m "feat: implement TaskLifecycleService.block_task and unblock_task"
```

### Task 7: Implement cancel_task

**Files:**
- Modify: `apps/jobs/services.py`
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_task_lifecycle.py`:

```python
class CancelTaskTest(BaseTestCase):
    """Test TaskLifecycleService.cancel_task()."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.user = User.objects.first()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_cancel_from_pending(self):
        from apps.jobs.services import TaskLifecycleService
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'cancelled')

    def test_cancel_from_in_progress_closes_bleps(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.cancel_task(self.task.pk)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'cancelled')

    def test_cancel_from_blocked(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='blocked')
        self.task.refresh_from_db()
        TaskLifecycleService.cancel_task(self.task.pk)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'cancelled')

    def test_cancel_rejects_complete(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='complete')
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.cancel_task(self.task.pk)

    def test_cancel_last_non_terminal_triggers_wo_auto_complete(self):
        from apps.jobs.services import TaskLifecycleService
        other_task = Task.objects.create(
            work_order=self.wo, name="Complete task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=other_task.pk).update(status='complete')
        TaskLifecycleService.cancel_task(self.task.pk)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, 'complete')
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.CancelTaskTest -v2`
Expected: FAIL

- [ ] **Step 3: Implement cancel_task**

Add to `TaskLifecycleService` in `apps/jobs/services.py`:

```python
    @staticmethod
    def cancel_task(task_pk):
        """Cancel a task: close open bleps, check for WO auto-completion.

        Transition: pending/in_progress/blocked → cancelled
        Cancellation is a higher-authority action that overrides active work.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if task.status not in ('pending', 'in_progress', 'blocked'):
                raise ValidationError(
                    f"Cannot cancel task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )

            # Close open bleps
            from apps.jobs.models import Blep
            Blep.objects.filter(
                task=task, end_time__isnull=True,
            ).update(end_time=timezone.now())

            Task.objects.filter(pk=task.pk).update(status='cancelled')
            task.status = 'cancelled'

            TaskLifecycleService._check_wo_auto_complete(task)

            return task
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.CancelTaskTest -v2`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_task_lifecycle.py
git commit -m "feat: implement TaskLifecycleService.cancel_task"
```

### Task 8: Implement start_work and stop_work

**Files:**
- Modify: `apps/jobs/services.py`
- Test: `tests/test_task_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_task_lifecycle.py`:

```python
class StartStopWorkTest(BaseTestCase):
    """Test TaskLifecycleService.start_work() and stop_work()."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.user = User.objects.first()
        self.user2 = User.objects.create_user(username='worker2', password='test')
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        self.task.refresh_from_db()

    def test_start_work_creates_blep(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)

    def test_start_work_rejects_non_in_progress(self):
        from apps.jobs.services import TaskLifecycleService
        Task.objects.filter(pk=self.task.pk).update(status='pending')
        self.task.refresh_from_db()
        with self.assertRaises(ValidationError):
            TaskLifecycleService.start_work(self.task.pk, self.user)

    def test_start_work_closes_users_other_blep(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        other_task = Task.objects.create(
            work_order=self.wo, name="Other task",
            units="hours", rate="10.00", est_qty="1",
        )
        Task.objects.filter(pk=other_task.pk).update(status='in_progress')
        old_blep = Blep.objects.create(
            task=other_task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.start_work(self.task.pk, self.user)
        old_blep.refresh_from_db()
        self.assertIsNotNone(old_blep.end_time)

    def test_start_work_conflict_returns_worker_info(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        Blep.objects.create(
            task=self.task, user=self.user2, start_time=timezone.now(),
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user)
        self.assertIn('conflict', result)
        self.assertEqual(result['conflict'], 'active_worker')

    def test_start_work_join(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        existing_blep = Blep.objects.create(
            task=self.task, user=self.user2, start_time=timezone.now(),
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user, action='join')
        self.assertNotIn('conflict', result)
        # Both bleps open
        self.assertEqual(Blep.objects.filter(task=self.task, end_time__isnull=True).count(), 2)

    def test_start_work_takeover(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        existing_blep = Blep.objects.create(
            task=self.task, user=self.user2, start_time=timezone.now(),
        )
        result = TaskLifecycleService.start_work(self.task.pk, self.user, action='takeover')
        self.assertNotIn('conflict', result)
        existing_blep.refresh_from_db()
        self.assertIsNotNone(existing_blep.end_time)
        # Only new blep is open
        open_bleps = Blep.objects.filter(task=self.task, end_time__isnull=True)
        self.assertEqual(open_bleps.count(), 1)
        self.assertEqual(open_bleps.first().user, self.user)

    def test_stop_work_closes_blep(self):
        from apps.jobs.services import TaskLifecycleService
        from apps.jobs.models import Blep
        blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )
        TaskLifecycleService.stop_work(self.task.pk, self.user)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_no_open_blep_raises(self):
        from apps.jobs.services import TaskLifecycleService
        with self.assertRaises(ValidationError):
            TaskLifecycleService.stop_work(self.task.pk, self.user)
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle.StartStopWorkTest -v2`
Expected: FAIL

- [ ] **Step 3: Implement start_work and stop_work**

Add to `TaskLifecycleService` in `apps/jobs/services.py`:

```python
    @staticmethod
    def start_work(task_pk, user, action=None):
        """Start a work session on an in_progress task.

        No status change. Creates a blep for the user.
        If another worker has an open blep, returns conflict info unless
        action='join' or action='takeover' is specified.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)

            if task.status != 'in_progress':
                raise ValidationError(
                    f"Cannot start work: task status is '{task.status}', must be 'in_progress'."
                )

            from apps.jobs.models import Blep

            # Check for other workers BEFORE closing user's existing blep
            # (avoid closing user's blep if we're going to return a conflict)
            other_bleps = Blep.objects.filter(
                task=task, end_time__isnull=True,
            ).exclude(user=user).select_related('user')

            if other_bleps.exists() and action is None:
                other = other_bleps.first()
                return {
                    'conflict': 'active_worker',
                    'worker': {
                        'user_id': other.user_id,
                        'name': str(other.user),
                    },
                    'blep_id': other.blep_id,
                    'started_at': other.start_time,
                    'options': ['join', 'takeover'],
                }

            # Safe to proceed — close user's open blep on any task
            Blep.objects.filter(
                user=user, end_time__isnull=True,
            ).update(end_time=timezone.now())

            if action == 'takeover':
                other_bleps.update(end_time=timezone.now())

            blep = Blep.objects.create(
                task=task, user=user, start_time=timezone.now(),
            )
            return {'task': task, 'blep': blep}

    @staticmethod
    def stop_work(task_pk, user):
        """Stop a work session: close the user's open blep on this task."""
        with transaction.atomic():
            from apps.jobs.models import Blep
            updated = Blep.objects.filter(
                task_id=task_pk, user=user, end_time__isnull=True,
            ).update(end_time=timezone.now())

            if not updated:
                raise ValidationError("No open work session found for this user on this task.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle.StartStopWorkTest -v2`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python manage.py test`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py tests/test_task_lifecycle.py
git commit -m "feat: implement TaskLifecycleService.start_work and stop_work"
```

---

## Chunk 3: API Endpoints

### Task 9: Create TaskLifecycleMixin

**Files:**
- Modify: `apps/api/mixins.py` (add after TaskBundleMixin, ~line 267)
- Test: `tests/test_task_lifecycle_api.py` (create)

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_task_lifecycle_api.py
from django.utils import timezone
from rest_framework.test import APIClient
from apps.jobs.models import Task, WorkOrder, Blep
from tests.base import BaseTestCase


class TaskLifecycleAPITest(BaseTestCase):
    """Test task lifecycle API endpoints."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_start_task(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')

    def test_complete_task(self):
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/complete/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'complete')

    def test_block_task(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/block/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'blocked')

    def test_unblock_task(self):
        Task.objects.filter(pk=self.task.pk).update(status='blocked')
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/unblock/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')

    def test_cancel_task(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/cancel/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'cancelled')

    def test_start_work(self):
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Blep.objects.filter(task=self.task, user=self.user, end_time__isnull=True).exists())

    def test_stop_work(self):
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/stop-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Blep.objects.filter(task=self.task, user=self.user, end_time__isnull=True).exists())

    def test_bleps_list(self):
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/bleps/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_start_work_conflict_response(self):
        user2 = self._create_user('worker2')
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        Blep.objects.create(task=self.task, user=user2, start_time=timezone.now())
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('conflict', resp.data)

    def test_start_work_join(self):
        user2 = self._create_user('worker2')
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        Blep.objects.create(task=self.task, user=user2, start_time=timezone.now())
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'join'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('conflict', resp.data)

    def test_start_work_takeover(self):
        user2 = self._create_user('worker2')
        Task.objects.filter(pk=self.task.pk).update(status='in_progress')
        Blep.objects.create(task=self.task, user=user2, start_time=timezone.now())
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'takeover'}, format='json')
        self.assertEqual(resp.status_code, 200)
        # Only one open blep (the new user's)
        self.assertEqual(
            Blep.objects.filter(task=self.task, end_time__isnull=True).count(), 1
        )

    def test_invalid_transition_returns_400(self):
        Task.objects.filter(pk=self.task.pk).update(status='complete')
        url = f'/api/work-orders/{self.wo.pk}/tasks/{self.task.pk}/start/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)

    def test_wrong_task_returns_404(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/99999/start/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)

    def _create_user(self, username):
        from apps.core.models import User
        return User.objects.create_user(username=username, password='test')
```

- [ ] **Step 2: Run tests to verify failures**

Run: `python manage.py test tests.test_task_lifecycle_api -v2`
Expected: FAIL — 404 on all lifecycle endpoints (not yet registered)

- [ ] **Step 3: Implement TaskLifecycleMixin**

Add to `apps/api/mixins.py` after the `TaskBundleMixin` class:

```python
class TaskLifecycleMixin:
    """
    Adds task lifecycle action endpoints to a WorkOrder viewset.

    Endpoints:
        POST .../tasks/{task_id}/start/
        POST .../tasks/{task_id}/complete/
        POST .../tasks/{task_id}/block/
        POST .../tasks/{task_id}/unblock/
        POST .../tasks/{task_id}/cancel/
        POST .../tasks/{task_id}/start-work/
        POST .../tasks/{task_id}/stop-work/
        GET  .../tasks/{task_id}/bleps/
    """

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/start', url_name='task-start')
    def task_start(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            result = TaskLifecycleService.start_task(task.pk, request.user)
            return Response({'status': 'in_progress', 'blep_id': result['blep'].blep_id})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/complete', url_name='task-complete')
    def task_complete(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            TaskLifecycleService.complete_task(task.pk)
            return Response({'status': 'complete'})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/block', url_name='task-block')
    def task_block(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            result = TaskLifecycleService.block_task(task.pk)
            if isinstance(result, dict) and 'conflict' in result:
                return Response(result)
            return Response({'status': 'blocked'})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/unblock', url_name='task-unblock')
    def task_unblock(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            TaskLifecycleService.unblock_task(task.pk)
            return Response({'status': 'in_progress'})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/cancel', url_name='task-cancel')
    def task_cancel(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            TaskLifecycleService.cancel_task(task.pk)
            return Response({'status': 'cancelled'})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/start-work', url_name='task-start-work')
    def task_start_work(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        action_param = request.data.get('action')
        try:
            result = TaskLifecycleService.start_work(task.pk, request.user, action=action_param)
            if isinstance(result, dict) and 'conflict' in result:
                return Response(result)
            return Response({'status': 'ok', 'blep_id': result['blep'].blep_id})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'],
            url_path='tasks/(?P<task_id>[0-9]+)/stop-work', url_name='task-stop-work')
    def task_stop_work(self, request, pk=None, task_id=None):
        from apps.jobs.services import TaskLifecycleService
        task = self._get_lifecycle_task_or_404(pk, task_id)
        try:
            TaskLifecycleService.stop_work(task.pk, request.user)
            return Response({'status': 'ok'})
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'],
            url_path='tasks/(?P<task_id>[0-9]+)/bleps', url_name='task-bleps')
    def task_bleps(self, request, pk=None, task_id=None):
        from apps.jobs.models import Blep
        from apps.api.work_orders.serializers import BlepSerializer
        task = self._get_lifecycle_task_or_404(pk, task_id)
        bleps = Blep.objects.filter(task=task).order_by('-start_time')
        serializer = BlepSerializer(bleps, many=True)
        return Response(serializer.data)

    def _get_lifecycle_task_or_404(self, wo_pk, task_id):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_id, work_order_id=wo_pk)
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()
```

Add `ValidationError` to the imports at the top of `apps/api/mixins.py`:

```python
from django.core.exceptions import ValidationError
```

- [ ] **Step 4: Add TaskLifecycleMixin to WorkOrderViewSet**

In `apps/api/work_orders/views.py`, update the import and class definition:

```python
from apps.api.mixins import StatusTransitionMixin, TaskBundleMixin, TaskLifecycleMixin
```

```python
class WorkOrderViewSet(StatusTransitionMixin, TaskLifecycleMixin, TaskBundleMixin, viewsets.ModelViewSet):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_lifecycle_api -v2`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `python manage.py test`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/mixins.py apps/api/work_orders/views.py tests/test_task_lifecycle_api.py
git commit -m "feat: add task lifecycle API endpoints via TaskLifecycleMixin"
```

### Task 10: Add status to TaskSerializer

**Files:**
- Modify: `apps/api/worksheets/serializers.py` (where TaskSerializer lives)
- Test: `tests/test_task_lifecycle_api.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_task_lifecycle_api.py`:

```python
class TaskSerializerStatusTest(BaseTestCase):
    """Test that task status is included in API responses."""

    def setUp(self):
        super().setUp()
        from apps.core.models import User
        from apps.jobs.models import Job
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status='incomplete')
        self.task = Task.objects.create(
            work_order=self.wo, name="Test task",
            units="hours", rate="10.00", est_qty="1",
        )

    def test_task_list_includes_status(self):
        url = f'/api/work-orders/{self.wo.pk}/tasks/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('status', resp.data[0])
        self.assertEqual(resp.data[0]['status'], 'pending')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_lifecycle_api.TaskSerializerStatusTest -v2`
Expected: FAIL — `'status'` not in serializer fields

- [ ] **Step 3: Add status to TaskSerializer**

Find `TaskSerializer` in `apps/api/worksheets/serializers.py` and add `'status'` to its `fields` list and `read_only_fields`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_task_lifecycle_api.TaskSerializerStatusTest -v2`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python manage.py test`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/worksheets/serializers.py tests/test_task_lifecycle_api.py
git commit -m "feat: include task status in API serializer"
```

---

## Chunk 4: Update Seed Script

### Task 11: Update seed_data.sh for task lifecycle endpoints

The seed script creates WorkOrders with tasks and now needs to use lifecycle endpoints for scenarios involving task progress. Also, WO transition validation now requires `draft → incomplete` before `incomplete → complete`.

**Files:**
- Modify: `scripts/seed_data.sh`

- [ ] **Step 1: Verify existing WO flows still work**

Since Task 3 removed the `draft` state and WOs now start in `incomplete`, the existing seed script flows that create WOs and then complete them should work without any workaround — `incomplete → complete` is a valid transition. No `reopen` calls needed.

- [ ] **Step 3: Add task lifecycle calls to relevant scenarios**

For the "in progress" scenarios (Jobs 7, 11), use the new task endpoints to start some tasks:

For Job 7 (folding display easels — in progress, some work done):
```bash
# Get task IDs from the work order's task list
WO7_TASKS=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$BASE/api/work-orders/$WO7_ID/tasks/")
WO7_TASK1=$(echo "$WO7_TASKS" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['task_id'])")
WO7_TASK2=$(echo "$WO7_TASKS" | python3 -c "import sys,json; print(json.load(sys.stdin)[1]['task_id'])")

# Start and complete first two tasks
post "/api/work-orders/$WO7_ID/tasks/$WO7_TASK1/start/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/$WO7_TASK1/complete/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/$WO7_TASK2/start/" '{}' > /dev/null
post "/api/work-orders/$WO7_ID/tasks/$WO7_TASK2/complete/" '{}' > /dev/null

# Start third task (in progress)
WO7_TASK3=$(echo "$WO7_TASKS" | python3 -c "import sys,json; print(json.load(sys.stdin)[2]['task_id'])")
post "/api/work-orders/$WO7_ID/tasks/$WO7_TASK3/start/" '{}' > /dev/null
```

For Job 11 (service counter — WO complete, all tasks done) and Job 12 (spice display — completed): WOs now start in `incomplete`, so `POST .../complete/` works directly. Alternatively, start and complete all tasks to let auto-completion handle it.

- [ ] **Step 4: Test the seed script**

Run: `./scripts/seed_data.sh`
Expected: All scenarios create successfully without errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_data.sh
git commit -m "feat: update seed script for task lifecycle and WO transition validation"
```

### Task 12: Final integration test

- [ ] **Step 1: Run full test suite**

Run: `python manage.py test`
Expected: All PASS

- [ ] **Step 2: Start dev server and run seed script end-to-end**

```bash
python manage.py runserver &
./scripts/seed_data.sh
```

Verify all scenarios complete without errors and the summary output shows correct states.

- [ ] **Step 3: Spot-check via API**

```bash
# Check a task has status field
curl -s http://localhost:8000/api/work-orders/ | python3 -m json.tool | head -30

# Check bleps endpoint works
curl -s "http://localhost:8000/api/work-orders/{wo_id}/tasks/{task_id}/bleps/" | python3 -m json.tool
```

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "fix: integration test fixups"
```
