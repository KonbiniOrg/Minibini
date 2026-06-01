# Job Duplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click "Duplicate…" of an existing Job into a new one, with two outcomes — an immediately-approved execution clone, or a draft that requires a new estimate.

**Architecture:** A new `JobService.duplicate_job(source_job, *, contact, path)` orchestrates the copy inside one transaction, always sourcing work from the source Job's execution layer (`Task`/`Material`). Outcome `'approved'` copies execution Tasks/Materials onto the new Job, creates earmarks, and walks `draft→submitted→approved` through the service (mirroring `apps/estimates/signals.py`). Outcome `'estimate'` maps the work into a fresh draft `EstWorksheet` as `PlanTask`/`PlanMaterial`. A thin DRF `@action` exposes it; a Svelte page drives it.

**Tech Stack:** Django 5.2 / DRF service+viewset, MySQL, Svelte 5 SPA (svelte-spa-router), Django `TestCase` + DRF `APIClient`.

**Spec:** `docs/plans/2026-06-01-job-duplication-design.md`

---

## File Structure

- **Modify** `apps/jobs/services.py` — add `JobService.duplicate_job` + private helpers (`_copy_deliverables`, `_copy_work_to_job`, `_copy_work_to_worksheet`, `_advance_to_approved`).
- **Modify** `apps/api/jobs/views.py` — add a `duplicate` `@action` on `JobViewSet`. (No `get_permissions` change needed — `duplicate` falls through to the default `[IsAuthenticated(), CanManageJobs()]`.)
- **Create** `tests/test_job_duplication.py` — service + API tests.
- **Create** `frontend/src/routes/jobs/DuplicateJobPage.svelte` — the intermediate page.
- **Modify** `frontend/src/App.svelte` — register the route + import.
- **Modify** `frontend/src/components/jobs/JobHeader.svelte` — add the "Duplicate…" link.
- **Modify** `docs/designs/jobs-tasks-and-worksheets.md` and `docs/designs/users-and-permissions.md` — document behavior + endpoint.

---

## Task 1: Service — Outcome A (immediately approved)

Implements `duplicate_job` end-to-end for `path='approved'`: create draft Job, copy deliverables + execution Tasks (with subtask hierarchy) + Materials, create earmarks, walk to `approved`. The `'estimate'` branch is a temporary `NotImplementedError` (filled in Task 2; nothing calls it until Task 3).

**Files:**
- Modify: `apps/jobs/services.py` (add methods to the `JobService` class, near `copy_from_worksheet` ~line 588)
- Test: `tests/test_job_duplication.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_duplication.py`:

