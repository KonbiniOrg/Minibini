"""
API-level tests: guarded mutations must return HTTP 400 (not 200/500) when the
Job is on_hold.

These are regression tests for the class of bug where an API endpoint used
serializer.save() directly (or called a service but didn't catch
ValidationError), bypassing the service-layer on_hold guard.  Each test
method would have caught a miss before the fix.

Endpoints covered:
  PATCH  /api/jobs/{id}/tasks/{tid}/           — TaskService.update_task
  DELETE /api/jobs/{id}/tasks/{tid}/           — TaskService.delete_task
  POST   /api/jobs/{id}/tasks/                 — TaskService.create_direct
  POST   /api/tasks/{id}/complete              — TaskLifecycleService.complete_task
  POST   /api/tasks/{id}/block                 — TaskLifecycleService.block_task
  POST   /api/tasks/{id}/unblock               — TaskLifecycleService.unblock_task
  POST   /api/tasks/{id}/cancel                — TaskLifecycleService.cancel_task
  POST   /api/jobs/{id}/reorder-tasks          — TaskService.reorder_tasks
  POST   /api/tasks/{task_pk}/assign/          — TaskService.assign
  POST   /api/jobs/{id}/materials/             — MaterialService.create_on_job
  POST   /api/tasks/{id}/materials/            — MaterialService.create_on_job
  PATCH  /api/tasks/{id}/materials/{mid}/      — MaterialService.update_pricing
  PATCH  /api/materials/{id}/                  — MaterialService.update_pricing
"""
from decimal import Decimal

from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_job(contact, statuses):
    import time
    job = Job.objects.create(
        job_number=f'J-API-HOLD-{time.time():.6f}',
        contact=contact,
        status=Job.STATUS_DRAFT,
    )
    for s in statuses:
        job.status = s
        job.save()
    job.refresh_from_db()
    return job


def _on_hold_job(contact):
    from apps.jobs.services import JobService
    job = _make_job(contact, [
        Job.STATUS_SUBMITTED,
        Job.STATUS_APPROVED,
    ])
    return JobService.hold_job(job.pk, 'guard test hold')


def _pending_task(job, scheme):
    return Task.objects.create(
        job=job, name='Guard Task', rate_scheme=scheme, status=Task.STATUS_PENDING,
    )


def _blocked_task(job, scheme):
    return Task.objects.create(
        job=job, name='Blocked Task', rate_scheme=scheme, status=Task.STATUS_BLOCKED,
    )


def _in_progress_task(job, scheme):
    return Task.objects.create(
        job=job, name='In Progress Task', rate_scheme=scheme,
        status=Task.STATUS_IN_PROGRESS,
    )


def _material(job, task=None, ac=None, pli=None):
    if ac is None:
        ac = AccountingCategory.objects.first()
    return Material.objects.create(
        job=job, task=task,
        description='Guard Material',
        quantity=Decimal('1.00'),
        unit_cost=Decimal('5.00'),
        sell_price=Decimal('10.00'),
        accounting_category=ac,
        inventory_item=pli,
    )


# ─── base ───────────────────────────────────────────────────────────────────

class OnHoldAPIGuardBase(BaseTestCase):
    """
    Provides an authenticated DRF client with can_manage_jobs, a contact,
    a FLAT_FEE rate scheme, and an on_hold job with a pending task.
    """

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Permission
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        perm = Permission.objects.get(codename='can_manage_jobs')
        if not self.user.user_permissions.filter(pk=perm.pk).exists():
            self.user.user_permissions.add(perm)
        # Re-fetch to clear permission cache
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.first()
        self.scheme = (
            RateScheme.objects.filter(algorithm=RateScheme.ENTERED_QTY).first()
            or RateScheme.objects.first()
        )
        self.ac = AccountingCategory.objects.first()

    # ── shared assertion ────────────────────────────────────────────────────

    def assert_400_on_hold(self, response, msg='on hold'):
        """Assert the response is 400 and mentions 'on hold' (case-insensitive)."""
        self.assertEqual(
            response.status_code, 400,
            f'Expected 400 for on_hold job; got {response.status_code}. '
            f'Body: {getattr(response, "data", None)}',
        )
        body_str = str(getattr(response, 'data', '')).lower()
        self.assertIn(
            msg.lower(), body_str,
            f'Expected "{msg}" in response body; got: {response.data}',
        )


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/jobs/{id}/tasks/{tid}/  (JobTaskMixin.task_detail PATCH)
# ═══════════════════════════════════════════════════════════════════════════

