"""
Tests that Task and Material mutations are rejected while a Job is on_hold.

Coverage:
- TaskLifecycleService: complete_task, block_task, unblock_task, cancel_task
- TaskService: create_direct, update_task, delete_task, reorder_tasks, assign,
  create_from_template
- MaterialService: create_on_job, update_pricing

Each guarded method has two test cases:
  - _blocked: on_hold job raises ValidationError with "on hold" in the message
  - _allowed: in_progress job succeeds (no error)

Methods deliberately NOT tested here (already covered by blep guard):
  start_work, stop_work, cancel_work
"""
from decimal import Decimal
from django.core.exceptions import ValidationError

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, Task, ServiceItem
from apps.jobs.services import TaskService, TaskLifecycleService
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.contacts.models import Contact


# ─── helpers ───────────────────────────────────────────────────────────────

def _make_job(contact, status_path):
    """Create a Job and walk it through the given sequence of statuses."""
    import time
    job = Job.objects.create(
        job_number=f'J-HOLD-GUARD-{time.time()}',
        contact=contact,
        status=Job.STATUS_DRAFT,
    )
    for s in status_path:
        job.status = s
        job.save()
    job.refresh_from_db()
    return job


def _on_hold_job(contact):
    return _make_job(contact, [
        Job.STATUS_SUBMITTED,
        Job.STATUS_APPROVED,
        Job.STATUS_ON_HOLD,
    ])


def _in_progress_job(contact):
    return _make_job(contact, [
        Job.STATUS_SUBMITTED,
        Job.STATUS_APPROVED,
        Job.STATUS_IN_PROGRESS,
    ])


def _pending_task(job, scheme):
    """Create a pending Task on the given job."""
    return Task.objects.create(
        job=job,
        name='Test Task',
        service_item=scheme,
        status=Task.STATUS_PENDING,
    )


def _blocked_task(job, scheme):
    """Create a BLOCKED Task on the given job (in_progress → blocked transition)."""
    task = Task.objects.create(
        job=job,
        name='Blocked Task',
        service_item=scheme,
        status=Task.STATUS_BLOCKED,
    )
    return task


def _in_progress_task(job, scheme):
    """Create an IN_PROGRESS Task directly (no blep needed — direct DB state for guard tests)."""
    return Task.objects.create(
        job=job,
        name='In Progress Task',
        service_item=scheme,
        status=Task.STATUS_IN_PROGRESS,
    )


def _material(job, task=None, ac=None):
    """Create a PENDING Material on the given job (and optionally task)."""
    from apps.core.models import AccountingCategory
    if ac is None:
        ac = AccountingCategory.objects.first()
    return Material.objects.create(
        job=job,
        task=task,
        description='Test Material',
        quantity=Decimal('1.00'),
        unit_cost=Decimal('5.00'),
        sell_price=Decimal('10.00'),
        accounting_category=ac,
    )


# ─── shared setUp ──────────────────────────────────────────────────────────

class OnHoldGuardBase(BaseTestCase):
    """
    Base for all on_hold guard tests.

    Fixture provides: a Contact, a ServiceItem with pk=1, a User 'admin',
    and AccountingCategories.
    """

    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        # Prefer a FLAT_FEE scheme so we don't need bleps to complete tasks.
        self.scheme = (
            ServiceItem.objects.filter(algorithm=ServiceItem.FLAT_FEE).first()
            or ServiceItem.objects.first()
        )
        self.user = User.objects.get(username='admin')
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.first()


# ═══════════════════════════════════════════════════════════════════════════
# TaskLifecycleService guards
# ═══════════════════════════════════════════════════════════════════════════

class CompleteTaskOnHoldTest(OnHoldGuardBase):

    def setUp(self):
        super().setUp()
        # complete_task checks algorithm before the guard fires only if we call
        # the guard first. Until the guard is in place, we need a FLAT_FEE
        # scheme so TaskTimeRequired doesn't mask the missing ValidationError.
        flat_fee = ServiceItem.objects.filter(algorithm=ServiceItem.FLAT_FEE).first()
        if flat_fee is None:
            self.skipTest('No FLAT_FEE ServiceItem in fixture.')
        self.scheme = flat_fee

    def test_complete_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.complete_task(task.pk)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_complete_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        result = TaskLifecycleService.complete_task(task.pk)
        self.assertEqual(result.status, Task.STATUS_COMPLETE)


class BlockTaskOnHoldTest(OnHoldGuardBase):

    def test_block_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.block_task(task.pk, reason='blocked for test')
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_block_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        result = TaskLifecycleService.block_task(task.pk, reason='blocked')
        # Returns the task (or a conflict dict for active workers; no workers here).
        self.assertEqual(result.status, Task.STATUS_BLOCKED)


class UnblockTaskOnHoldTest(OnHoldGuardBase):

    def test_unblock_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _blocked_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.unblock_task(task.pk)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_unblock_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _blocked_task(job, self.scheme)
        result = TaskLifecycleService.unblock_task(task.pk)
        self.assertEqual(result.status, Task.STATUS_IN_PROGRESS)


class CancelTaskOnHoldTest(OnHoldGuardBase):

    def test_cancel_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskLifecycleService.cancel_task(task.pk)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_cancel_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        result = TaskLifecycleService.cancel_task(task.pk)
        self.assertEqual(result.status, Task.STATUS_CANCELLED)


