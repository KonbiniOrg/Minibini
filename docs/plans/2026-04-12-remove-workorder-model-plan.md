# Remove WorkOrder Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the `WorkOrder` model. `Task` belongs directly to `Job`. Rename `WorkOrderTemplate` → `WorkTemplate`. Add `Job.STATUS_WORK_COMPLETE`. Preserve the task-list UI as `#/jobs/[id]/tasklist`.

**Architecture:** Big-bang refactor on a single branch. Phase A reshapes models and ships one migration. Phases B–F update services, API, search, frontend, and Django templates. Phase H updates `CLAUDE.md`.

**Test discipline (TDD per phase):** Every phase ends with test updates covering that phase's code paths before moving to the next phase. For phases C–F, write/rewrite tests BEFORE the implementation within the phase; run them failing, then implement. Phase A and B were executed before this discipline was established, so they get retroactive test tasks (A7, B6). The previous "Phase G — rewrite all tests at the end" structure is retired; Phase G is now housekeeping only (rename mechanical test files, drop obsolete ones, update fixtures, full-suite green).

**Tech Stack:** Django 5.2+, DRF, MySQL, Svelte 5 SPA, Vite. Tests via Django `TestCase`.

**Spec:** `docs/designs/2026-04-12-remove-workorder-model-design.md`

---

## Before starting

- [ ] **Create feature branch**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git checkout -b refactor/remove-workorder
```

- [ ] **Confirm dev server status**

If the Django dev server or Vite dev server is running, the agent should stop them before any migration step (so `makemigrations` is clean). Restart after the migration task.

---

## Phase A — Models & Migration

This phase changes the data model. At the end, `Task.job` replaces `Task.work_order`, `Job` has `work_complete` status, and `WorkOrder` is gone. One migration file produces all of this.

### Task A1: Rename model `WorkOrderTemplate` → `WorkTemplate`

**Files:**
- Modify: `apps/estimates/models.py`
- Modify: `apps/estimates/services.py`
- Modify: every file importing `WorkOrderTemplate` (grep first)

**Note:** We do this BEFORE touching WorkOrder so the rename is its own concern.

- [ ] **Step 1: Find all references**

Run: `grep -rn "WorkOrderTemplate" apps/ tests/ fixtures/ templates/ frontend/src/ 2>/dev/null`
Record the full list. Expect matches in models, services, API serializers/views, tests, fixtures, Svelte components.

- [ ] **Step 2: Rename the model class and `db_table`**

In `apps/estimates/models.py`, locate `class WorkOrderTemplate(models.Model)`:
- Rename class to `WorkTemplate`.
- Change `db_table = 'work_order_templates'` (or whatever the current value is) to `db_table = 'work_templates'`.
- If there is a `template_id` or similar PK, leave it.

Leave any field-name references to `work_order_template` on related models (e.g., `TemplateTaskAssociation.work_order_template`) UNTOUCHED in this task — those are handled in A2.

- [ ] **Step 3: Update all imports**

Replace every `from apps.estimates.models import ... WorkOrderTemplate ...` with `WorkTemplate`, and every `WorkOrderTemplate` identifier across the codebase. Include test files, serializers, views, frontend is done in later phase.

Use:
```bash
grep -rln "WorkOrderTemplate" apps/ tests/ | xargs sed -i '' 's/WorkOrderTemplate/WorkTemplate/g'
```
(On macOS use `sed -i ''`; Linux `sed -i`.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename WorkOrderTemplate to WorkTemplate"
```

---

### Task A2: Rename FK field `work_order_template` → `template` (or `work_template`)

**Files:**
- Modify: `apps/estimates/models.py` (TemplateTaskAssociation, TemplateBundle, etc.)
- Modify: service and serializer references

**Decision:** the existing `AbstractWorkContainer.template` FK name is `template`. On association/bundle models we rename `work_order_template` → `work_template` to keep the grep-able relation clear (the abstract `template` lives on the container; `work_template` lives on the associations/bundles).

- [ ] **Step 1: Find all references to `work_order_template`**

Run: `grep -rn "work_order_template" apps/ tests/ fixtures/`

- [ ] **Step 2: Update model FK names**

In `apps/estimates/models.py`, wherever `work_order_template = models.ForeignKey(WorkTemplate, ...)` appears, rename to `work_template = models.ForeignKey('estimates.WorkTemplate', ...)`. Update `related_name` if it mentions "work_order" (e.g., `related_name='work_order_associations'` → `related_name='work_template_associations'`).

- [ ] **Step 3: Update all Python references**

```bash
grep -rln "work_order_template" apps/ tests/ | xargs sed -i '' 's/work_order_template/work_template/g'
```

- [ ] **Step 4: Update fixture JSON references**

Fixtures reference model names (`estimates.workordertemplate`) and FK field names. Update the model references in JSON files under `fixtures/`:
```bash
grep -rln "workordertemplate\|work_order_template" fixtures/ | xargs sed -i '' -e 's/workordertemplate/worktemplate/g' -e 's/work_order_template/work_template/g'
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename work_order_template FK to work_template"
```

---

### Task A3: Reshape `AbstractWorkContainer`

**Files:**
- Modify: `apps/core/models.py:183-189`
- Modify: `apps/estimates/models.py` (EstWorksheet)
- Modify: `apps/jobs/models.py` (Job gains inheritance)

The abstract base currently declares `job` + `template`. We remove `job` from the abstract (so `Job` can extend without self-referencing) and move it to `EstWorksheet` directly.

- [ ] **Step 1: Reshape the abstract base**

In `apps/core/models.py`, replace the current `AbstractWorkContainer`:

```python
class AbstractWorkContainer(models.Model):
    template = models.ForeignKey(
        'estimates.WorkTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True

    def populate_from_template(self, template):
        """Populate this container's tasks from a WorkTemplate.

        Subclasses implement by reading template's TemplateTaskAssociations
        and TemplateBundles and creating the appropriate task type
        (PlanTask on EstWorksheet, Task on Job).
        """
        raise NotImplementedError
```

- [ ] **Step 2: Add `job` FK directly to `EstWorksheet`**

In `apps/estimates/models.py`, on `class EstWorksheet(AbstractWorkContainer)`, add:

```python
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE)
```

(Keep the abstract inheritance — it still provides `template`.)

- [ ] **Step 3: Make `Job` extend `AbstractWorkContainer`**

In `apps/jobs/models.py`, change the class line:

```python
from apps.core.models import AbstractWorkContainer

@history(exclude=['job_id'])
class Job(AbstractWorkContainer):
    ...
```

`Job` now inherits a nullable `template` FK.

- [ ] **Step 4: Commit**

Do not commit yet — A4 and A5 must land together with A3 in a single migration. Skip to A4.

---

### Task A4: Add `STATUS_WORK_COMPLETE` to `Job`

**Files:**
- Modify: `apps/jobs/models.py`

- [ ] **Step 1: Add the status constant and choice**

In `apps/jobs/models.py`, in `class Job(AbstractWorkContainer)`:

```python
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_WORK_COMPLETE = 'work_complete'   # NEW
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    JOB_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_WORK_COMPLETE, 'Work Complete'),   # NEW
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
```

- [ ] **Step 2: Update `VALID_TRANSITIONS`**

In `Job.clean()`, update `VALID_TRANSITIONS`:

```python
        VALID_TRANSITIONS = {
            Job.STATUS_DRAFT: [Job.STATUS_SUBMITTED, Job.STATUS_REJECTED],
            Job.STATUS_SUBMITTED: [Job.STATUS_APPROVED, Job.STATUS_REJECTED],
            Job.STATUS_APPROVED: [Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED],
            Job.STATUS_WORK_COMPLETE: [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED],
            Job.STATUS_REJECTED: [],
            Job.STATUS_COMPLETED: [],
            Job.STATUS_CANCELLED: [],
        }
```

- [ ] **Step 3: Update `save()` date-setting**

In `Job.save()`, the terminal-date logic currently sets `completed_date` on entry to `COMPLETED` / `CANCELLED`. Leave this as-is — `work_complete` is NOT a terminal state and should NOT set `completed_date`.