```python
from decimal import Decimal
from datetime import timedelta
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import Configuration, AccountingCategory, HistoryEntry, User
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.estimates.models import EstWorksheet
from apps.inventory.models import Material, PlanMaterial, PriceListItem, Earmark
from apps.deliverables.models import Deliverable
from apps.jobs.services import JobService


def _make_scheme(suffix):
    ac = AccountingCategory.objects.create(code=f'DUP-{suffix}', name=f'dup-{suffix}')
    return RateScheme.objects.create(
        name=f'S-dup-{suffix}', algorithm=RateScheme.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class DuplicateJobTestBase(BaseTestCase):
    """Builds a representative source Job: 2 tasks (one a subtask), 2 materials
    (one task-attached + inventoried, one task-less + inventoried), 2 deliverables."""

    def setUp(self):
        super().setUp()
        # Job numbering config (duplicate_job calls generate_next_number('job')).
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-DUP-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='job_counter', defaults={'value': '0'})

        self.contact = Contact.objects.create(
            first_name='Source', last_name='Customer',
            email='src@example.com', work_number='555-0001',
        )
        self.other_contact = Contact.objects.create(
            first_name='New', last_name='Customer',
            email='new@example.com', work_number='555-0002',
        )
        self.category = AccountingCategory.objects.create(name='Material', code='DUPMAT')
        self.scheme = _make_scheme('a')
        self.plywood = PriceListItem.objects.create(
            code='DUP.PLY', description='Plywood', units='sheets',
            qty_on_hand=Decimal('20.00'), purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'), is_inventoried=True,
            accounting_category=self.category,
        )
        self.screws = PriceListItem.objects.create(
            code='DUP.SCR', description='Screws', units='ea',
            qty_on_hand=Decimal('50.00'), purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'), is_inventoried=True,
            accounting_category=self.category,
        )

        self.source = Job.objects.create(
            job_number='JOB-SRC-001', name='Cabinet run', description='Six uppers',
            contact=self.contact, customer_po_number='CUST-PO-9',
            due_date=None,
        )
        self.task_a = Task.objects.create(
            job=self.source, name='Build', description='Build the boxes',
            sort_order=1, est_worker_time=timedelta(hours=4),
            est_qty=Decimal('6'), rate_scheme=self.scheme,
        )
        self.task_b = Task.objects.create(
            job=self.source, name='Finish', description='Sand + seal',
            sort_order=2, est_worker_time=timedelta(hours=2),
            est_qty=Decimal('6'), rate_scheme=self.scheme,
            parent_task=self.task_a,
        )
        self.material_attached = Material.objects.create(
            job=self.source, task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        self.material_loose = Material.objects.create(
            job=self.source, task=None, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'),
            sell_price=Decimal('12.00'),
        )
        self.deliverable_1 = Deliverable.objects.create(
            job=self.source, description='Upper cabinet', qty_ordered=Decimal('6'),
            units='ea', sort_order=10,
        )
        self.deliverable_2 = Deliverable.objects.create(
            job=self.source, description='Toe kick', qty_ordered=Decimal('3'),
            units='ea', sort_order=20,
        )


class DuplicateApprovedTest(DuplicateJobTestBase):

    def test_creates_approved_job_with_fresh_metadata(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.other_contact, path='approved')
        new_job.refresh_from_db()
        self.assertEqual(new_job.status, Job.STATUS_APPROVED)
        self.assertIsNotNone(new_job.start_date)            # set by the approved transition
        self.assertEqual(new_job.contact_id, self.other_contact.pk)
        self.assertEqual(new_job.name, 'Cabinet run')
        self.assertEqual(new_job.description, 'Six uppers')
        self.assertNotEqual(new_job.job_number, self.source.job_number)
        self.assertTrue(new_job.job_number.startswith('JOB-DUP-'))
        self.assertEqual(new_job.customer_po_number, '')    # not copied
        self.assertIsNone(new_job.due_date)                 # not copied

    def test_copies_deliverables(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        delivs = Deliverable.objects.filter(job=new_job).order_by('sort_order')
        self.assertEqual([d.description for d in delivs], ['Upper cabinet', 'Toe kick'])
        self.assertEqual(delivs[0].qty_ordered, Decimal('6'))

    def test_copies_tasks_reset_and_preserves_hierarchy(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        tasks = {t.name: t for t in Task.objects.filter(job=new_job)}
        self.assertEqual(set(tasks), {'Build', 'Finish'})
        build, finish = tasks['Build'], tasks['Finish']
        # reset fields
        self.assertEqual(finish.status, Task.STATUS_PENDING)
        self.assertIsNone(finish.assignee_id)
        self.assertIsNone(finish.actual_qty)
        self.assertIsNone(finish.source_plan_task_id)
        # carried fields
        self.assertEqual(finish.est_qty, Decimal('6'))
        self.assertEqual(finish.rate_scheme_id, self.scheme.pk)
        # hierarchy remapped to the NEW build task (not the source's)
        self.assertEqual(finish.parent_task_id, build.task_id)

    def test_copies_materials_with_task_links_and_reset_state(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        mats = Material.objects.filter(job=new_job)
        self.assertEqual(mats.count(), 2)
        attached = mats.get(price_list_item=self.plywood)
        loose = mats.get(price_list_item=self.screws)
        self.assertIsNotNone(attached.task_id)
        self.assertEqual(attached.task.job_id, new_job.pk)   # points at NEW task
        self.assertIsNone(loose.task_id)
        self.assertEqual(attached.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertIsNone(attached.po_line_item_id)
        self.assertIsNone(attached.source_plan_material_id)

    def test_creates_earmarks(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.plywood, job=new_job).quantity,
            Decimal('5.00'))
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.screws, job=new_job).quantity,
            Decimal('2.00'))

    def test_records_history_for_each_status_hop(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        entries = HistoryEntry.objects.filter(object_type='job', object_id=new_job.pk)
        new_statuses = {e.changes.get('status', {}).get('new') for e in entries}
        self.assertIn(Job.STATUS_SUBMITTED, new_statuses)
        self.assertIn(Job.STATUS_APPROVED, new_statuses)

    def test_no_estimate_or_worksheet_on_new_job(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        self.assertFalse(EstWorksheet.objects.filter(job=new_job).exists())
        self.assertFalse(new_job.estimate_set.exists())

    def test_source_job_unchanged(self):
        JobService.duplicate_job(self.source, contact=self.other_contact, path='approved')
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, Job.STATUS_DRAFT)
        self.assertEqual(self.source.contact_id, self.contact.pk)
        self.assertEqual(Task.objects.filter(job=self.source).count(), 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_job_duplication.DuplicateApprovedTest -v 2`
