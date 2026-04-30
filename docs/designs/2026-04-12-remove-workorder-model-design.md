# Design: Remove WorkOrder Model

**Date:** 2026-04-12
**Status:** Approved for planning

## Summary

Eliminate the `WorkOrder` model entirely. `Task` belongs directly to `Job`. The `WorkOrder` layer provided no meaningful grouping (Job ↔ WorkOrder is 1:many in the schema but 1:1 in practice) and only added indirection when linking Jobs to the work within them.

## Motivation

Today a Job aggregates: 0+ EstWorksheets, 0+ Estimates, 0+ WorkOrders, 0+ Invoices, 0+ PO line items, 1 Contact, 0–1 Business. `WorkOrder` was conceived as the execution-side parallel to `EstWorksheet` (planning), both containing task lists. After working with the model, the WorkOrder container earns nothing: every query that starts at a Job and wants its Tasks must traverse an extra hop, and every service method that operates on WO-scoped state would read more naturally as Job-scoped.

The abstraction survives for planning (`EstWorksheet` still contains `PlanTask`s — see `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md`). Only the execution-side container is collapsing.

## Scope

**In scope:** Models, services, API, frontend routes and components, tests, fixtures, the search index, migrations, `CLAUDE.md`.

**Out of scope:** Other `docs/designs/` updates (they stay as historical record). Rework of `JobDetailPage.svelte` to absorb the task list view — deferred to a later pass.

## Design

### 1. Data model

**Deleted:** `WorkOrder` model and `workorders` table.

**`AbstractWorkContainer`** (`apps/core/models.py`) — reshaped:

```python
class AbstractWorkContainer(models.Model):
    template = FK('estimates.WorkTemplate', SET_NULL, null=True, blank=True)
    class Meta: abstract = True
    def populate_from_template(self, template): ...  # shared
```

The `job` FK leaves the abstraction (it only applied to EstWorksheet; Job cannot self-reference). The abstraction's remaining value: one FK plus shared `populate_from_template()` logic, keeping template-population code in one place.

**`Job`** (`apps/jobs/models.py`):
- Extends `AbstractWorkContainer` (gains `template` FK).
- New status choice: `STATUS_WORK_COMPLETE = 'work_complete'` — "work is done, invoicing/payment still open." The existing `STATUS_COMPLETED = 'completed'` remains the fully-closed terminal (all invoices paid).
- Status progression: `draft → submitted → approved → work_complete → completed`. Terminals: `rejected`, `cancelled`, `completed`.
- Transition map addition: `APPROVED → [WORK_COMPLETE, CANCELLED]` (replaces `APPROVED → [COMPLETED, CANCELLED]`), `WORK_COMPLETE → [COMPLETED, CANCELLED]`.
- **No Job-level block status** in this refactor. Today's WO-level block rollup (task blocked → WO blocked) is dropped; blocked tasks remain visible at the task level and on the tasklist view, but do not bubble up to Job status. Revisiting later is deferred.

**`EstWorksheet`** (`apps/estimates/models.py`):
- Still extends `AbstractWorkContainer`.
- Declares its own `job = FK(Job, CASCADE)` directly (no longer inherited).

**`Task`** (`apps/jobs/models.py`):
- `work_order = FK(WorkOrder)` → **`job = FK(Job, CASCADE, related_name='tasks')`**.

**Rename:** `WorkOrderTemplate` → `WorkTemplate` (model, `db_table`, all references in `TemplateTaskAssociation`, `TemplateBundle`, serializers, URLs, fixtures).

**Unchanged:** `Blep` (FK Task), `Material` (FK Task), `Invoice` (already Job-scoped), `PlanTask`/`PlanBundle`/`PlanMaterial` on the EstWorksheet side. `TaskBundle` was already removed in migration 0009; no concern.

### 2. Services

**Delete `WorkOrderService`** (`apps/jobs/services.py`). Responsibilities absorbed by `JobService` (which already exists at line 215):

| Old `WorkOrderService` method | New `JobService` method |
|---|---|
| `create_direct(job, ...)` | *(gone — creating a Job implicitly gives you a work container)* |
| `create_from_template(job, template)` | `populate_from_template(job, template)` |
| `create_from_estimate(job, estimate)` | `populate_from_estimate(job, estimate)` |
| `copy_from_worksheet(wo_pk, worksheet_pk)` | `copy_from_worksheet(job_pk, worksheet_pk)` |
| `update_status(wo, new_status)` | extends `JobService.update_status(job, new_status)` to handle `work_complete` |