---

### Task A5: Replace `Task.work_order` with `Task.job`

**Files:**
- Modify: `apps/jobs/models.py` (Task class)
- Delete: `WorkOrder` class entirely (in the same file)

- [ ] **Step 1: Delete the `WorkOrder` class**

In `apps/jobs/models.py`, delete the entire `class WorkOrder(AbstractWorkContainer)` block (lines ~120–162). Also remove the `@history(exclude=['work_order_id'])` decorator line directly above it.

- [ ] **Step 2: Change `Task.work_order` to `Task.job`**

In `class Task(TaskBase)`, replace:

```python
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name='tasks')
```

with:

```python
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='tasks')
```

- [ ] **Step 3: Update `Task.save()` sort_order scoping**

The `save()` method uses `Task.objects.filter(work_order=self.work_order)` to find the max sort_order. Change:

```python
                max_order = Task.objects.filter(
                    job=self.job
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
```

- [ ] **Step 4: Remove `WorkOrder` from imports**

Scan `apps/jobs/models.py` for any remaining references to `WorkOrder`. There should be none.

---

### Task A6: Create the migration

**Files:**
- Create: `apps/jobs/migrations/00NN_remove_workorder.py` (NN = next sequential number)
- Create: `apps/core/migrations/00NN_alter_abstractworkcontainer.py` (if Django generates a separate one)
- Create: `apps/estimates/migrations/00NN_...` (for WorkTemplate rename + EstWorksheet.job)

- [ ] **Step 1: Generate migrations**

Run: `python manage.py makemigrations`

Expected output: Django creates one or more migration files covering:
- Rename `WorkOrderTemplate` → `WorkTemplate`
- Rename field `work_order_template` → `work_template` on associations/bundles
- Add `Job.template` FK
- Alter `Job.status` choices (add `work_complete`)
- Add `EstWorksheet.job` FK (since it moved off the abstract)
- Add `Task.job` FK (nullable initially; see Step 2)
- Remove `Task.work_order`
- Delete `WorkOrder` model

Django may ask for defaults or confirmation on non-nullable fields. For `Task.job`, respond by editing the generated migration manually (next step).

- [ ] **Step 2: Edit the migration to add a data backfill for `Task.job`**

Django will generate a `RemoveField('work_order')` and `AddField('job', ...)`. Before `RemoveField`, insert a `RunPython` operation that copies data, THEN alters the field to non-nullable. Edit the generated file to order operations as:

```python
# 1. Rename WorkOrderTemplate and the FK field (Django generates these)
# 2. Add Task.job as nullable FK:
migrations.AddField(
    model_name='task',
    name='job',
    field=models.ForeignKey(
        null=True, blank=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name='tasks',
        to='jobs.job',
    ),
),

# 3. Backfill (insert manually):
migrations.RunPython(backfill_task_job, reverse_code=migrations.RunPython.noop),

# 4. Make Task.job non-nullable:
migrations.AlterField(
    model_name='task',
    name='job',
    field=models.ForeignKey(
        on_delete=django.db.models.deletion.CASCADE,
        related_name='tasks',
        to='jobs.job',
    ),
),

# 5. Remove Task.work_order:
migrations.RemoveField(model_name='task', name='work_order'),

# 6. Delete WorkOrder model:
migrations.DeleteModel(name='WorkOrder'),
```

And define `backfill_task_job` at the top of the file:

```python
def backfill_task_job(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    WorkOrder = apps.get_model('jobs', 'WorkOrder')
    for task in Task.objects.all():
        if task.work_order_id is not None:
            wo = WorkOrder.objects.get(pk=task.work_order_id)
            task.job_id = wo.job_id
            task.save(update_fields=['job_id'])
```

The `AbstractWorkContainer` reshape (removing `job` from the abstract, adding `job` directly to `EstWorksheet`) will be handled by Django automatically as a `RemoveField`/`AddField` pair on `EstWorksheet` — however, since the column is the same, Django may collapse it. Review the generated migration; if Django plans to drop and re-add the column (losing worksheet→job links), add a second backfill. Most likely Django will just update state without altering the database.

- [ ] **Step 3: Review migration order across apps**

`makemigrations` may produce separate files under `apps/jobs/`, `apps/estimates/`, and `apps/core/`. Verify dependencies between them are correct (Django generates `dependencies = [...]` automatically). Do not run `migrate` — only the user runs that.

- [ ] **Step 4: Commit Phase A as a single atomic commit**

```bash
git add apps/jobs/models.py apps/core/models.py apps/estimates/models.py apps/jobs/migrations apps/estimates/migrations apps/core/migrations
git commit -m "refactor: remove WorkOrder model, Task belongs to Job directly

- Delete WorkOrder model
- Task.work_order → Task.job (backfilled in migration)
- Add Job.STATUS_WORK_COMPLETE status
- Job extends AbstractWorkContainer (gains template FK)
- EstWorksheet declares its own job FK (no longer inherited)
- Rename WorkOrderTemplate → WorkTemplate"
```

- [ ] **Step 5: Ask the user to run `migrate`**

Pause and tell the user:
> "Phase A models and migration are ready. Please run `python manage.py migrate` on your dev DB and confirm success before I continue with services."

---

### Task A7: Retroactive tests for Phase A (model layer)

Phase A executed before TDD discipline was established. Bring the model-layer tests up to date now, against the current (post-A) codebase.

**Files to touch (all under `tests/`):**
- `test_jobs_models.py` — covers Job, Task, (old: WorkOrder)
- `test_jobs_models_with_fixtures.py` — fixture-backed model tests
- `test_comprehensive_models.py` — cross-model assertions that may reference WorkOrder or `task.work_order`

**Scope of Phase A's model-layer changes:**
- `Task.work_order` → `Task.job`
- `WorkOrder` model deleted
- `Job` gains `STATUS_WORK_COMPLETE` and extends `AbstractWorkContainer`
- `WorkOrderTemplate` → `WorkTemplate`; `work_order_template` FK → `work_template`
- `EstWorksheet.job` declared directly
- Migration `jobs/0012` with backfill

- [ ] **Step 1: Run each candidate test file and record failures**

For each test file listed, run it individually and capture failures:
```bash
python manage.py test tests.test_jobs_models tests.test_jobs_models_with_fixtures tests.test_comprehensive_models -v 2 2>&1 | tail -80
```

- [ ] **Step 2: Rewrite each failing test to exercise the new model shape**

Apply these mechanical swaps everywhere they appear:
- `Task.objects.create(work_order=wo, ...)` → `Task.objects.create(job=job, ...)`
- `task.work_order` → `task.job`
- `WorkOrder.objects.create(...)` → delete (no direct WorkOrder; just create Job with tasks)
- `WorkOrderTemplate` → `WorkTemplate`
- `work_order_template=` → `work_template=`

Add NEW tests for:
- `Job.STATUS_WORK_COMPLETE` is a valid choice
- Transition `APPROVED → WORK_COMPLETE` is allowed; `WORK_COMPLETE → COMPLETED` is allowed; `WORK_COMPLETE → WORK_COMPLETE` is NOT (or is now a no-op via the short-circuit in `JobService.update_status` — test that the service short-circuit works)
- `Job` has the `template` FK (nullable)
- `EstWorksheet.job` is an FK to Job (non-nullable)
- `Task.job` is required (creating a Task without `job` raises)

Delete tests that asserted WorkOrder-specific behavior with no Job equivalent (e.g., "WorkOrder status machine incomplete→blocked→complete").

- [ ] **Step 3: Run the suite until green**

```bash
python manage.py test tests.test_jobs_models tests.test_jobs_models_with_fixtures tests.test_comprehensive_models -v 2
```