# ═══════════════════════════════════════════════════════════════════════════
# TaskService guards
# ═══════════════════════════════════════════════════════════════════════════

class CreateDirectTaskOnHoldTest(OnHoldGuardBase):

    def test_create_direct_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.create_direct(
                job,
                name='New Task',
                service_item_id=self.scheme.pk,
            )
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_create_direct_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = TaskService.create_direct(
            job,
            name='New Task',
            service_item_id=self.scheme.pk,
        )
        self.assertIsNotNone(task.pk)
        self.assertEqual(task.job, job)


class UpdateTaskOnHoldTest(OnHoldGuardBase):

    def test_update_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.update_task(task.pk, name='Updated Name')
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_update_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        result = TaskService.update_task(task.pk, name='Updated Name')
        self.assertEqual(result.name, 'Updated Name')


class DeleteTaskOnHoldTest(OnHoldGuardBase):

    def test_delete_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.delete_task(task.pk)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_delete_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        pk = task.pk
        TaskService.delete_task(pk)
        self.assertFalse(Task.objects.filter(pk=pk).exists())


class ReorderTasksOnHoldTest(OnHoldGuardBase):

    def test_reorder_tasks_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        t1 = Task.objects.create(job=job, name='T1', service_item=self.scheme, sort_order=1)
        t2 = Task.objects.create(job=job, name='T2', service_item=self.scheme, sort_order=2)
        with self.assertRaises(ValidationError) as ctx:
            TaskService.reorder_tasks(t1.pk, 'down')
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_reorder_tasks_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        t1 = Task.objects.create(job=job, name='T1', service_item=self.scheme, sort_order=1)
        t2 = Task.objects.create(job=job, name='T2', service_item=self.scheme, sort_order=2)
        TaskService.reorder_tasks(t1.pk, 'down')
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.sort_order, 2)
        self.assertEqual(t2.sort_order, 1)


class AssignTaskOnHoldTest(OnHoldGuardBase):

    def test_assign_task_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        # unassign (assignee_id=None) — still a mutation
        with self.assertRaises(ValidationError) as ctx:
            TaskService.assign(task, assignee_id=None)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_assign_task_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        task = _pending_task(job, self.scheme)
        # Unassign is always safe (no est_worker_time required)
        result = TaskService.assign(task, assignee_id=None)
        self.assertIsNone(result.assignee_id)


class CreateFromTemplateOnHoldTest(OnHoldGuardBase):

    def _get_flat_fee_template(self):
        from apps.estimates.models import TaskTemplate
        scheme = ServiceItem.objects.filter(algorithm=ServiceItem.FLAT_FEE).first()
        if scheme is None:
            self.skipTest('No FLAT_FEE ServiceItem in fixture.')
        tmpl, _ = TaskTemplate.objects.get_or_create(
            template_name='Guard Test Template',
            defaults={
                'service_item': scheme,
                'default_billable_qty': Decimal('1'),
                'is_active': True,
            },
        )
        return tmpl

    def test_create_from_template_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        tmpl = self._get_flat_fee_template()
        with self.assertRaises(ValidationError) as ctx:
            TaskService.create_from_template(tmpl, job)
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_create_from_template_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        tmpl = self._get_flat_fee_template()
        task = TaskService.create_from_template(tmpl, job)
        self.assertIsNotNone(task.pk)
        self.assertEqual(task.job, job)


# ═══════════════════════════════════════════════════════════════════════════
# MaterialService guards
# ═══════════════════════════════════════════════════════════════════════════

class MaterialCreateOnJobOnHoldTest(OnHoldGuardBase):

    def test_create_on_job_blocked_on_on_hold_job(self):
        job = _on_hold_job(self.contact)
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.create_on_job(
                job=job,
                description='Test Material',
                quantity=Decimal('2.00'),
                accounting_category=self.ac,
            )
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_create_on_job_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        mat = MaterialService.create_on_job(
            job=job,
            description='Test Material',
            quantity=Decimal('2.00'),
            accounting_category=self.ac,
        )
        self.assertIsNotNone(mat.pk)
        self.assertEqual(mat.job, job)


class MaterialUpdatePricingOnHoldTest(OnHoldGuardBase):

    def test_update_pricing_blocked_on_on_hold_job(self):
        # Create the material while job is still in a mutable state,
        # then place the job on_hold, then try to update pricing.
        job = _in_progress_job(self.contact)
        mat = _material(job, ac=self.ac)
        # Move job to on_hold
        job.status = Job.STATUS_ON_HOLD
        job.save()
        job.refresh_from_db()
        mat.refresh_from_db()
        with self.assertRaises(ValidationError) as ctx:
            MaterialService.update_pricing(mat, unit_cost=Decimal('7.00'))
        self.assertIn('on hold', str(ctx.exception).lower())

    def test_update_pricing_allowed_on_in_progress_job(self):
        job = _in_progress_job(self.contact)
        mat = _material(job, ac=self.ac)
        result = MaterialService.update_pricing(mat, unit_cost=Decimal('7.00'))
        self.assertEqual(result.unit_cost, Decimal('7.00'))