Expected: FAIL — `AttributeError: type object 'JobService' has no attribute 'duplicate_job'`.

- [ ] **Step 3: Implement `duplicate_job` + Outcome A helpers**

In `apps/jobs/services.py`, add these methods to the `JobService` class (place them just after `copy_from_worksheet`). Note `copy_active_modifiers` is already importable from `apps.jobs.models`.

```python
    @staticmethod
    def duplicate_job(source_job, *, contact, path):
        """Copy `source_job` into a new Job. `path` is 'approved' or 'estimate'.
        Work is always sourced from the source Job's execution Tasks/Materials.
        Returns the new (refreshed) Job."""
        from django.db import transaction
        if path not in ('approved', 'estimate'):
            raise ValidationError(
                f"Invalid path '{path}'; expected 'approved' or 'estimate'.")
        with transaction.atomic():
            new_job = JobService.create_job(
                name=source_job.name,
                description=source_job.description,
                contact=contact,
            )
            JobService._copy_deliverables(source_job, new_job)
            if path == 'approved':
                JobService._copy_work_to_job(source_job, new_job)
                from apps.inventory.services import InventoryService
                InventoryService.create_earmarks_for_job(new_job)
                JobService._advance_to_approved(new_job, source_job)
            else:
                JobService._copy_work_to_worksheet(source_job, new_job)
            new_job.refresh_from_db()
            return new_job

    @staticmethod
    def _copy_deliverables(source_job, new_job):
        from apps.deliverables.services import DeliverableService
        from apps.deliverables.models import Deliverable
        for d in Deliverable.objects.filter(job=source_job).order_by('sort_order', 'pk'):
            DeliverableService.create(
                job_id=new_job.pk,
                description=d.description,
                qty_ordered=d.qty_ordered,
                units=d.units,
                sort_order=d.sort_order,
            )

    @staticmethod
    def _copy_work_to_job(source_job, new_job):
        """Outcome A: copy execution Tasks (reset, hierarchy preserved) + Materials."""
        from apps.jobs.models import Task, copy_active_modifiers
        from apps.inventory.models import Material
        from apps.inventory.services import MaterialService

        source_tasks = list(
            Task.objects.filter(job=source_job).order_by('sort_order', 'pk'))
        task_map = {}  # source task_id -> new Task
        for task in source_tasks:
            new_task = Task.objects.create(
                job=new_job,
                name=task.name,
                description=task.description,
                sort_order=task.sort_order,
                est_worker_time=task.est_worker_time,
                est_qty=task.est_qty,
                rate_scheme=task.rate_scheme,
                active_modifiers=copy_active_modifiers(task.active_modifiers),
                status=Task.STATUS_PENDING,
            )
            task_map[task.pk] = new_task
        # Second pass: wire parent_task hierarchy onto the new tasks.
        for task in source_tasks:
            if task.parent_task_id and task.parent_task_id in task_map:
                new_task = task_map[task.pk]
                new_task.parent_task = task_map[task.parent_task_id]
                new_task.save()
        # Materials (task-attached follow their remapped task; task-less stay loose).
        for material in Material.objects.filter(job=source_job).order_by('pk'):
            MaterialService.create_on_job(
                job=new_job,
                task=task_map.get(material.task_id),
                description=material.description,
                quantity=material.quantity,
                units=material.units,
                unit_cost=material.unit_cost,
                sell_price=material.sell_price,
                price_list_item=material.price_list_item,
                accounting_category=material.accounting_category,
            )

    @staticmethod
    def _advance_to_approved(new_job, source_job):
        """Walk draft -> submitted -> approved through the service, recording a
        HistoryEntry per hop. Mirrors apps/estimates/signals.py:96-116."""
        from apps.core.models import HistoryEntry, User
        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )
        action_desc = f"Duplicated from {source_job.job_number}"
        JobService.update_status(new_job.pk, Job.STATUS_SUBMITTED)
        HistoryEntry.objects.create(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_DRAFT, 'new': Job.STATUS_SUBMITTED},
                     '_action': action_desc},
        )
        JobService.update_status(new_job.pk, Job.STATUS_APPROVED)
        HistoryEntry.objects.create(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_SUBMITTED, 'new': Job.STATUS_APPROVED},
                     '_action': action_desc},
        )

    @staticmethod
    def _copy_work_to_worksheet(source_job, new_job):
        raise NotImplementedError("estimate path implemented in Task 2")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test tests.test_job_duplication.DuplicateApprovedTest -v 2`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_job_duplication.py