**Earmark release:** currently fires via `InventoryService.release_earmarks_for_job(wo.job)` on WO → `complete`. In the new model, fires on Job entering `STATUS_WORK_COMPLETE`.

**Task auto-rollup** (existing behavior in `TaskLifecycleService`, services.py:580–637) is partially preserved, retargeted at Job:
- **Kept:** When a task completes and no non-terminal tasks remain on the job → Job auto-advances to `work_complete`. Only fires if Job is currently `approved`.
- **Dropped:** task-blocks-container and task-unblocks-container behaviors. Blocked tasks no longer bubble up to Job status. `_check_wo_blocked` and `_check_wo_unblocked` are removed.

**`TaskService`** — mechanical swap of `work_order` → `job` in `_copy_worksheet_tasks`, `_create_task_from_catalog_item`, `_create_generic_task`, `create_from_template`, `create_direct`.

**Signals:** `apps/jobs/signals.py` is empty; nothing to change there.

### 3. API

**Removed:** `apps/api/work_orders/` (viewset, serializers, mixins, urls). `/api/work-orders/` router registration gone.

**Task endpoints move to Job-scoped:**

| Old | New |
|---|---|
| `POST /api/work-orders/{id}/tasks` | `POST /api/jobs/{id}/tasks` |
| `PATCH/DELETE /api/work-orders/{id}/tasks/{tid}` | `PATCH/DELETE /api/jobs/{id}/tasks/{tid}` |
| `POST /api/work-orders/{id}/complete` | `POST /api/jobs/{id}/work-complete` |
| `POST /api/work-orders/{id}/block` | *(removed — no Job-level block status)* |
| `POST /api/work-orders/{id}/reopen` | *(removed — WO-level reopen had no Job equivalent; reopening a completed/work_complete job is a separate future concern)* |
| `POST /api/work-orders/{id}/create-from-template` | `POST /api/jobs/{id}/populate-from-template` |
| `POST /api/work-orders/{id}/create-from-estimate` | `POST /api/jobs/{id}/populate-from-estimate` |
| `POST /api/work-orders/{id}/copy-from-worksheet` | `POST /api/jobs/{id}/copy-from-worksheet` |
| `POST /api/work-orders/{id}/add-from-template` | `POST /api/jobs/{id}/add-from-template` |
| `POST /api/work-orders/{id}/materials` | `POST /api/jobs/{id}/tasks/{tid}/materials` |
| `POST /api/work-orders/{id}/reorder` | `POST /api/jobs/{id}/reorder-tasks` |

**Template rename ripple:**
- `/api/work-order-templates/` → `/api/work-templates/` (router re-register, serializer rename, URL name updates).

**Mixins** (`apps/api/mixins.py`):
- `WorkOrderTaskMixin` → retargeted and renamed `JobTaskMixin`.
- `StatusTransitionMixin` on `JobViewSet` gains the `work_complete` action.
- `LineItemMixin`, `TaskLifecycleMixin` — internal `task.work_order` → `task.job` swap.

**`JobSerializer`** adds `tasks` (nested, read) and `template` FK. Frontend no longer round-trips through a work order to reach tasks.

**Permissions unchanged.** `CanManageJobs` still gates writes; `IsAuthenticated` still covers reads and the "authenticated user adds a task to existing work" affordance.

### 4. Frontend

**Route preservation:** the existing `#/workorders/[id]` view is moved, not deleted.

| Old | New |
|---|---|
| `#/workorders/[id]` → `routes/workorders/WorkOrderDetailPage.svelte` | `#/jobs/[id]/tasklist` → `routes/jobs/JobTaskListPage.svelte` |

The component's UI stays as-is. Only the data source changes: `GET /api/work-orders/{id}` → `GET /api/jobs/{id}` (with nested tasks in the response). Later rework will likely fold this into `JobDetailPage.svelte`; explicitly out of scope here.

**Other Svelte components touched:**
- `components/jobs/JobDetail.svelte` — remove work-order list; link to `#/jobs/[id]/tasklist`.
- `routes/jobs/JobDetailPage.svelte` — same: remove WO list section, add tasklist link.
- `components/TaskModal.svelte` — replace `work_order` context with `job` context.
- `components/invoices/WizardSourcePool.svelte` — retarget "invoice line-item source" pool from WO tasks to job tasks.
- `components/expenses/ExpenseForm.svelte`, `MaterialPicker.svelte` — swap WO references for job references.

**`frontend/src/lib/api.js`:**
- Remove `workOrders.*` helpers.
- Add `jobs.tasks.*`, `jobs.populateFromTemplate`, `jobs.populateFromEstimate`, `jobs.copyFromWorksheet`, `jobs.reorderTasks`, `jobs.workComplete` helpers.

