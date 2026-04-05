# Task Split and Worksheet → WorkOrder Refactor

## Date: 2026-04-05

## Status

Design approved in brainstorm. Implementation plan to follow.

## Problem

Three related structural problems in the current job/worksheet/work order
pipeline have accumulated into a single tangle that needs to be resolved
before further work on materials, task lifecycle, or worksheet→WO
conversion can proceed cleanly.

### 1. `Task` is dual-purpose

`apps.jobs.models.Task` serves two semantically different roles: a
planning placeholder on an `EstWorksheet`, and a real work item on a
`WorkOrder`. The model distinguishes them only by which nullable FK is
populated (`est_worksheet` or `work_order`) and enforces "exactly one"
in `clean()`.

This creates ~25-30 container-branching code sites across views,
services, signals, serializers, and mixins. It also allows semantically
invalid states (like hierarchical worksheet tasks) that the code then
has to defend against ad-hoc. `TaskBundle` mirrors the same dual-FK
pattern with the same problems.

`BlepService` already enforces at runtime that bleps can only exist on
WO-side tasks (`apps/jobs/services/blep_service.py:101`), acknowledging
the split conceptually without making it type-enforced.

### 2. Three worksheet → WorkOrder paths disagree

Investigation turned up three distinct code paths that convert
(directly or indirectly) from an `EstWorksheet` to a `WorkOrder`, each
producing structurally different WorkOrders from the same source:

- **Path A: Estimate-mediated.** `WorkOrderService.create_from_estimate`
  → `TaskService.create_from_line_item` →
  `_copy_worksheet_tasks`. Bundled tasks collapse into single line
  items; materials detach into their own line items; parent-child
  hierarchy is lost (the "second pass" loop at
  `apps/jobs/services/__init__.py:227-233` is effectively dead code
  because `source_tasks` is always a single-element list).
- **Path B: Direct worksheet copy.** `WorkOrderService.copy_from_worksheet`
  (`apps/jobs/services/__init__.py:124-177`). Preserves bundles, sort
  order, and materials attached to tasks. Silently drops `parent_task`.
- **Path C: Template straight to WO.** `WorkOrderService.create_from_template`
  → `TaskTemplate.generate_task`. Preserves `parent_template`
  recursively, so hierarchy survives. No materials.

Each path serves a legitimate workflow (see "Workflows" below), but the
paths disagree on what "converting to a WorkOrder" means, and nothing
in the UI or API currently steers users to the right path for their
job's shape.

### 3. Hierarchy lives in the wrong place

`Task.parent_task` is a self-FK that is structurally valid on any Task,
planning or real. `TaskTemplate.parent_template` exists and Path C
carries hierarchy through. But the intended mental model is that
hierarchy emerges *during work* — a worker discovers mid-task that it
makes sense to break a task into chunks. That only makes sense on WO-
side tasks. Hierarchy on planning artifacts (worksheets, templates) has
no user story and has been a source of bugs.

## Goals

1. Replace the dual-FK `Task` model with a type-enforced split between
   planning tasks and work tasks.
2. Do the parallel split for `Material` so the planned-vs-actual
   distinction is type-enforced and materials carry the
   PriceListItem linkage forward cleanly from planning to work.
3. Make the three worksheet → WorkOrder workflows first-class:
   preserve all three, route users to the correct one for their job's
   shape, and make the "worksheet → WO copy" path (workflow 3's
   canonical path) actually work correctly.
4. Move hierarchy out of planning artifacts so it only exists where it
   has meaning (on work tasks).
5. Relocate earmark creation off the `estimate_accepted` signal and
   onto WO creation, so all three workflows produce correct earmarks
   and earmark lifecycle follows the WorkOrder.

## Non-goals

- **No refinement of Path A (Estimate → WO).** Minimum mechanical
  changes only to make it compile against the new models. Its quirks
  (bundle collapse, material detachment into line items) are
  preserved. Its real redesign is a future project.
- **No replacement for RealBundle's lost information at WO time.**
  Future invoice-time grouping (the "ad-hoc wizard" idea raised in the
  brainstorm) is a separate project.
- **No materials-in-Svelte work.** That is the paused
  `feature/materials` project and resumes on its own branch after
  this refactor lands. See
  `docs/plans/2026-04-05-materials-in-svelte-and-workorders.md`.
- **No estimate expiration mechanism.** Earmark release is handled
  entirely through the WO lifecycle; estimate expiration remains out
  of scope.