class TaskDetailPatchOnHoldTest(OnHoldAPIGuardBase):
    """
    This was the confirmed bypass: task_detail PATCH used serializer.save()
    directly instead of TaskService.update_task(). It returned 200; should 400.
    """

    def test_patch_task_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/jobs/{job.pk}/tasks/{task.pk}/'
        response = self.client.patch(url, {'name': 'Updated Name'}, format='json')
        self.assert_400_on_hold(response)

    def test_patch_task_returns_200_when_job_not_on_hold(self):
        """Smoke-test: non-on_hold jobs are still patchable."""
        job = _make_job(self.contact, [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
        ])
        task = _pending_task(job, self.scheme)
        url = f'/api/jobs/{job.pk}/tasks/{task.pk}/'
        response = self.client.patch(url, {'name': 'Updated Name'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['name'], 'Updated Name')


# ═══════════════════════════════════════════════════════════════════════════
# DELETE /api/jobs/{id}/tasks/{tid}/  (already routes through service)
# ═══════════════════════════════════════════════════════════════════════════

class TaskDetailDeleteOnHoldTest(OnHoldAPIGuardBase):

    def test_delete_task_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/jobs/{job.pk}/tasks/{task.pk}/'
        response = self.client.delete(url)
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/jobs/{id}/tasks/  (already routes through TaskService.create_direct)
# ═══════════════════════════════════════════════════════════════════════════

class TaskCreateOnHoldTest(OnHoldAPIGuardBase):

    def test_post_tasks_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        url = f'/api/jobs/{job.pk}/tasks/'
        response = self.client.post(url, {
            'name': 'New Task',
            'rate_scheme': self.scheme.pk,
        }, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{id}/complete   (TaskLifecycleService.complete_task)
# ═══════════════════════════════════════════════════════════════════════════

class TaskCompleteOnHoldTest(OnHoldAPIGuardBase):

    def test_complete_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/complete/'
        response = self.client.post(url, {}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{id}/block   (TaskLifecycleService.block_task)
# ═══════════════════════════════════════════════════════════════════════════

class TaskBlockOnHoldTest(OnHoldAPIGuardBase):

    def test_block_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/block/'
        response = self.client.post(url, {'reason': 'blocked'}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{id}/unblock   (TaskLifecycleService.unblock_task)
# ═══════════════════════════════════════════════════════════════════════════

class TaskUnblockOnHoldTest(OnHoldAPIGuardBase):

    def test_unblock_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _blocked_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/unblock/'
        response = self.client.post(url, {}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{id}/cancel   (TaskLifecycleService.cancel_task)
# ═══════════════════════════════════════════════════════════════════════════

class TaskCancelOnHoldTest(OnHoldAPIGuardBase):

    def test_cancel_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/cancel/'
        response = self.client.post(url, {}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/jobs/{id}/reorder-tasks   (TaskService.reorder_tasks)
# ═══════════════════════════════════════════════════════════════════════════

class TaskReorderOnHoldTest(OnHoldAPIGuardBase):

    def test_reorder_tasks_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        t1 = Task.objects.create(job=job, name='T1', rate_scheme=self.scheme, sort_order=1)
        t2 = Task.objects.create(job=job, name='T2', rate_scheme=self.scheme, sort_order=2)
        url = f'/api/jobs/{job.pk}/reorder-tasks/'
        response = self.client.post(url, {'task_id': t1.pk, 'direction': 'down'}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{task_pk}/assign/   (TaskService.assign)
# ═══════════════════════════════════════════════════════════════════════════

class TaskAssignOnHoldTest(OnHoldAPIGuardBase):

    def test_assign_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/assign/'
        # Unassign (null) is still a mutation and still guarded.
        response = self.client.post(url, {'assignee': None}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/jobs/{id}/materials/   (MaterialService.create_on_job)
# ═══════════════════════════════════════════════════════════════════════════

class JobMaterialCreateOnHoldTest(OnHoldAPIGuardBase):

    def test_post_job_materials_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        url = f'/api/jobs/{job.pk}/materials/'
        response = self.client.post(url, {
            'description': 'Material',
            'quantity': '1.00',
            'units': 'none',
            'unit_cost': '5.00',
            'sell_price': '10.00',
            'accounting_category': self.ac.pk,
        }, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/tasks/{id}/materials/   (MaterialService.create_on_job via task)
# ═══════════════════════════════════════════════════════════════════════════

class TaskMaterialCreateOnHoldTest(OnHoldAPIGuardBase):
    """
    This endpoint called MaterialService.create_on_job without catching
    ValidationError, so an on_hold job caused a 500.
    """

    def test_post_task_materials_returns_400_when_job_on_hold(self):
        job = _on_hold_job(self.contact)
        task = _pending_task(job, self.scheme)
        url = f'/api/tasks/{task.pk}/materials/'
        response = self.client.post(url, {
            'description': 'Material',
            'quantity': '1.00',
            'units': 'none',
            'unit_cost': '5.00',
            'sell_price': '10.00',
            'accounting_category': self.ac.pk,
        }, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/tasks/{id}/materials/{mid}/   (MaterialService.update_pricing)
# ═══════════════════════════════════════════════════════════════════════════

class TaskMaterialPatchOnHoldTest(OnHoldAPIGuardBase):
    """
    For the pricing path, update_pricing was called without a try/except,
    so an on_hold job caused a 500.  Non-pricing PATCH would also have
    slipped through without going through the guard at all.
    """

    def _make_on_hold_job_with_material(self):
        """Job starts in_progress (so the material can be created), then goes on_hold."""
        job = _make_job(self.contact, [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
        ])
        task = _pending_task(job, self.scheme)
        mat = _material(job, task=task, ac=self.ac)
        from apps.jobs.services import JobService
        JobService.hold_job(job.pk, 'guard test hold')
        job.refresh_from_db()
        mat.refresh_from_db()
        return job, task, mat

    def test_patch_task_material_pricing_returns_400_when_job_on_hold(self):
        job, task, mat = self._make_on_hold_job_with_material()
        url = f'/api/tasks/{task.pk}/materials/{mat.pk}/'
        response = self.client.patch(url, {'unit_cost': '9.00'}, format='json')
        self.assert_400_on_hold(response)

    def test_patch_task_material_description_returns_400_when_job_on_hold(self):
        """Non-pricing PATCH also mutates the material and must be guarded."""
        job, task, mat = self._make_on_hold_job_with_material()
        url = f'/api/tasks/{task.pk}/materials/{mat.pk}/'
        response = self.client.patch(url, {'description': 'Updated'}, format='json')
        self.assert_400_on_hold(response)


# ═══════════════════════════════════════════════════════════════════════════
# PATCH /api/materials/{id}/   (MaterialService.update_pricing / flat path)
# ═══════════════════════════════════════════════════════════════════════════

class FlatMaterialPatchOnHoldTest(OnHoldAPIGuardBase):
    """
    MaterialViewSet.partial_update called update_pricing without try/except
    for the pricing path; used serializer.save() for the non-pricing path
    (which bypasses the guard entirely).
    """

    def _make_on_hold_job_with_material(self, with_pli=False):
        job = _make_job(self.contact, [
            Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
        ])
        pli = None
        if with_pli:
            from apps.inventory.models import InventoryItem
            pli = InventoryItem.objects.create(
                code='ONHOLD-PLI', description='guard pli',
                purchase_price=Decimal('5.00'), selling_price=Decimal('10.00'),
                accounting_category=self.ac)
        mat = _material(job, ac=self.ac, pli=pli)
        from apps.jobs.services import JobService
        JobService.hold_job(job.pk, 'guard test hold')
        job.refresh_from_db()
        mat.refresh_from_db()
        return job, mat

    def test_patch_material_pricing_returns_400_when_job_on_hold(self):
        # PLI-linked so the pricing patch reaches the on-hold guard (a freeform
        # material would be rejected first by the freeform-cost guard).
        job, mat = self._make_on_hold_job_with_material(with_pli=True)
        url = f'/api/materials/{mat.pk}/'
        response = self.client.patch(url, {'unit_cost': '9.00'}, format='json')
        self.assert_400_on_hold(response)

    def test_patch_material_description_returns_400_when_job_on_hold(self):
        """Non-pricing PATCH must also be guarded."""
        job, mat = self._make_on_hold_job_with_material()
        url = f'/api/materials/{mat.pk}/'
        response = self.client.patch(url, {'description': 'Updated'}, format='json')
        self.assert_400_on_hold(response)