**Django HTML templates** (`templates/jobs/`):
- Delete `work_order_list.html`, `work_order_detail.html` (no Django views render them; UI is Svelte).
- Rename `work_order_template_*.html` → `work_template_*.html`.

### 5. Search

`apps/search/services.py` currently indexes WorkOrder as its own category.

- Remove `CATEGORY_WORK_ORDERS` constant and its routing.
- Remove `'work_orders'` from the default categories list at line 62.
- Remove the `'WorkOrder'` mapping at line 649 and the `result_ids['WorkOrder']` branch at lines 797–806.
- **Rename** `search_work_orders_with_tasks(query)` → `search_jobs_with_tasks(query)`. It now:
  - Queries Jobs matching by `job_number` or `description`.
  - Queries Tasks matching by `name`, `units`, `rate`, or `job.job_number` (swap `task.work_order.job.job_number` → `task.job.job_number`).
  - Groups results: each entry is `{'parent': job, 'tasks': [matching tasks]}`.
- The existing `CATEGORY_JOBS` path is replaced by (or merged with) this grouped version, so searching a job now surfaces its matching tasks inline instead of requiring a separate work-order category. Flat-list handling at lines 561/615/675 that special-cases `'work_orders'` and `'est_worksheets'` is updated: `'jobs'` now uses the grouped shape, and `'work_orders'` is dropped from those branches.

### 6. Tests

TDD per project convention: rewrite tests first, then implementation.

| File | Action |
|---|---|
| `test_api_work_orders.py` | Delete. Behaviors absorbed by extended `test_api_jobs.py` and a new `test_api_job_tasks.py`. |
| `test_api_wo_creation.py` | Rewrite as `test_api_job_population.py`. |
| `test_api_workorder_ui.py` | Rewrite as `test_api_job_tasklist.py`. |
| `test_workorder_from_estimate.py` | Rewrite as `test_job_from_estimate.py`. |
| `test_jobs_models_with_fixtures.py` | Drop WorkOrder assertions; add `work_complete` status; assert `job.tasks` relation. |
| `test_task_lifecycle.py` | Rollup targets Job; earmark release fires on `Job.STATUS_WORK_COMPLETE`; auto-unblock targets Job. |
| `test_work_order_template_edit_delete.py` | Rename `test_work_template_edit_delete.py`. |
| Other test files referencing `WorkOrder.objects.create(...)` or `task.work_order` | Mechanical swap. |

Fixtures (`/fixtures/` and `unit_test_data.json`):
- Drop `jobs.workorder` rows; ensure tasks carry `job` FK.
- `workordertemplate` → `worktemplate` records.

### 7. Migration

Single big-bang migration in `apps/jobs/migrations/`:

1. `RenameModel`: `WorkOrderTemplate` → `WorkTemplate`; `RenameField` references in `TemplateTaskAssociation`, `TemplateBundle`.
2. `AddField`: `Task.job` (FK Job, nullable temporarily).
3. `RunPython`: copy `task.work_order.job_id` → `task.job_id` for all tasks. Safety belt; costs nothing.
4. `AlterField`: `Task.job` → non-nullable, CASCADE, `related_name='tasks'`.
5. `RemoveField`: `Task.work_order`.
6. `AlterField`: `Job.status` choices include `work_complete`.
7. `AddField`: `Job.template` FK → `WorkTemplate`.
8. Move `job` FK from `AbstractWorkContainer` to `EstWorksheet` directly.
9. `DeleteModel`: `WorkOrder`.

Agent runs `makemigrations`; user runs `migrate` (per `CLAUDE.md`).

**Branch strategy:** single feature branch off `main`, merged when all tests pass.

## CLAUDE.md updates

- Remove `WorkOrder` from the Jobs app model list.
- Add `STATUS_WORK_COMPLETE` to the Job status progression in the Business Workflows section.
- Update the Job Creation Flow: `Job → EstWorksheet (optionally from template) → Tasks → Estimate → Tasks on Job → Time tracking (Bleps) → Invoice`.
- Rename `WorkOrderTemplate` → `WorkTemplate`.
- Update permissions mapping text that references work-order routes.

## Non-goals

- Rework of `JobDetailPage.svelte` layout.
- Changes to the PlanTask / planning-side split (`docs/designs/2026-04-05-...`).
- Any change to invoicing, POs, contacts, businesses, or inventory beyond the earmark-release trigger retargeting.
- Updates to other `docs/designs/` files (they remain as historical record).