git commit -m "feat(jobs): duplicate_job — immediately-approved outcome"
```

---

## Task 2: Service — Outcome B (requires a new estimate)

Implements `_copy_work_to_worksheet`: a fresh draft `EstWorksheet` with `PlanTask`/`PlanMaterial` mapped from the source's execution Tasks/Materials, including the `est_qty` fallback and task-attachment preservation. No earmarks; Job stays `draft`.

**Files:**
- Modify: `apps/jobs/services.py` (replace the `_copy_work_to_worksheet` stub)
- Test: `tests/test_job_duplication.py` (add a class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job_duplication.py`:

```python
class DuplicateEstimateTest(DuplicateJobTestBase):

    def test_creates_draft_job_no_status_walk(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.other_contact, path='estimate')
        self.assertEqual(new_job.status, Job.STATUS_DRAFT)
        self.assertIsNone(new_job.start_date)
        self.assertEqual(new_job.contact_id, self.other_contact.pk)

    def test_creates_fresh_draft_worksheet(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        ws = EstWorksheet.objects.get(job=new_job)
        self.assertEqual(ws.status, EstWorksheet.STATUS_DRAFT)
        self.assertEqual(ws.version, 1)
        self.assertIsNone(ws.parent_id)
        self.assertIsNone(ws.estimate_id)

    def test_maps_tasks_to_plan_tasks(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        ws = EstWorksheet.objects.get(job=new_job)
        names = set(PlanTask.objects.filter(est_worksheet=ws).values_list('name', flat=True))
        self.assertEqual(names, {'Build', 'Finish'})
        build = PlanTask.objects.get(est_worksheet=ws, name='Build')
        self.assertEqual(build.est_qty, Decimal('6'))
        self.assertEqual(build.rate_scheme_id, self.scheme.pk)

    def test_maps_materials_preserving_task_attachment(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        ws = EstWorksheet.objects.get(job=new_job)
        build = PlanTask.objects.get(est_worksheet=ws, name='Build')
        attached = PlanMaterial.objects.get(est_worksheet=ws, price_list_item=self.plywood)
        loose = PlanMaterial.objects.get(est_worksheet=ws, price_list_item=self.screws)
        self.assertEqual(attached.plan_task_id, build.plan_task_id)
        self.assertIsNone(loose.plan_task_id)

    def test_no_earmarks_on_estimate_path(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        self.assertEqual(Earmark.objects.filter(job=new_job).count(), 0)

    def test_est_qty_falls_back_to_actual_qty_then_zero(self):
        # Task with no est_qty but an actual_qty -> PlanTask.est_qty = actual_qty.
        Task.objects.create(
            job=self.source, name='AdHoc', sort_order=3,
            rate_scheme=self.scheme, est_qty=None, actual_qty=Decimal('3.00'),
        )
        # Task with neither -> PlanTask.est_qty = 0.00.
        Task.objects.create(
            job=self.source, name='Bare', sort_order=4,
            rate_scheme=self.scheme, est_qty=None, actual_qty=None,
        )
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        ws = EstWorksheet.objects.get(job=new_job)
        self.assertEqual(
            PlanTask.objects.get(est_worksheet=ws, name='AdHoc').est_qty, Decimal('3.00'))
        self.assertEqual(
            PlanTask.objects.get(est_worksheet=ws, name='Bare').est_qty, Decimal('0.00'))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_job_duplication.DuplicateEstimateTest -v 2`