- **No changes to invoice line item generation semantics** beyond
  removing the PLI-required gate, which is a straightforward
  simplification.

## The Three Workflows

This refactor preserves all three and adds routing logic to steer
users to the right one. No workflow is deleted.

| # | Situation                                           | Canonical path  | Role of Estimate                      |
|---|-----------------------------------------------------|-----------------|---------------------------------------|
| 1 | Small / repeat job, trusted customer                | Template → WO   | None — no estimate exists             |
| 2 | Small unfamiliar job, new customer                  | Estimate → WO   | Source of work structure, approval    |
| 3 | Larger / unfamiliar job                             | Worksheet → WO  | Customer approval only (not WO source)|

The key insight distinguishing workflow 3 from workflow 2: in workflow
3 the `Estimate` is a customer-facing artifact generated *from* the
worksheet, and customer approval happens via the estimate, but the
WorkOrder is built from the **Worksheet**, not from the Estimate. The
estimate does its job and then steps out of the way.

## Model Design

### Task split

```
TaskBase (abstract)
  name
  description
  sort_order
  units
  rate
  est_qty
  accounting_category  (FK, nullable)

PlanTask(TaskBase)
  est_worksheet  FK
  mapping_strategy  ('direct' | 'bundle' | 'exclude')
  bundle           FK to PlanBundle (nullable)
  # no assignee, no status, no parent_task, no bleps, no materials of type Material

Task(TaskBase)
  work_order     FK
  assignee       FK to User (nullable)
  status         (pending | in_progress | blocked | complete | cancelled)
  parent_task    FK to self (nullable)
  # bleps via reverse FK
  # materials (Material) via reverse FK
  # no mapping_strategy, no bundle
```

Notes:
- `TaskBase` is **abstract** (Django `Meta: abstract = True`). No base
  table, fields copied into each subclass. We never need to query "all
  tasks regardless of type" at the DB level, and abstract avoids the
  join overhead and polymorphism quirks of multi-table inheritance.
- The unqualified name `Task` belongs to the work-side (execution)
  model. Planning gets the qualified `PlanTask`. This matches the
  mental model that the work-side is the canonical, default thing.
- `parent_task` exists only on `Task`. `PlanTask` cannot have
  hierarchical structure. `TaskTemplate.parent_template` is removed.
- `status` exists only on `Task`. `PlanTask` has no lifecycle state
  because planning tasks never get worked on.
- `bleps` exist only on `Task`. Already enforced at runtime today;
  becomes type-enforced after the split.

### Bundle simplification

```
PlanBundle
  est_worksheet          FK
  name
  description
  accounting_category    (FK, nullable)
  sort_order
  source_template_bundle (FK to TemplateBundle, nullable)
```

`PlanBundle` is the only bundle model that exists after the refactor.
It replaces the current `TaskBundle` entirely — the current model's
work-order-side usage is deleted.

**`RealBundle` does not exist.** On a WorkOrder, tasks are flat. When a
worksheet is copied to a WO, bundle grouping is discarded. Workers see
a flat task list on the WO.

Accepted trade-offs:
- Bundle `name` and `description` (e.g. "Kitchen Install Phase") do not
  appear on the WO. A user who wants to know the phase structure goes
  back to the worksheet.
- Bundle `accounting_category` is not inherited onto `Task`s at copy
  time. This is fine because `Task.accounting_category` is set
  directly on the task; the bundle's category was only used at
  bundle-line-item generation time on the estimate side.
- Future invoice-time line-item grouping (if implemented) is a
  separate project and does not depend on `RealBundle` existing.

### Material split

```
MaterialBase (abstract)
  description
  quantity
  unit_cost
  sell_price
  price_list_item     FK (optional, nullable — set at creation or never)
  accounting_category FK (optional, nullable)
  line_item_type      FK (required; drives estimate/invoice line item generation)

PlannedMaterial(MaterialBase)
  plan_task  FK to PlanTask

Material(MaterialBase)
  task  FK to Task
```

Notes:
- `MaterialBase` is abstract, same rationale as `TaskBase`.
- `price_list_item` is set at creation time or never. There is no
  "firming up" phase where a freeform material is later promoted to
  PLI-linked. A freeform material and a PLI-linked material are
  different kinds of records and promoting one to the other would
  quietly rewrite inventory history.
- `price_list_item` **carries forward** from `PlannedMaterial` to
  `Material` at worksheet → WO copy time. The FK is preserved, not
  re-derived.