Until all three pass, iterate on the tests (not the implementation — Phase A is frozen; if a test reveals a real model defect, STOP and escalate).

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update model-layer tests for Task-on-Job refactor"
```

---

## Phase B — Services

Reshape `WorkOrderService`, `TaskService`, `TaskLifecycleService`, and inventory hooks to match the new model.

### Task B1: Merge `WorkOrderService` into `JobService`

**Files:**
- Modify: `apps/jobs/services.py`

- [ ] **Step 1: Replace `WorkOrderService.create_from_estimate` with `JobService.populate_from_estimate`**

In `apps/jobs/services.py`, in `class JobService`, add:

```python
    @staticmethod
    def populate_from_estimate(job, estimate):
        """Populate a Job's tasks from an Estimate's line items.
        Only OPEN and ACCEPTED estimates are allowed. Requires job to be in APPROVED status."""
        from apps.estimates.models import Estimate
        if estimate.status not in [Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED]:
            raise ValidationError(
                f"Only Open and Accepted estimates can populate jobs. "
                f"Estimate {estimate.estimate_number} is {estimate.status}."
            )
        for line_item in estimate.estimatelineitem_set.all():
            TaskService.create_from_line_item(line_item, job)

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
        return job
```

- [ ] **Step 2: Replace `create_from_template` with `populate_from_template` on `JobService`**

```python
    @staticmethod
    def populate_from_template(job, template):
        """Populate a Job from a WorkTemplate's task associations."""
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")

        job.template = template
        job.save()

        from apps.estimates.models import TemplateTaskAssociation
        associations = TemplateTaskAssociation.objects.filter(
            work_template=template,
            task_template__is_active=True,
        ).order_by('sort_order', 'task_template__template_name')

        for association in associations:
            association.task_template.generate_task(job, association.est_qty)

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
        return job