Expected: FAIL — `NotImplementedError: estimate path implemented in Task 2`.

- [ ] **Step 3: Implement `_copy_work_to_worksheet`**

In `apps/jobs/services.py`, replace the stub body:

```python
    @staticmethod
    def _copy_work_to_worksheet(source_job, new_job):
        """Outcome B: map execution Tasks/Materials into a fresh draft worksheet
        as PlanTasks/PlanMaterials. PlanTask requires a non-null est_qty, so fall
        back to actual_qty then 0.00 when the source Task has none. (PlanTask has
        no hierarchy, so subtask nesting is flattened; sort_order is preserved.)"""
        from decimal import Decimal
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import Task, PlanTask, copy_active_modifiers
        from apps.inventory.models import Material, PlanMaterial

        ws = EstWorksheet.objects.create(
            job=new_job, status=EstWorksheet.STATUS_DRAFT, version=1,
            parent=None, estimate=None,
        )
        task_map = {}  # source task_id -> new PlanTask
        for task in Task.objects.filter(job=source_job).order_by('sort_order', 'pk'):
            if task.est_qty is not None:
                est_qty = task.est_qty
            elif task.actual_qty is not None:
                est_qty = task.actual_qty
            else:
                est_qty = Decimal('0.00')
            plan_task = PlanTask.objects.create(
                est_worksheet=ws,
                name=task.name,
                description=task.description,
                sort_order=task.sort_order,
                est_worker_time=task.est_worker_time,
                est_qty=est_qty,
                rate_scheme=task.rate_scheme,
                active_modifiers=copy_active_modifiers(task.active_modifiers),
            )
            task_map[task.pk] = plan_task
        for material in Material.objects.filter(job=source_job).order_by('pk'):
            PlanMaterial.objects.create(
                est_worksheet=ws,
                plan_task=task_map.get(material.task_id),
                description=material.description,
                quantity=material.quantity,
                units=material.units,
                unit_cost=material.unit_cost,
                sell_price=material.sell_price,
                price_list_item=material.price_list_item,
                accounting_category=material.accounting_category,
            )
        return ws
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test tests.test_job_duplication.DuplicateEstimateTest -v 2`
Expected: PASS (6 tests).

Then run both service classes together:
Run: `python manage.py test tests.test_job_duplication -v 2`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_job_duplication.py
git commit -m "feat(jobs): duplicate_job — new-estimate (worksheet) outcome"
```

---

## Task 3: API — `duplicate` action on JobViewSet

**Files:**
- Modify: `apps/api/jobs/views.py` (add an `@action`; imports already present: `action`, `Response`, `status`, `ValidationError`, `JobService`)
- Test: `tests/test_job_duplication.py` (add an API class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job_duplication.py`:

```python
class DuplicateApiTest(DuplicateJobTestBase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.mgr = User.objects.create_user(username='dup_mgr', password='x')
        self.mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_jobs', content_type__app_label='core'))
        self.mgr = User.objects.get(pk=self.mgr.pk)  # refresh permission cache
        self.worker = User.objects.create_user(username='dup_worker', password='x')

    def _url(self):
        return f'/api/jobs/{self.source.pk}/duplicate/'

    def test_requires_can_manage_jobs(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 403, r.data)

    def test_approved_path_returns_new_job_id(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.other_contact.pk, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.data)
        new_job = Job.objects.get(pk=r.data['job_id'])
        self.assertEqual(new_job.status, Job.STATUS_APPROVED)
        self.assertEqual(new_job.contact_id, self.other_contact.pk)

    def test_estimate_path_returns_new_job_id(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'estimate'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(
            EstWorksheet.objects.filter(job_id=r.data['job_id']).exists())

    def test_bad_path_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'nope'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_missing_contact_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(), {'path': 'approved'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_unknown_contact_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': 999999, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_job_duplication.DuplicateApiTest -v 2`
Expected: FAIL — the POST returns 404 (no `duplicate` route) rather than the expected codes.

- [ ] **Step 3: Implement the action**

In `apps/api/jobs/views.py`, add this method to `JobViewSet` (e.g. after `populate_from_template`, ~line 205):