- `line_item_type` lives on the base because both estimate line items
  and invoice line items need it regardless of which side the
  material was on.
- `PlannedMaterial` has **zero inventory side effects**. No earmarks,
  no QOH touch. It is purely planning data.

### `EstimateLineItem.task` retargeting

`EstimateLineItem.task` retargets to `PlanTask` (was the dual-FK
`Task`). This matches where the reference actually comes from:
`EstimateGenerationService` pulls tasks from an `EstWorksheet`, which
after the split contains `PlanTask` rows.

### `TaskTemplate.parent_template` removal

`TaskTemplate.parent_template` is removed. The recursive child
generation in `TaskTemplate.generate_task()` at
`apps/estimates/models.py:507-516` becomes a flat loop over
associations. Templates define flat task lists; hierarchy emerges later
on the WO side if needed.

## Worksheet → WorkOrder Conversion (Path B, the canonical path)

`WorkOrderService.copy_from_worksheet` is rewritten against the new
models:

```python
def copy_from_worksheet(work_order_pk, worksheet_pk):
    wo = WorkOrder.objects.get(pk=work_order_pk)
    ws = EstWorksheet.objects.get(pk=worksheet_pk)

    for plan_task in PlanTask.objects.filter(est_worksheet=ws).prefetch_related('materials'):
        task = Task.objects.create(
            work_order=wo,
            name=plan_task.name,
            description=plan_task.description,
            units=plan_task.units,
            rate=plan_task.rate,
            est_qty=plan_task.est_qty,
            accounting_category=plan_task.accounting_category,
            sort_order=plan_task.sort_order,
            # assignee and status use their own defaults
            # parent_task is None — hierarchy emerges during work
        )
        for pm in plan_task.plannedmaterial_set.all():
            Material.objects.create(
                task=task,
                description=pm.description,
                quantity=pm.quantity,
                unit_cost=pm.unit_cost,
                sell_price=pm.sell_price,
                price_list_item=pm.price_list_item,  # carries forward
                accounting_category=pm.accounting_category,
                line_item_type=pm.line_item_type,
            )
```

No bundle handling. No parent_task handling. No `mapping_strategy`
carryover. No filtering based on `mapping_strategy='exclude'` (that
concept belongs to estimate generation, not WO creation). Every
`PlanTask` on the worksheet becomes a `Task` on the WorkOrder; every
`PlannedMaterial` becomes a `Material`.

After the loop, the new earmark hook runs (see "Earmark lifecycle"
below).

## Path A Minimal-Change Treatment

`WorkOrderService.create_from_estimate` and
`TaskService.create_from_line_item` stay semantically the same. Only
the changes required to compile against the new models:

- `EstimateLineItem.task` is now a FK to `PlanTask`, so
  `_copy_worksheet_tasks` copies from a `PlanTask` to a `Task`. The
  dead "second pass parent loop" disappears automatically because
  `PlanTask` has no `parent_task`.
- The catalog and manual branches of `create_from_line_item` are
  untouched — they already create `Task` records from line item fields.
- No behavioral changes. Path A's bundle-collapse and material-detach
  behavior is preserved as-is. Refining Path A is a future project.

In practice, Path A's `line_item.task` branch will rarely fire under
the new routing rules: workflow 2 (hand-written estimate) produces
line items without `.task` references, and workflow 3 should route
through Path B. The branch only fires if a user overrides the workflow
warning.

## Workflow Routing: Restrictions and Warnings

WorkOrders are editable post-creation, so routing restrictions are
about preventing pointless initial state and steering toward the right
path, not about enforcing correct outcomes.

**Hard prerequisite gates (enforced by API):**
- `Template → WO` requires a template to exist and be selected.
- `Estimate → WO` requires an estimate to exist on the job.
- `Worksheet → WO` requires a worksheet to exist on the job.

These are existence checks, not workflow checks. A user cannot click
"Create WO from Worksheet" on a job with no worksheet.

**Soft workflow warnings (API returns OK with a warning; UI surfaces
as a confirmation dialog):**
- `Estimate → WO` when the job has a Worksheet. Warn: "This job has a
  Worksheet. Usually the Worksheet is the source for the WorkOrder,
  not the Estimate. Proceed anyway?"
- `Template → WO` when the job has a Worksheet or an Estimate. Warn:
  "This job already has [Worksheet/Estimate]. Template → WO is usually
  for jobs that go straight to work. Proceed anyway?"

**No restriction:**
- `Worksheet → WO` without an Estimate. A user may legitimately have a
  worksheet for internal planning that doesn't need customer approval.