```

- [ ] **Step 3: Replace `copy_from_worksheet`**

```python
    @staticmethod
    def copy_from_worksheet(job_pk, worksheet_pk):
        """Copy a worksheet's PlanTasks (with their PlanMaterials) to a job."""
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import PlanTask
        from apps.inventory.models import Material

        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')

        for plan_task in PlanTask.objects.filter(
            est_worksheet=ws
        ).prefetch_related('plan_materials'):
            new_task = Task.objects.create(
                job=job,
                name=plan_task.name,
                description=plan_task.description,
                units=plan_task.units,
                rate=plan_task.rate,
                est_qty=plan_task.est_qty,
                accounting_category=plan_task.accounting_category,
                sort_order=plan_task.sort_order,
            )
            for pm in plan_task.plan_materials.all():
                Material.objects.create(
                    task=new_task,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
```

- [ ] **Step 4: Extend `JobService.update_status`**

Replace the existing `update_job` with an `update_status` method that handles the earmark release side effect:

```python
    @staticmethod
    def update_status(pk, new_status):
        """Update job status; triggers earmark release on entry to work_complete."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        old_status = job.status
        job.status = new_status
        job.full_clean()
        job.save()

        if new_status == Job.STATUS_WORK_COMPLETE and old_status != Job.STATUS_WORK_COMPLETE:
            from apps.inventory.services import InventoryService
            InventoryService.release_earmarks_for_job(job)

        return job
```

Keep the existing `update_job` (for generic field updates) alongside it — it does not duplicate `update_status`.

- [ ] **Step 5: Delete the entire `WorkOrderService` class**

Remove `class WorkOrderService:` and all its methods from `apps/jobs/services.py`.

- [ ] **Step 6: Run tests to verify the service layer compiles**

Run: `python manage.py test tests.test_jobs_services -v 2`
Expected: ImportErrors or `WorkOrderService is not defined` failures — that is the correct failure at this point because tests still reference `WorkOrderService`. We will fix tests in Phase G. Do not fix them yet.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/services.py
git commit -m "refactor: merge WorkOrderService into JobService"
```

---

### Task B2: Update `TaskService` to use `job` instead of `work_order`

**Files:**
- Modify: `apps/jobs/services.py` (TaskService class)

- [ ] **Step 1: Rename all method parameters and internals**

Every method in `TaskService` currently accepts `work_order` as a parameter. Rename to `job`. Examples:

```python
    @staticmethod
    def create_from_line_item(line_item, job):
        if line_item.task:
            return TaskService._copy_worksheet_tasks(line_item, job)
        elif line_item.price_list_item:
            return TaskService._create_task_from_catalog_item(line_item, job)
        else:
            return TaskService._create_generic_task(line_item, job)

    @staticmethod
    def _copy_worksheet_tasks(line_item, job):
        plan_task = line_item.task
        new_task = Task.objects.create(
            job=job,
            name=plan_task.name,
            ...
        )
        return [new_task]
```

Apply the same `work_order` → `job` swap to:
- `_create_task_from_catalog_item`
- `_create_generic_task`
- `create_from_template(template, job, assignee=None)`
- `create_direct(job, name, **kwargs)`

- [ ] **Step 2: Update `delete_task` to remove WO-unblock rollup**

Current `delete_task` checks `if was_blocked and wo.status == WorkOrder.STATUS_BLOCKED` and calls `WorkOrderService.update_status(...)`. Remove that entire post-delete block. `delete_task` no longer does any rollup after the spec decision to drop Job-level block status.

New `delete_task` body (reduced):

```python
    @staticmethod
    def delete_task(task_pk):
        try:
            task = Task.objects.get(pk=task_pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_pk} not found')

        non_deletable = (Task.STATUS_IN_PROGRESS, Task.STATUS_COMPLETE)
        if task.status in non_deletable:
            raise ValidationError(
                f"Cannot delete a {task.status} task. Cancel it instead."
            )
        if Blep.objects.filter(task=task).exists():
            raise ValidationError(
                "Cannot delete a task that has time entries. Cancel it instead."
            )

        task.delete()
```

- [ ] **Step 3: Update `reorder_tasks`**

```python
    @staticmethod
    def reorder_tasks(task_id, direction):
        from apps.core.services import BundlingService

        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_id} not found')

        items_qs = Task.objects.filter(job=task.job)

        BundlingService.reorder_container_items(
            items_qs, 'task', task_id, direction,
        )
        task.refresh_from_db()
        return task
```

- [ ] **Step 4: Commit**

```bash
git add apps/jobs/services.py
git commit -m "refactor: TaskService uses Job instead of WorkOrder"
```

---

### Task B3: Update `TaskLifecycleService` rollup target

**Files:**
- Modify: `apps/jobs/services.py` (TaskLifecycleService class)

- [ ] **Step 1: Replace `_check_wo_auto_complete` with `_check_job_work_complete`**

```python
    @staticmethod
    def _check_job_work_complete(task):
        """Auto-advance Job to work_complete if all its tasks are terminal.
        Only fires when Job is currently in APPROVED status."""
        job = task.job
        if job.status != Job.STATUS_APPROVED:
            return
        terminal = {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED}
        all_terminal = not Task.objects.filter(
            job=job
        ).exclude(status__in=terminal).exists()
        if all_terminal:
            JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)
```

- [ ] **Step 2: Remove `_check_wo_blocked` and `_check_wo_unblocked`**

Delete both methods entirely.

- [ ] **Step 3: Update call sites**

In `complete_task` and `cancel_task`, replace `TaskLifecycleService._check_wo_auto_complete(task)` with `TaskLifecycleService._check_job_work_complete(task)`.

In `block_task`, remove the call to `_check_wo_blocked(task)`.

In `unblock_task` and `cancel_task`, remove the call to `_check_wo_unblocked(task)` (the `was_blocked` check can also be dropped since it only fed that call).

- [ ] **Step 4: Update the `start_work` flow**

`start_work` references `task.work_order` nowhere directly — it only uses `task.assignee`, `task.materials`, `task.status`. The consumption step `InventoryService.consume_material(material)` stays. No change needed beyond verifying.

- [ ] **Step 5: Run the jobs services tests to confirm expected fails**

Run: `python manage.py test tests.test_task_lifecycle -v 2`
Expected: tests that still expect WO-level blocked transitions fail. That is correct — Phase G rewrites them.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py
git commit -m "refactor: TaskLifecycleService rolls up to Job.work_complete, drops block rollup"
```

---

### Task B4: Rename and retarget inventory earmark helper

**Files:**
- Modify: `apps/inventory/services.py`

- [ ] **Step 1: Rename `create_earmarks_for_work_order` → `create_earmarks_for_job`**

In `apps/inventory/services.py`, find `create_earmarks_for_work_order(work_order)` (around line 251). Rename to `create_earmarks_for_job(job)` and update the body:

```python
    @staticmethod
    def create_earmarks_for_job(job):
        """Create earmarks from a Job's task materials.

        Aggregates PlanMaterial/Material quantities by price_list_item
        across all tasks on the job, then upserts Earmark records.
        """
        from apps.inventory.models import Material
        materials = Material.objects.filter(
            task__job=job,
            price_list_item__isnull=False,
        )
        # aggregate logic — preserve current logic, only swap the filter/source
        ...
        earmark_data = [...]
        InventoryService._upsert_earmarks(job, earmark_data)
```

The existing function already has most of the logic — preserve it and swap `work_order.job` → `job` throughout. There is also a `create_earmarks_for_job(job, earmark_data)` method at line 281 that takes pre-built data; rename IT to `_upsert_earmarks(job, earmark_data)` to avoid the name collision.

- [ ] **Step 2: Update all call sites of `create_earmarks_for_work_order`**

```bash
grep -rln "create_earmarks_for_work_order" apps/ | xargs sed -i '' 's/create_earmarks_for_work_order/create_earmarks_for_job/g'
```

- [ ] **Step 3: Verify `release_earmarks_for_job` unchanged**

The existing function already takes a `job` parameter. No change required.

- [ ] **Step 4: Commit**

```bash
git add apps/inventory/services.py apps/jobs/services.py
git commit -m "refactor: earmark helpers job-scoped instead of work-order-scoped"
```

---

### Task B5: Update `BoardService` task queries

**Files:**
- Modify: `apps/jobs/services.py` (BoardService, around line 800)

- [ ] **Step 1: Rewrite task queries to use `task.job`**

Current:
```python
tasks = Task.objects.filter(
    work_order__job_id__in=approved_job_ids,
).exclude(...).select_related('work_order__job', 'assignee')
```

New:
```python
tasks = Task.objects.filter(
    job_id__in=approved_job_ids,
).exclude(...).select_related('job', 'assignee')
```

Apply the same substitution at every occurrence in `BoardService` (there are at least 3: approved tasks query, stats-by-job query, another at line ~907).

Also update the serializer access pattern: `task.work_order.job` → `task.job` anywhere in `_serialize_task` and helpers.

- [ ] **Step 2: Run board tests**

Run: `python manage.py test tests.test_board_service tests.test_board_api -v 2`
Expected: tests that still use `work_order` fail. Fine for now.

- [ ] **Step 3: Commit**

```bash
git add apps/jobs/services.py
git commit -m "refactor: BoardService queries tasks via job FK"
```

---

### Task B6: Retroactive tests for Phase B (service layer)

Phase B executed before TDD discipline. Update service-layer tests now.

**Files to touch:**
- `tests/test_jobs_services.py` — WorkOrderService / JobService / TaskService coverage
- `tests/test_task_lifecycle.py` — rollup logic, block/unblock, complete/cancel
- `tests/test_earmark_release.py` — earmark release on status change
- `tests/test_earmark_flow.py`, `tests/test_auto_earmark.py` — earmark creation paths
- `tests/test_board_service.py` — BoardService queries, sub-statuses, unpaid column
- `tests/test_estimates_services.py` — any WorkOrderService references
- `tests/test_bundling_services.py`, `tests/test_blep_service.py`, `tests/test_expense_service.py` — any task-reorder / task-blep / expense paths

**Scope of Phase B's service-layer changes:**
- `WorkOrderService` deleted; methods moved to `JobService.populate_from_estimate / populate_from_template / copy_from_worksheet / update_status`
- `TaskService` params: `work_order` → `job`; `delete_task` simplified
- `TaskLifecycleService._check_wo_*` removed; `_check_job_work_complete` added (only fires when `job.status == APPROVED`)
- `InventoryService.create_earmarks_for_work_order` → `create_earmarks_for_job`; internal `_upsert_earmarks` helper
- `BoardService` — unpaid column queries `status=WORK_COMPLETE` exclusively; new `_work_complete_sub_status`; `'needs-work-order'` → `'needs-tasks'`
- `JobService.update_status` short-circuits no-op transitions and releases earmarks on entry to `WORK_COMPLETE`

- [ ] **Step 1: Run candidate test files**

```bash
python manage.py test \
  tests.test_jobs_services \
  tests.test_task_lifecycle \
  tests.test_earmark_release \
  tests.test_earmark_flow \
  tests.test_auto_earmark \
  tests.test_board_service \
  tests.test_estimates_services \
  tests.test_bundling_services \
  tests.test_blep_service \
  tests.test_expense_service \
  -v 2 2>&1 | tail -120
```

Record failures.

- [ ] **Step 2: Rewrite tests to match new service API**

Apply mechanical swaps:
- `WorkOrderService.create_from_estimate(est)` → `JobService.populate_from_estimate(job, est)` (signature: takes job now)
- `WorkOrderService.create_from_template(tpl, job)` → `JobService.populate_from_template(job, tpl)` (arg order flip)
- `WorkOrderService.copy_from_worksheet(wo.pk, ws.pk)` → `JobService.copy_from_worksheet(job.pk, ws.pk, template=ws.template)` (3-arg version now)
- `WorkOrderService.update_status(wo.pk, 'complete')` → `JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)`
- `InventoryService.create_earmarks_for_work_order(wo)` → `InventoryService.create_earmarks_for_job(job)`
- `task.work_order` → `task.job`
- Assertions about "WO blocked because task blocked" → DELETE those tests (block rollup is gone per spec)

Add NEW tests:
- Completing all tasks on an `approved` Job auto-advances Job to `work_complete` (only when Job is approved; NOT when Job is in other states)
- Blocking a task does NOT change Job status (regression guard against accidentally re-adding bubble-up)
- Transitioning Job `approved → work_complete` releases remaining earmarks for that job
- Transitioning Job `work_complete → work_complete` (no-op via short-circuit) does NOT release earmarks a second time
- `BoardService.get_unpaid_data` returns only `status=work_complete` jobs and assigns each a sub-status from `invoice-sent` / `invoice-prepped` / `needs-invoice` based on invoice state
- `BoardService._approved_sub_status` returns `'needs-tasks'` when a Job has no tasks (replacing the old `'needs-work-order'`)

- [ ] **Step 3: Iterate to green**

Run until passing. If a test exposes a real service defect, STOP and escalate.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: update service-layer tests for WorkOrder removal"
```

---

## Phase C — API

Collapse `/api/work-orders/` routes into `/api/jobs/` sub-routes.

**Test-first discipline:** Before writing viewset/serializer code in each task below, write or rewrite the corresponding tests to describe the desired endpoint contract. Run them failing. Then implement. Test files in scope for Phase C:
- `tests/test_api_jobs.py` — existing job endpoint tests; extend with new actions (`work-complete`, `populate-from-*`, `copy-from-worksheet`, `reorder-tasks`, task sub-resource).
- `tests/test_api_work_orders.py` — DELETE after migrating any unique coverage to `test_api_jobs.py`.
- `tests/test_api_wo_creation.py` → rename `tests/test_api_job_population.py` and rewrite.
- `tests/test_api_workorder_ui.py` → rename `tests/test_api_job_tasklist.py` and rewrite to assert `GET /api/jobs/{id}/` response shape (nested tasks, template).
- `tests/test_workorder_from_estimate.py` → rename `tests/test_job_from_estimate.py`.
- `tests/test_work_order_template_edit_delete.py` → rename `tests/test_work_template_edit_delete.py`; swap `/api/work-order-templates/` → `/api/work-templates/`.
- `tests/test_atom_api_permissions.py` — verify permission classes on new Job-scoped actions.
- `tests/test_api_bleps.py`, `tests/test_task_lifecycle_api.py`, `tests/test_api_expenses.py` — update any `/api/work-orders/` calls to job-scoped equivalents.

Within each Task C1/C2/C3, the step list should be: (1) write/rewrite the failing tests for this sub-scope, (2) run them to confirm failure reason, (3) implement the endpoint/serializer/mixin changes, (4) run tests to green, (5) commit (tests + impl together per sub-scope).

### Task C1: Delete `apps/api/work_orders/` directory

**Files:**
- Delete: `apps/api/work_orders/__init__.py`
- Delete: `apps/api/work_orders/views.py`
- Delete: `apps/api/work_orders/serializers.py`
- Modify: `apps/api/urls.py` (remove WorkOrderViewSet router registration)

- [ ] **Step 1: Remove the router registration**

In `apps/api/urls.py`, locate the line registering `WorkOrderViewSet` (search: `work-orders`). Remove that line and its import.

- [ ] **Step 2: Delete the directory**

```bash
rm -rf apps/api/work_orders/
```

- [ ] **Step 3: Verify no remaining imports**

```bash
grep -rn "from apps.api.work_orders" apps/ tests/
```
Expected: no matches. If any, remove them.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove /api/work-orders/ viewset and routes"
```

---

### Task C2: Add Job sub-routes to `JobViewSet`

**Files:**
- Modify: `apps/api/jobs/views.py`
- Modify: `apps/api/jobs/serializers.py`
- Modify: `apps/api/mixins.py`

- [ ] **Step 1: Rename `WorkOrderTaskMixin` → `JobTaskMixin`**

In `apps/api/mixins.py`, find `class WorkOrderTaskMixin`. Rename to `JobTaskMixin`. Internally, replace every `work_order` lookup with `job` lookup. The mixin's `@action` decorators should target `job` PK lookups. Example:

```python
class JobTaskMixin:
    @action(detail=True, methods=['post'], url_path='tasks')
    def create_task(self, request, pk=None):
        job = self.get_object()
        serializer = TaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = TaskService.create_direct(job=job, **serializer.validated_data)
        return Response(TaskSerializer(task).data, status=201)

    @action(detail=True, methods=['patch', 'delete'],
            url_path=r'tasks/(?P<task_pk>[^/.]+)')
    def modify_task(self, request, pk=None, task_pk=None):
        job = self.get_object()
        try:
            task = Task.objects.get(pk=task_pk, job=job)
        except Task.DoesNotExist:
            return Response({'detail': 'Task not found'}, status=404)
        if request.method == 'DELETE':
            TaskService.delete_task(task.pk)
            return Response({'message': 'Task deleted.'}, status=200)
        serializer = TaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = TaskService.update_task(task.pk, **serializer.validated_data)
        return Response(TaskSerializer(updated).data)
```

- [ ] **Step 2: Add the new actions to `JobViewSet`**

In `apps/api/jobs/views.py`, import `JobTaskMixin` and add it to `JobViewSet`'s bases. Add these actions (or via mixins):

```python
    @action(detail=True, methods=['post'], url_path='work-complete')
    def work_complete(self, request, pk=None):
        job = JobService.update_status(pk, Job.STATUS_WORK_COMPLETE)
        return Response(JobSerializer(job).data)

    @action(detail=True, methods=['post'], url_path='populate-from-template')
    def populate_from_template(self, request, pk=None):
        job = self.get_object()
        template_id = request.data.get('template_id')
        template = WorkTemplate.objects.get(pk=template_id)
        JobService.populate_from_template(job, template)
        return Response(JobSerializer(job).data)

    @action(detail=True, methods=['post'], url_path='populate-from-estimate')
    def populate_from_estimate(self, request, pk=None):
        job = self.get_object()
        estimate_id = request.data.get('estimate_id')
        estimate = Estimate.objects.get(pk=estimate_id)
        JobService.populate_from_estimate(job, estimate)
        return Response(JobSerializer(job).data)

    @action(detail=True, methods=['post'], url_path='copy-from-worksheet')
    def copy_from_worksheet(self, request, pk=None):
        worksheet_id = request.data.get('worksheet_id')
        JobService.copy_from_worksheet(pk, worksheet_id)
        job = Job.objects.get(pk=pk)
        return Response(JobSerializer(job).data)

    @action(detail=True, methods=['post'], url_path='reorder-tasks')
    def reorder_tasks(self, request, pk=None):
        task_id = request.data.get('task_id')
        direction = request.data.get('direction')
        TaskService.reorder_tasks(task_id, direction)
        job = Job.objects.get(pk=pk)
        return Response(JobSerializer(job).data)
```

Permission class: all task-modification actions use `CanManageJobs` (see `apps/api/permissions.py`). `work_complete` and populate actions use `CanManageJobs` as well.

- [ ] **Step 3: Update `JobSerializer` to include nested tasks and template**

In `apps/api/jobs/serializers.py`:

```python
from apps.api.tasks.serializers import TaskSerializer
from apps.api.templates_config.serializers import WorkTemplateSerializer  # rename in Phase C3

class JobSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(many=True, read_only=True)
    template = WorkTemplateSerializer(read_only=True)
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=WorkTemplate.objects.all(),
        source='template',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Job
        fields = [..., 'tasks', 'template', 'template_id']
```

The `TaskSerializer` should already exist in `apps/api/tasks/serializers.py` — update any internal `work_order` references there to `job`.

- [ ] **Step 4: Update `TaskSerializer` (likely in `apps/api/tasks/serializers.py`)**

Swap any `work_order` field references for `job`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jobs/ apps/api/mixins.py apps/api/tasks/
git commit -m "feat: Job-scoped task endpoints replacing /api/work-orders/"
```

---

### Task C3: Rename `/api/work-order-templates/` → `/api/work-templates/`

**Files:**
- Modify: `apps/api/templates_config/views.py`
- Modify: `apps/api/templates_config/serializers.py`
- Modify: `apps/api/urls.py`

- [ ] **Step 1: Rename viewset**

```bash
grep -rln "WorkOrderTemplateViewSet\|WorkOrderTemplateSerializer\|work-order-templates" apps/ | xargs sed -i '' \
  -e 's/WorkOrderTemplateViewSet/WorkTemplateViewSet/g' \
  -e 's/WorkOrderTemplateSerializer/WorkTemplateSerializer/g' \
  -e 's|work-order-templates|work-templates|g'
```

- [ ] **Step 2: Check URL name references**

Search templates and frontend for `{% url 'api:work-order-template-...' %}` or `apiClient.workOrderTemplates`. Update per Phase E for frontend; for Django templates, swap now if the URL name changed.

- [ ] **Step 3: Commit**

```bash
git add apps/api/templates_config/ apps/api/urls.py
git commit -m "refactor: rename /api/work-order-templates/ to /api/work-templates/"
```

---

## Phase D — Search

**Test-first:** Write/rewrite `tests/test_search_function.py` to describe the new grouped shape under Job BEFORE editing `apps/search/services.py`. Assertions should cover: a query matching a job number surfaces the Job with empty/populated `tasks`; a query matching a task name surfaces the parent Job with that task in its `tasks` list; `'work_orders'` category is absent from results; `'jobs'` category uses the grouped shape.

### Task D1: Rename search method and retarget at Job

**Files:**
- Modify: `apps/search/services.py`

- [ ] **Step 1: Remove `CATEGORY_WORK_ORDERS`**

In `apps/search/services.py`, delete the constant declaration and every mapping entry:
- Line 23: `CATEGORY_WORK_ORDERS = 7` — delete
- Line 36 (`CATEGORY_ID_TO_KEY`): delete the `CATEGORY_WORK_ORDERS: 'work_orders'` entry
- Line 53 (`CATEGORY_ID_TO_DISPLAY`): delete the `'Work Orders'` entry
- Line 62: remove `'work_orders'` from the default categories list

Renumber the remaining category IDs if any later code assumes contiguous numbering; otherwise leave the gap.

- [ ] **Step 2: Rename and rewrite `search_work_orders_with_tasks`**

Replace the method entirely:

```python
    @staticmethod
    def search_jobs_with_tasks(query):
        """Search for jobs and their matching tasks, returning grouped results."""
        jobs = Job.objects.filter(
            Q(job_number__icontains=query) |
            Q(description__icontains=query)
        ).prefetch_related('tasks')

        tasks = Task.objects.annotate(
            rate_text=Cast('rate', CharField())
        ).filter(
            Q(name__icontains=query) |
            Q(units__icontains=query) |
            Q(rate_text__icontains=query) |
            Q(job__job_number__icontains=query)
        ).select_related('assignee', 'job')

        job_dict = {}
        for job in jobs:
            job_dict[job.pk] = {'parent': job, 'tasks': []}

        for task in tasks:
            if task.job_id not in job_dict:
                job_dict[task.job_id] = {'parent': task.job, 'tasks': []}
            job_dict[task.job_id]['tasks'].append(task)

        return list(job_dict.values())
```

- [ ] **Step 3: Wire the new method into the main search orchestrator**

Around line 469, the old code called:
```python
wo_groups = cls.search_work_orders_with_tasks(query)
...
categories['work_orders'] = [group['parent'] for group in wo_groups]
```

Replace with:
```python
job_groups = cls.search_jobs_with_tasks(query)
...
categories['jobs'] = [group['parent'] for group in job_groups]
```

Remove any separate flat-Jobs query that this replaces. Ensure the grouped tasks remain accessible to the caller — if the search API returns tasks separately or inline, update the response shape accordingly.

- [ ] **Step 4: Remove `'WorkOrder'` from result_ids branch**

Around line 797:
```python
if 'WorkOrder' in result_ids and result_ids['WorkOrder']:
    ...
```

Delete the entire block. Also remove the `'work_orders': 'WorkOrder'` mapping near line 649.

Remove `WorkOrder` from the module-level imports at line 5.

- [ ] **Step 5: Update flat-list handling**

Lines 561, 615, 675 have branches that special-case `'work_orders'` and `'est_worksheets'` as flat lists. Update `'jobs'` to use the grouped shape (because it now carries tasks inline) and drop `'work_orders'` from the flat branches.

- [ ] **Step 6: Commit**

```bash
git add apps/search/services.py
git commit -m "refactor: search groups tasks under parent Job, drop WorkOrder category"
```

---

## Phase E — Frontend

**Test-first:** Frontend changes are harder to test automatically; the primary test strategy is the API-level tests already written in Phase C (they assert the `GET /api/jobs/{id}/` shape the frontend consumes). For the frontend itself, smoke-test each route manually after changes (covered in Phase I). Do NOT skip Phase I's smoke test — it IS the test for Phase E.

### Task E1: Move WorkOrderDetailPage to JobTaskListPage

**Files:**
- Create: `frontend/src/routes/jobs/JobTaskListPage.svelte`
- Delete: `frontend/src/routes/workorders/WorkOrderDetailPage.svelte`
- Modify: `frontend/src/App.svelte` (router)

- [ ] **Step 1: Copy the file to its new home**

```bash
mkdir -p frontend/src/routes/jobs
cp frontend/src/routes/workorders/WorkOrderDetailPage.svelte \
   frontend/src/routes/jobs/JobTaskListPage.svelte
```

- [ ] **Step 2: Update the new file's data source**

Open `frontend/src/routes/jobs/JobTaskListPage.svelte` and:
1. Replace the `onMount` fetch: `GET /api/work-orders/{id}/` → `GET /api/jobs/{id}/`.
2. The response shape changes: tasks are now nested under `job.tasks` directly (no intermediate `work_order.tasks`). Update the store/reactive state accordingly.
3. Replace any `workOrderId` variable with `jobId`.
4. Replace action calls:
   - `POST /api/work-orders/{id}/tasks` → `POST /api/jobs/{id}/tasks`
   - `PATCH /api/work-orders/{id}/tasks/{tid}` → `PATCH /api/jobs/{id}/tasks/{tid}`
   - `POST /api/work-orders/{id}/complete` → `POST /api/jobs/{id}/work-complete`
   - `POST /api/work-orders/{id}/reorder` → `POST /api/jobs/{id}/reorder-tasks`
   - `POST /api/work-orders/{id}/add-from-template` → `POST /api/jobs/{id}/add-from-template`
   - Any "block" / "reopen" buttons are removed (no Job-level block in this refactor).

- [ ] **Step 3: Register the new route in `App.svelte`**

Find the router table (`svelte-spa-router` routes object) and:
- Remove `'/workorders/:id': WorkOrderDetailPage`
- Add `'/jobs/:id/tasklist': JobTaskListPage`
- Remove the `WorkOrderDetailPage` import.

- [ ] **Step 4: Delete the old file and directory**

```bash
rm -rf frontend/src/routes/workorders/
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): preserve tasklist view at #/jobs/[id]/tasklist"
```

---

### Task E2: Update components that reference WorkOrder

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte`
- Modify: `frontend/src/components/TaskModal.svelte`
- Modify: `frontend/src/components/invoices/WizardSourcePool.svelte`
- Modify: `frontend/src/components/expenses/ExpenseForm.svelte`
- Modify: `frontend/src/components/expenses/MaterialPicker.svelte`

- [ ] **Step 1: `JobDetail.svelte` — remove WO list, link to tasklist**

Delete any "Work Orders" section that iterated `job.work_orders`. Replace with:
```svelte
<p><a href="#/jobs/{job.job_id}/tasklist">View task list →</a></p>
```

- [ ] **Step 2: `JobDetailPage.svelte` — same treatment**

Remove any WO-fetching `onMount` logic. Rely on `job.tasks` from the Job endpoint for summary counts (if displayed). Add the same tasklist link.

- [ ] **Step 3: `TaskModal.svelte` — context swap**

Every `work_order_id` prop becomes `job_id`. Internal API calls for task CRUD point at the job-scoped routes.

- [ ] **Step 4: `WizardSourcePool.svelte`**

This component pulls completed WO tasks as invoice line-item sources. Replace the fetch: `GET /api/work-orders/?status=complete&job={id}` (or similar) with `GET /api/jobs/{id}/` and filter `job.tasks` for terminal statuses client-side.

- [ ] **Step 5: `ExpenseForm.svelte` and `MaterialPicker.svelte`**

Search these files for `work_order` / `workOrder`:
```bash
grep -n "work_order\|workOrder\|WorkOrder" frontend/src/components/expenses/*.svelte
```
Replace with `job` / `Job` equivalents.

- [ ] **Step 6: `frontend/src/lib/api.js`**

Remove the `workOrders` namespace entirely. Add to the `jobs` namespace:
```javascript
jobs: {
  // existing methods preserved
  workComplete: (id) => post(`/api/jobs/${id}/work-complete/`),
  populateFromTemplate: (id, templateId) =>
    post(`/api/jobs/${id}/populate-from-template/`, { template_id: templateId }),
  populateFromEstimate: (id, estimateId) =>
    post(`/api/jobs/${id}/populate-from-estimate/`, { estimate_id: estimateId }),
  copyFromWorksheet: (id, worksheetId) =>
    post(`/api/jobs/${id}/copy-from-worksheet/`, { worksheet_id: worksheetId }),
  reorderTasks: (id, taskId, direction) =>
    post(`/api/jobs/${id}/reorder-tasks/`, { task_id: taskId, direction }),
  createTask: (id, data) => post(`/api/jobs/${id}/tasks/`, data),
  updateTask: (id, taskId, data) =>
    patch(`/api/jobs/${id}/tasks/${taskId}/`, data),
  deleteTask: (id, taskId) =>
    del(`/api/jobs/${id}/tasks/${taskId}/`),
  addFromTemplate: (id, templateId) =>
    post(`/api/jobs/${id}/add-from-template/`, { template_id: templateId }),
},
```

And rename `workOrderTemplates` → `workTemplates` throughout.

- [ ] **Step 7: Run the frontend dev build**

```bash
cd frontend && npm run build
```
Expected: clean build. If errors, fix the specific file referenced.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "refactor(frontend): components and api client reference Job, not WorkOrder"
```

---

## Phase F — Django HTML Templates

### Task F1: Delete unused work order HTML templates

**Files:**
- Delete: `templates/jobs/work_order_list.html`
- Delete: `templates/jobs/work_order_detail.html`

- [ ] **Step 1: Confirm no Django view references them**

```bash
grep -rn "work_order_list\|work_order_detail" apps/ templates/
```
If any view still references them, remove the view (likely dead).

- [ ] **Step 2: Delete**

```bash
rm templates/jobs/work_order_list.html
rm templates/jobs/work_order_detail.html
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove unused work order HTML templates"
```

---

### Task F2: Rename work order template HTML files

**Files:**
- Rename: `templates/jobs/work_order_template_*.html` → `templates/jobs/work_template_*.html`

- [ ] **Step 1: Rename files**

```bash
cd templates/jobs
for f in work_order_template_*.html; do
  git mv "$f" "${f/work_order_template/work_template}"
done
cd -
```

- [ ] **Step 2: Update template internals**

Grep inside the renamed files for `work_order_template` / `WorkOrderTemplate` / `{% url 'work-order-template' %}`-style references and swap to `work_template`.

- [ ] **Step 3: Update any Django view rendering these templates**

```bash
grep -rn "work_order_template" apps/
```
Update any `render(request, 'jobs/work_order_template_...')` calls.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename work order template HTML files to work template"
```

---

## Phase G — Test housekeeping & fixtures

By this point, tests have been updated per-phase (A7, B6, and tests-first within C/D). Phase G is now only: (1) the residual mechanical file renames that didn't fit cleanly into a prior phase, (2) fixture updates, (3) full-suite green confirmation. The previous "rewrite everything at the end" version of this phase is retired.

### Task G1: Residual test file renames (if any remain)

**Files:**
- Delete: `tests/test_api_work_orders.py`
- Rewrite: `tests/test_api_wo_creation.py` → `tests/test_api_job_population.py`
- Rewrite: `tests/test_api_workorder_ui.py` → `tests/test_api_job_tasklist.py`
- Rewrite: `tests/test_workorder_from_estimate.py` → `tests/test_job_from_estimate.py`
- Rename: `tests/test_work_order_template_edit_delete.py` → `tests/test_work_template_edit_delete.py`

- [ ] **Step 1: Delete `test_api_work_orders.py`**

Its coverage moves into `test_api_jobs.py` (job-scoped task endpoints and `work-complete` action). Before deleting, skim it for any unique test cases not obviously covered elsewhere; migrate those to `test_api_jobs.py` as new test methods first.

```bash
git rm tests/test_api_work_orders.py
```

- [ ] **Step 2: Rewrite `test_api_wo_creation.py` → `test_api_job_population.py`**

```bash
git mv tests/test_api_wo_creation.py tests/test_api_job_population.py
```
Open the file and rewrite every test:
- API endpoints: `/api/work-orders/{id}/create-from-template` → `/api/jobs/{id}/populate-from-template`, etc.
- Model usage: `WorkOrder.objects.create(...)` → none (just assert `job.tasks.count()`).
- Assertions on WO status → assertions on `job.tasks` and `job.template`.

- [ ] **Step 3: Rewrite `test_api_workorder_ui.py` → `test_api_job_tasklist.py`**

```bash
git mv tests/test_api_workorder_ui.py tests/test_api_job_tasklist.py
```
Rewrite to exercise `GET /api/jobs/{id}/` and verify the nested-task response shape that `JobTaskListPage.svelte` consumes. Include:
- GET returns job with `tasks` array.
- Each task has name, status, sort_order, assignee.
- Ordering respects `sort_order`.

- [ ] **Step 4: Rewrite `test_workorder_from_estimate.py` → `test_job_from_estimate.py`**

```bash
git mv tests/test_workorder_from_estimate.py tests/test_job_from_estimate.py
```
Replace all `WorkOrderService.create_from_estimate(estimate)` with `JobService.populate_from_estimate(job, estimate)`. The fixture `workorder_from_estimate.json` should be renamed accordingly — see Task G3.

- [ ] **Step 5: Rename `test_work_order_template_edit_delete.py`**

```bash
git mv tests/test_work_order_template_edit_delete.py tests/test_work_template_edit_delete.py
```
Inside, swap all `WorkOrderTemplate` → `WorkTemplate`, `/api/work-order-templates/` → `/api/work-templates/`.

- [ ] **Step 6: Commit after rewrite**

Hold the commit until G2 completes — G2 handles the mechanical bulk swap across remaining test files.

---

### Task G2: Bulk-swap remaining test files

**Files:** all of:
- `tests/test_api_bleps.py`
- `tests/test_api_expenses.py`
- `tests/test_api_home.py`
- `tests/test_api_templates_config.py`
- `tests/test_api_users.py`
- `tests/test_atom_api_permissions.py`
- `tests/test_auto_earmark.py`
- `tests/test_blep_service.py`
- `tests/test_board_api.py`
- `tests/test_board_service.py`
- `tests/test_bundling_services.py`
- `tests/test_comprehensive_models.py`
- `tests/test_crud_operations.py`
- `tests/test_earmark_flow.py`
- `tests/test_earmark_release.py`
- `tests/test_estimates_services.py`
- `tests/test_estworksheet_creation_from_job.py`
- `tests/test_estworksheet.py`
- `tests/test_expense_service.py`
- `tests/test_history_all_models.py`
- `tests/test_in_bundle_display_order.py`
- `tests/test_instance_level_estimate_generation.py`
- `tests/test_inventory_qoh_services.py`
- `tests/test_inventory_qoh.py`
- `tests/test_invoice_line_item_source.py`
- `tests/test_invoice_wizard_api.py`
- `tests/test_invoice_wizard_service.py`
- `tests/test_invoicing_models.py`
- `tests/test_jobs_models_with_fixtures.py`
- `tests/test_jobs_models.py`
- `tests/test_jobs_services.py`
- `tests/test_lineitem_task_generation.py`
- `tests/test_new_templating.py`
- `tests/test_qbo_expense_push.py`
- `tests/test_reorder_requires_post.py`
- `tests/test_search_function.py`
- `tests/test_sort_order_namespaces.py`
- `tests/test_task_bundle.py`
- `tests/test_task_decouple_template.py`
- `tests/test_task_description.py`
- `tests/test_task_generation_bundling.py`
- `tests/test_task_lifecycle_api.py`
- `tests/test_task_lifecycle.py`
- `tests/test_task_reordering.py`
- `tests/test_task_template_edit_delete.py`
- `tests/test_template_bundle_ui.py`
- `tests/test_template_ordering.py`
- `tests/test_template_workflows.py`
- `tests/test_units_model_defaults.py`
- `tests/test_units_serializer_validation.py`
- `tests/test_worksheet_create_from_template.py`

- [ ] **Step 1: Pattern-based substitutions**

For each file above, apply these swaps:

| Old | New |
|---|---|
| `WorkOrder.objects.create(job=X, ...)` | `(nothing — delete line; replace with direct Task creation on Job)` |
| `WorkOrderService.create_from_estimate(est)` | `JobService.populate_from_estimate(job, est)` |
| `WorkOrderService.create_from_template(job, tpl)` | `JobService.populate_from_template(job, tpl)` |
| `WorkOrderService.copy_from_worksheet(wo.pk, ws.pk)` | `JobService.copy_from_worksheet(job.pk, ws.pk)` |
| `WorkOrderService.update_status(wo.pk, 'complete')` | `JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)` |
| `Task.objects.create(work_order=wo, ...)` | `Task.objects.create(job=job, ...)` |
| `task.work_order` | `task.job` |
| `task.work_order.job` | `task.job` |
| `wo.tasks` | `job.tasks` |
| `WorkOrder.STATUS_COMPLETE` | `Job.STATUS_WORK_COMPLETE` |
| `WorkOrder.STATUS_INCOMPLETE` | `Job.STATUS_APPROVED` |
| `WorkOrder.STATUS_BLOCKED` | `(no direct equivalent — see below)` |
| `from apps.jobs.models import ... WorkOrder ...` | remove `WorkOrder` from import list |
| `WorkOrderTemplate` | `WorkTemplate` |
| `work_order_template` | `work_template` |

Use a combination of `sed` for mechanical cases and hand edits for semantic cases. For example:
```bash
for f in tests/test_*.py; do
  sed -i '' \
    -e 's/task\.work_order\.job/task.job/g' \
    -e 's/task\.work_order/task.job/g' \
    -e 's/work_order=wo/job=job/g' \
    -e 's/WorkOrderTemplate/WorkTemplate/g' \
    -e 's/work_order_template/work_template/g' \
    "$f"
done
```

- [ ] **Step 2: Handle block-rollup test cases**

Tests that assert "blocking a task blocks the work order" (in `test_task_lifecycle.py`, `test_api_bleps.py`, possibly others) no longer apply. Delete those test methods; they cover behavior that has been explicitly removed (see design doc). Add a comment at deletion sites for the reviewer: `# Block rollup was removed in the workorder-removal refactor; blocked tasks no longer bubble up.`

- [ ] **Step 3: Handle `_check_wo_auto_complete` tests**

Tests asserting "all tasks complete → WO auto-completes" should now assert "all tasks terminal → Job advances to work_complete". Example rewrite:

```python
def test_completing_last_task_advances_job_to_work_complete(self):
    job = self._approved_job()
    t1 = Task.objects.create(job=job, name='a', ...)
    t2 = Task.objects.create(job=job, name='b', ...)
    TaskLifecycleService.complete_task(t1.pk)
    job.refresh_from_db()
    self.assertEqual(job.status, Job.STATUS_APPROVED)
    TaskLifecycleService.complete_task(t2.pk)
    job.refresh_from_db()
    self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)
```

- [ ] **Step 4: Handle `test_earmark_release.py`**

Rewrite earmark-release tests to trigger on `JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)` instead of WO completion.

- [ ] **Step 5: Run the full test suite**

Run: `python manage.py test -v 1 2>&1 | tail -60`
Expected: most tests pass. For every failure, read the assertion and fix either the test (if the old expectation was WO-specific) or, rarely, the implementation (if a genuine regression slipped in).

**Critical:** do NOT run tests in parallel from subagents. CLAUDE.md calls this out: one MySQL test DB, will deadlock.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: update test suite for Task-on-Job model"
```

---

### Task G3: Update fixtures

**Files:**
- Modify: `fixtures/*.json`
- Rename: `fixtures/workorder_from_estimate.json` → `fixtures/job_from_estimate.json`

- [ ] **Step 1: Remove `jobs.workorder` rows from all fixtures**

```bash
grep -rln '"jobs.workorder"' fixtures/
```
For each fixture file that contains `jobs.workorder` rows, open and delete those rows. Where `jobs.task` rows reference `"work_order": N` in their `fields` object, rewrite as `"job": M` where M is the `job` PK the deleted WO pointed to.

- [ ] **Step 2: Rename the model identifier `jobs.workordertemplate` → `estimates.worktemplate`**

Wait — `WorkTemplate` is in `apps/estimates/models.py`. In fixtures the model identifier is `estimates.worktemplate`. Confirm the app label of `WorkTemplate` and update fixtures accordingly.

```bash
grep -rln '"estimates.workordertemplate"\|"jobs.workordertemplate"' fixtures/ | xargs sed -i '' \
  -e 's/"estimates.workordertemplate"/"estimates.worktemplate"/g' \
  -e 's/"jobs.workordertemplate"/"estimates.worktemplate"/g'
```

- [ ] **Step 3: Rename fixture field `work_order_template` → `work_template`**

```bash
grep -rln '"work_order_template"' fixtures/ | xargs sed -i '' 's/"work_order_template"/"work_template"/g'
```

- [ ] **Step 4: Rename `workorder_from_estimate.json`**

```bash
git mv fixtures/workorder_from_estimate.json fixtures/job_from_estimate.json
```

Review the file: delete any `jobs.workorder` rows, rewrite `jobs.task` `work_order` FK fields to `job`.

- [ ] **Step 5: Verify fixtures load**

Run: `python manage.py test tests.test_jobs_models_with_fixtures -v 2`
Expected: the fixture tests pass (or expose real fixture issues to fix).

- [ ] **Step 6: Commit**

```bash
git add fixtures/
git commit -m "test(fixtures): remove WorkOrder rows, rename work_template references"
```

---

### Task G4: Full test suite green

- [ ] **Step 1: Run all tests**

Run: `python manage.py test 2>&1 | tail -30`
Expected: 0 failures. If any remain, fix them one by one.

- [ ] **Step 2: Commit any stragglers**

```bash
git add -A
git commit -m "test: final fixes for WorkOrder removal refactor"
```

---

## Phase H — Documentation

### Task H1: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Jobs app model list**

Find the section listing Jobs app models. Remove the `WorkOrder` bullet. The remaining models are Job, Task, TaskBundle (if present), Blep.

- [ ] **Step 2: Update Job status description**

Current: `Job - Central entity. Status: draft → approved/rejected → needs_attention/blocked → complete`

Replace with: `Job - Central entity. Status: draft → submitted → approved → work_complete → completed (terminal). Also rejected, cancelled (terminals). 'work_complete' means work is done; 'completed' means fully closed (invoiced/paid).`

- [ ] **Step 3: Update the Job Creation Flow diagram**

Current: `Job → EstWorksheet (from template) → Estimate → WorkOrder → Invoice`
Replace with: `Job → EstWorksheet (from template) → Estimate → Tasks on Job → Invoice`

- [ ] **Step 4: Rename `WorkOrderTemplate` → `WorkTemplate`**

Global substitution inside `CLAUDE.md`:
```bash
sed -i '' 's/WorkOrderTemplate/WorkTemplate/g' CLAUDE.md
```

- [ ] **Step 5: Update the URL Structure section**

Remove references to `/api/work-orders/`. Add `/api/jobs/{id}/tasks/`, `/api/jobs/{id}/work-complete/`, etc. Rename `/api/work-order-templates/` → `/api/work-templates/`.

Remove from the Django HTML Views section: `work orders` references. Remove the `/jobs/ - Jobs (list, create, detail, work orders)` detail.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for WorkOrder removal"
```

---

## Phase I — Final verification

### Task I1: Manual smoke test

- [ ] **Step 1: Start backend and frontend**

```bash
python manage.py runserver &
cd frontend && npm run dev &
```

- [ ] **Step 2: Open the app in a browser**

Open `http://localhost:9000`. Log in.

- [ ] **Step 3: Click through the core flows**

- Create a Job → approve → populate from a template → verify tasks appear.
- Open `#/jobs/[id]/tasklist` — verify the view renders with tasks.
- Complete a task. Complete all tasks. Verify Job auto-advances to `work_complete`.
- Manually advance Job to `completed`. Verify.
- Accept an estimate → create a job from it → verify tasks populated.
- Use the invoice wizard source pool → verify completed job tasks are selectable.

- [ ] **Step 4: Stop servers and commit any last fixes**

```bash
git add -A
git commit -m "fix: last smoke-test polish" || true
```

---

### Task I2: Clean up the plan

- [ ] **Step 1: Delete this plan**

Per user's docs convention (`docs/plans/` holds disposable plans):

```bash
git rm docs/plans/2026-04-12-remove-workorder-model-plan.md
git commit -m "chore: remove completed plan"
```

The design doc at `docs/designs/2026-04-12-remove-workorder-model-design.md` remains as the durable record.

---

### Task I3: Merge the branch

- [ ] **Step 1: Confirm everything green on the branch**

```bash
git log --oneline main..HEAD
python manage.py test 2>&1 | tail -5
```

- [ ] **Step 2: Ask the user how they want to integrate the branch**

Pause and ask: "Refactor is complete. Want me to open a PR, or merge directly to main?"