```python
    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate(self, request, pk=None):
        """Copy this Job into a new one. Body: {contact_id, path:'approved'|'estimate'}."""
        from apps.contacts.models import Contact
        source_job = self.get_object()
        path = request.data.get('path')
        if path not in ('approved', 'estimate'):
            return Response(
                {'path': ["Must be 'approved' or 'estimate'."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        contact_id = request.data.get('contact_id')
        if not contact_id:
            return Response(
                {'contact_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            contact = Contact.objects.get(pk=contact_id)
        except Contact.DoesNotExist:
            return Response(
                {'contact_id': ['Contact not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            new_job = JobService.duplicate_job(
                source_job, contact=contact, path=path)
        except ValidationError as e:
            return Response(
                {'detail': e.message if hasattr(e, 'message') else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({'job_id': new_job.pk}, status=status.HTTP_201_CREATED)
```

No `get_permissions` change is required: `duplicate` is not in `authenticated_only_actions`, so it falls through to the default `[IsAuthenticated(), CanManageJobs()]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test tests.test_job_duplication.DuplicateApiTest -v 2`
Expected: PASS (6 tests).

Then the whole module:
Run: `python manage.py test tests.test_job_duplication -v 2`
Expected: PASS (19 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/jobs/views.py tests/test_job_duplication.py
git commit -m "feat(api): POST /api/jobs/{id}/duplicate/ action"
```

---

## Task 4: Frontend — DuplicateJobPage, route, and link

No automated test (SPA has no unit-test harness here); verify via the Vite build + manual click-through.

**Files:**
- Create: `frontend/src/routes/jobs/DuplicateJobPage.svelte`
- Modify: `frontend/src/App.svelte`
- Modify: `frontend/src/components/jobs/JobHeader.svelte`

- [ ] **Step 1: Create `frontend/src/routes/jobs/DuplicateJobPage.svelte`**

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let sourceJob = $state(null);
  let contacts = $state([]);
  let selectedContactId = $state('');
  let path = $state('approved');
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);

  async function load() {
    loading = true;
    loadError = null;
    try {
      sourceJob = await api.get(`/api/jobs/${params.id}/`);
      const page = await api.get('/api/contacts/?page_size=100');
      contacts = page.results || [];
      selectedContactId = sourceJob.contact ? String(sourceJob.contact) : '';
    } catch (e) {
      loadError = e.message || 'Failed to load job';
    } finally {
      loading = false;
    }
  }

  async function submit() {
    submitting = true;
    try {
      const result = await api.post(`/api/jobs/${params.id}/duplicate/`, {
        contact_id: selectedContactId,
        path,
      });
      push(`/jobs/${result.job_id}`);
    } catch (e) {
      // api.js renders the error overlay; just re-enable the button.
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p><strong>Error:</strong> {loadError}</p>
{:else}
  <h2>Duplicate {sourceJob.job_number}</h2>

  <p><label for="contact"><strong>Customer *</strong></label><br>
    <select id="contact" bind:value={selectedContactId} required>
      <option value="">-- Select contact --</option>
      {#each contacts as c}
        <option value={String(c.contact_id)}>{c.name}</option>
      {/each}
    </select>
  </p>

  <fieldset>
    <legend><strong>What kind of copy?</strong></legend>
    <p><label>
      <input type="radio" name="path" value="approved" bind:group={path}>
      Immediately approved — ready to work, reuses the original's pricing as-is.
    </label></p>
    <p><label>
      <input type="radio" name="path" value="estimate" bind:group={path}>
      Requires a new estimate — re-quote before work starts.
    </label></p>
    <p><em>If rates or material prices may have moved since the original, choose
      "Requires a new estimate" to re-quote.</em></p>
  </fieldset>

  <p>
    <button type="button" onclick={submit}
            disabled={submitting || !selectedContactId}>
      {submitting ? 'Duplicating…' : 'Duplicate'}
    </button>
    <a href="#/jobs/{params.id}">Cancel</a>
  </p>
{/if}
```

- [ ] **Step 2: Register the route in `frontend/src/App.svelte`**

Add the import alongside the other job-route imports:

```svelte
import DuplicateJobPage from './routes/jobs/DuplicateJobPage.svelte';
```

Add the route entry next to the existing `'/jobs/:id'` entries:

```svelte
'/jobs/:id/duplicate': DuplicateJobPage,
```

- [ ] **Step 3: Add the "Duplicate…" link in `frontend/src/components/jobs/JobHeader.svelte`**

In the header action area (near the existing `edit`/status links, ~line 119), add a navigation link. Per UI conventions, this is a navigation, so it's an `<a>`, not a button:

```svelte
<a href="#/jobs/{job.job_id}/duplicate" class="edit-link">duplicate…</a>
```

- [ ] **Step 4: Build and manually verify**

Run: `cd frontend && npm run build`
Expected: build completes with no errors.

Then with the dev servers running (`python manage.py runserver` + `cd frontend && npm run dev`), as a user with **Manage Jobs** permission:
1. Open a Job with tasks/materials/deliverables; click **duplicate…**.
2. Confirm the customer dropdown is pre-selected to the source's contact; change it.
3. Choose **Immediately approved**, click **Duplicate** → lands on a new Job that is **Approved**, with the tasks/materials/deliverables copied and a fresh job number.
4. Repeat with **Requires a new estimate** → lands on a new **Draft** Job that has a worksheet (visible via the worksheet/estimate affordance), no earmarks.
5. As a user **without** Manage Jobs, confirm the duplicate POST is rejected (error overlay).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/jobs/DuplicateJobPage.svelte frontend/src/App.svelte frontend/src/components/jobs/JobHeader.svelte
git commit -m "feat(spa): job duplication page, route, and Duplicate link"
```

---

## Task 5: Documentation

**Files:**
- Modify: `docs/designs/jobs-tasks-and-worksheets.md`
- Modify: `docs/designs/users-and-permissions.md`

- [ ] **Step 1: Add a "Job duplication" subsection to `jobs-tasks-and-worksheets.md`**

Add a subsection (near the Job lifecycle / §12 deliverables material) covering:
- The two outcomes (`approved` execution clone vs `estimate` draft worksheet).
- Work is always sourced from the source Job's **execution** Tasks/Materials.
- Reset rules (tasks: pending, no assignee/bleps/actual_qty; materials: pending/no PO/no source links).
- Outcome A creates **earmarks** and walks `draft→submitted→approved` through `JobService` (per the `estimates/signals.py` precedent), with a `HistoryEntry` per hop; deliverables remain editable because there is no estimate.
- Outcome B maps work into a fresh draft `EstWorksheet` (v1, no parent, no estimate); `PlanTask.est_qty` falls back to `actual_qty` then `0.00`; subtask hierarchy is flattened.
- Not copied: estimates, invoices, POs, bills, shipments, change orders, history, bleps, `customer_po_number`, `due_date`.
- Endpoint: `POST /api/jobs/{id}/duplicate/` `{contact_id, path}` → `{job_id}`.

- [ ] **Step 2: Add the endpoint row to `users-and-permissions.md` §3**

Under the `CanManageJobs` mapping, add:

```
| `POST /api/jobs/{id}/duplicate/` | `CanManageJobs` | Duplicate a Job into a new one |
```

- [ ] **Step 3: Commit**

```bash
git add docs/designs/jobs-tasks-and-worksheets.md docs/designs/users-and-permissions.md
git commit -m "docs: document job duplication feature + endpoint"
```

---

## Final verification

- [ ] Run the full duplication suite: `python manage.py test tests.test_job_duplication -v 2` → all green (19 tests).
- [ ] Run a broader sweep for regressions in touched apps: `python manage.py test tests` (single runner only — never parallel subagents).
- [ ] `cd frontend && npm run build` succeeds.
- [ ] Manual click-through (Task 4 Step 4) passes for both outcomes and the permission check.

---

## Notes for the implementer

- **Never write to the dev DB.** Tests use a separate test DB (`python manage.py test`). Do not run `migrate`, `shell`, `loaddata`, or any ORM/SQL writes against dev. No migration is needed for this feature — it adds no fields.
- **DB-table names are custom** (`tasks`, `materials`, `plan_tasks`, `plan_materials`, `worksheets`); use the ORM, not raw SQL.
- The whole `duplicate_job` runs in one `transaction.atomic()` — a failure mid-copy leaves no partial job.
- Do not call `.delete()` on line items or use `QuerySet.update()` for normalized/side-effecting fields (not used here, but house rules).