**UI demotion (implementation detail, not spec-enforced):**
The SPA may demote non-preferred buttons for a given job's shape
(smaller, greyer, lower in the menu) even when they're not
warning-gated, as visual steering. Demotion rules parallel the
warning rules.

The API surface is responsible for the hard prerequisite checks and
for returning warning metadata on soft-warning cases. The SPA is
responsible for rendering warnings as confirmation dialogs and for any
demotion behavior.

## Earmark Lifecycle

Earmark creation moves off the `estimate_accepted` signal entirely.

**Current (to be deleted):**
- `apps/estimates/signals.py:117-135` `auto_earmark_inventory` —
  deleted.
- `InventoryService.get_earmark_preview(job)` currently queries
  `task__est_worksheet__job=job` (`apps/inventory/services.py:175`).
  Rewritten to query `task__work_order__job=job`.

**New:**
- Earmark creation runs as a hook in `WorkOrderService` after each of
  the three WO creation paths completes. It aggregates `Material`
  records on the new WorkOrder by PLI and calls
  `InventoryService.create_earmarks_for_job(job, data)`.
- This gives all three workflows correct earmarks — today workflows 1
  and 2 produce no earmarks at all because the estimate-acceptance
  signal only looked at worksheet materials (a latent bug).

**Release:**
- Drawdown continues to happen via `consume_material` at WO task
  lifecycle transitions. Its defensive "worksheet OR work_order"
  branch at `services.py:73-75` is simplified because after the split,
  `material.task` is always a `Task`.
- WO cancellation releases any remaining earmark balance for the job.
- WO completion releases any un-consumed remainder (trailing
  garbage collection).

**`PlannedMaterial` has no inventory interaction whatsoever.** No
earmarks, no QOH touches, no signals. This is a clean, verifiable
invariant.

**PO-received earmarks are unchanged.** `receive_po_line_item` in
`InventoryService` still creates `(PLI, Job)` earmarks when inventory
is received against a job; it never involved Material records and is
unaffected by this refactor.

**Timing trade-off acknowledged:** In workflow 3, between estimate
acceptance and WO creation, inventory is not reserved. In practice
this window is seconds-to-minutes and can be closed by prompting the
user to create the WO immediately after estimate acceptance. Workflows
1 and 2 had no earlier reservation to begin with, so there is no
regression for them.

## API Shape

Two fully separated resources.

**Existing (unchanged on the wire):**
- `/api/tasks/{id}/` — `Task` (work-side). Returns the same payload
  shape it does today, minus any fields that only existed because of
  the dual-FK model.
- `/api/work-orders/{id}/tasks/` — nested `Task` list. Unchanged.

**New:**
- `/api/plan-tasks/{id}/` — `PlanTask`.
- `/api/worksheets/{id}/plan-tasks/` — nested `PlanTask` list.
- `/api/worksheets/{id}/bundles/` — nested `PlanBundle` list. If a
  bundles endpoint already exists on the current unified `/bundles/`,
  it is renamed (or the planning-side endpoint supersedes it).

`TaskBundleMixin` in `apps/api/mixins.py` is split or specialized: its
planning-side behavior becomes `PlanTaskBundleMixin` (used by
worksheets), and the work-order side uses a simpler task-only mixin
because bundles don't exist on the WO side.

Serializers split: `PlanTaskSerializer` / `PlanTaskDetailSerializer`
for the planning side, existing `TaskSerializer` /
`TaskDetailSerializer` for the work side. Any polymorphic fields
(e.g., the current `get_work_order` conditional at
`apps/api/tasks/serializers.py:27-40`) simplify.

## SPA URL Structure

Existing routes unchanged:
- `#/jobs/[id]/tasks/[task_id]` — `Task` detail.

New routes:
- `#/worksheets/[ws_id]/plan-tasks/[pt_id]` — `PlanTask` detail. Flat
  under `worksheets/` (not nested under `jobs/`). A PlanTask has no
  meaning outside its worksheet, and the job context is recoverable
  from the worksheet's own FK.

The asymmetry (Tasks nested under jobs, PlanTasks nested under
worksheets) is semantically correct: tasks are "the work on this job";
plan-tasks are "scaffolding on this specific planning document."

## Impacts on Related Systems

### `docs/designs/2026-03-06-material-pli-lifecycle.md`

Phases 4 and 5 of that document are superseded by this refactor:

- **Phase 4 ("WorkOrder firm up") is deleted.** There is no firming
  up phase. `price_list_item` is set at creation time or never.
- **Phase 5's invoice PLI gate is deleted.** A Material with a
  `line_item_type` can become an InvoiceLineItem regardless of PLI
  status. The original doc's gate existed because `line_item_type`
  wasn't on Material yet; once it was added (Phase 1 of that doc's
  own implementation plan), the gate became redundant.

The 2026-03-06 doc gets an amendment section dated 2026-04-05 pointing
at this spec. The original text is preserved for decision-history
purposes.

### Signals

- `estimate_accepted` → `auto_earmark_inventory` (deleted).
- Other signals in `apps/estimates/signals.py` are unaffected.

### Permissions

No atom changes. The existing atoms (`can_manage_jobs`,
`can_manage_financials`, etc.) apply identically to the new endpoints:

- `PlanTask` write endpoints require `can_manage_jobs`.
- `Task` write endpoints continue to require `can_manage_jobs` for
  structural changes, `IsAuthenticated` for task lifecycle actions a
  worker can take on their assigned work (matching current behavior).

### Tests

Approximately 41 test files and 285 test methods reference `Task`
construction. These update mechanically: tests that built a Task with
`est_worksheet=...` now build a `PlanTask`; tests that built a Task
with `work_order=...` now build a `Task`. Fixtures likewise split.

Tests exercising worksheet → WO conversion (existing
`test_workorder_from_estimate.py`,
`test_task_lifecycle.py`, `test_earmark_flow.py`,
`test_auto_earmark.py`) get rewritten to cover:
- Path B produces the correct flat-task WO with preserved materials
  and carried-forward PLI links.
- Path A still works for workflows 2 and 3-with-override.
- Earmarks derive from WO materials on WO creation for all three
  paths.
- `PlannedMaterial` never touches inventory.
- Workflow routing warnings fire at the right times.

### Frontend

No SPA changes are strictly required by this refactor — the SPA
currently has no PlanTask UI at all. However, the new `/api/plan-tasks/`
endpoints and `#/worksheets/[ws_id]/plan-tasks/` routes should exist
and be wired up so the downstream materials-in-Svelte project can
build on them immediately.

## Migration Strategy

This is a significant data model refactor with a non-trivial
migration. Detailed migration steps belong in the implementation plan
rather than this design doc, but the shape of the migration is:

1. Create new tables (`plan_tasks`, `tasks_new`, `plan_bundles`,
   `planned_materials`, `materials_new`, plus the `MaterialBase`/
   `TaskBase` abstract-inherited field sets materialized per
   subclass).
2. Copy existing `jobs_task` rows into `plan_tasks` or `tasks_new`
   based on which container FK is populated.
3. Copy existing `task_bundles` rows (planning ones) into
   `plan_bundles`. Work-order-side bundles are dropped.
4. Copy existing `materials` rows into `planned_materials` or
   `materials_new` based on their task's container.
5. Update all dependent FKs (`bleps`, `estimate_line_items`,
   `earmarks`-derivation) to target the new tables.
6. Drop the old tables.
7. Rename `tasks_new` → `tasks`, `materials_new` → `materials`.

The migration should be written as an atomic Django migration set and
tested against a copy of any existing non-trivial dataset before
running in any shared environment. Because `parent_task` is being
removed from the planning side, any existing data where worksheet
tasks have a `parent_task` value needs a decision: silently drop
(likely correct, since hierarchy was never intended there) or flag
for manual review. Based on the project's pre-production state, silent
drop is acceptable; the implementation plan should verify no
production data is affected.

## Out of Scope (Reiterated)

- Materials-in-Svelte UI (paused project, resumes after this lands).
- Refinement of Path A (Estimate → WO) semantics.
- Invoice-time ad-hoc task/material grouping (the "wizard" idea).
- Estimate expiration mechanism.
- Any changes to `consume_material` semantics beyond the container-
  branch simplification.

## Related Documents

- `docs/designs/2026-03-06-material-pli-lifecycle.md` — predecessor
  lifecycle doc; phases 4 and 5 are superseded by this spec (amendment
  section to be added pointing here).
- `docs/plans/2026-04-05-materials-in-svelte-and-workorders.md` —
  paused project, resumes after this refactor.
- `docs/designs/2026-03-07-model-inventory.md` — inventory model
  design, unaffected.
- `docs/designs/2026-03-15-task-lifecycle-design.md` — task lifecycle;
  minor simplifications from dropping the `worksheet-task` defensive
  checks.
