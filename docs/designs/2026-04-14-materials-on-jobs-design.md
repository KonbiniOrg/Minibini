# Materials attached to Jobs directly

## Motivation

Materials today are bound to a `Task` via a required FK. To capture a material
that isn't part of any task — for example, an expense-reimbursed purchase, a
miscellaneous consumable, or a job-level item that simply doesn't warrant a
task — the code invents a placeholder `Task` named "Materials" and attaches
the material there. `ExpenseService.find_or_create_materials_task`
(`apps/expenses/services.py:145`) is the canonical offender.

This refactor moves `Material` (and its worksheet-side twin `PlanMaterial`)
to attach to its container (`Job`, `EstWorksheet`) directly, with the existing
`Task`/`PlanTask` association becoming optional. It also adds a new
`TemplateMaterial` model to `WorkTemplate` so jobs and worksheets populated
from templates can carry job-level materials.

The refactor preserves the existing earmark/inventory semantics for materials
backed by inventoried `PriceListItem`s, extends those semantics to task-less
materials with explicit Consume / Restock / Draw-more actions, and unifies
the "expense-born inventoried material" path with the existing PO-receive
path (both become "stock in, earmark, normal consume").

## Current state

Relevant existing models:

- `MaterialBase` (abstract, `apps/inventory/models.py:94`) — shared fields for
  `PlanMaterial` and `Material`: description, quantity, unit_cost, sell_price,
  optional PLI, optional accounting_category.
- `PlanMaterial` (`apps/inventory/models.py:133`) — worksheet-side, required
  `plan_task` FK. No inventory side effects.
- `Material` (`apps/inventory/models.py:152`) — job-side, required `task` FK.
  Participates in earmark/QOH.
- `Earmark` (`apps/inventory/models.py:5`) — `(price_list_item, job, quantity)`
  unique-together. Per-PLI-per-Job aggregate, not per-material.
- `AbstractWorkContainer` (`apps/core/models.py:183`) — abstract base for
  `Job` and `EstWorksheet`. Holds `template` FK and a `populate_from_template`
  stub.
- `WorkTemplate` (`apps/estimates/models.py:317`) — singular template model
  (no "Plan" variant). `TemplateTaskAssociation` + `TemplateBundle` are its
  children. No material concept today.

Relevant existing services:

- `InventoryService.create_earmarks_for_job(job)` (`apps/inventory/services.py:251`)
  aggregates `Material.objects.filter(task__job=job, price_list_item__is_inventoried=True)`
  by PLI and upserts Earmark rows. Runs at the end of `populate_from_template`,
  `populate_from_estimate`, and `copy_from_worksheet`.
- `InventoryService.consume_material(material)` (`apps/inventory/services.py:60`)
  decrements QOH, increments qty_sold, shrinks the (pli, job) earmark. Called
  at task-start.
- `InventoryService.receive_po_line_item(po_line_item)` (`apps/inventory/services.py:38`)
  bumps QOH and upserts the earmark when a PO line item with a job is received.
- `InvoiceWizardService.get_source_pool(invoice)` (`apps/invoicing/services.py:200`)
  walks tasks → blep/material atoms for the invoice wizard.
- `EstimateGenerationService.generate_estimate_from_worksheet(worksheet)`
  (`apps/estimates/services.py:640`) walks plan tasks → plan materials.

## Scope and non-goals

**In scope:**

- Make `Material.task` and `PlanMaterial.plan_task` optional.
- Add required `Material.job` and `PlanMaterial.est_worksheet` FKs.
- Add `TemplateMaterial` model on `WorkTemplate`.
- New uniform state machine and op set for inventoried Materials:
  Consume, Restock(qty), Draw more(qty), Edit description.
- Add `restocked_qty` field on Material to track partial-release.
- Unify expense-born inventoried materials into the earmark pipeline
  (expense submit → QOH bump via a dedicated op; earmark via
  `MaterialService.create_on_job`).
- Service-mediated earmark mutations through a single
  `InventoryService._mutate_earmark` helper — no Django signals.
- Update invoice wizard source pool, estimate generation, and
  worksheet→job copy paths to handle task-less materials.
- Data migration: backfill `job`/`est_worksheet` FKs; clean up placeholder
  "Materials" tasks.

**Out of scope:**

- PO receive path changes. Untouched; folds naturally into the same earmark
  pipeline when an inventoried PLI is received with a job link.
- Retroactive PLI firm-up flow for existing freeform materials (already
  settled by the 2026-03-06 lifecycle doc amendment).
- Bundling task-less PlanMaterials on estimates. Each becomes its own
  direct line item; a future "bundle these worksheet-level materials" flag
  is out of scope.
- Expense UI error handling (flagged in memory as a pre-existing issue).
- Reassigning a Material from one job to another.

## Schema changes

### `Material` (`apps/inventory/models.py`)

- `task` → `ForeignKey(Task, on_delete=SET_NULL, null=True, blank=True, related_name='materials')`
  - **On-delete semantics change:** was CASCADE. Deleting a Task no longer
    destroys its Materials; the Material survives as task-less on the same
    Job. This prevents earmark orphaning when a Task is deleted without
    going through the service layer.
- **new** `job` → `ForeignKey(Job, on_delete=CASCADE, related_name='materials')`, not-null
  - CASCADE is safe here because `Earmark.job` also cascades on Job
    deletion; earmarks die with the job they belong to, no orphans.
- **new** `consumption_state` → `CharField(max_length=20, choices=CONSUMPTION_STATE_CHOICES, default='na')`
  - Choices: `na`, `pending`, `consumed`
- **new** `restocked_qty` → `DecimalField(max_digits=10, decimal_places=2, default=0)`
- `clean()` enforces:
  - `self.task is None or self.task.job_id == self.job_id`
  - `self.restocked_qty >= 0 and self.restocked_qty <= self.quantity`
- `save()` auto-sets `consumption_state`:
  - `'pending'` on creation when `price_list_item` is inventoried.
  - `'na'` otherwise.
- `effective_qty` property: `quantity - restocked_qty`.
- `is_expense_bound` property: `self.expenses.exists()` (lazy check via
  reverse relation from `Expense.material`).

### `PlanMaterial` (`apps/inventory/models.py`)

- `plan_task` → `ForeignKey(PlanTask, on_delete=CASCADE, null=True, blank=True, related_name='plan_materials')`
- **new** `est_worksheet` → `ForeignKey(EstWorksheet, on_delete=CASCADE, related_name='plan_materials')`, not-null
- `clean()` enforces: `self.plan_task is None or self.plan_task.est_worksheet_id == self.est_worksheet_id`
- No `consumption_state` or `restocked_qty` — worksheet side never touches
  inventory.

### `TemplateMaterial` (new, `apps/inventory/models.py`)

```python
class TemplateMaterial(MaterialBase):
    """Template-level material on a WorkTemplate. Populated as task-less
    PlanMaterial (on EstWorksheet) or task-less Material (on Job)."""
    template_material_id = models.AutoField(primary_key=True)
    work_template = models.ForeignKey(
        'estimates.WorkTemplate', on_delete=models.CASCADE,
        related_name='materials',
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_materials'
        ordering = ['sort_order']
```

- All fields from `MaterialBase` are optional (matches instance-side):
  freeform template materials are explicitly supported.
- No task/plan_task FK — template materials are always container-level.

### Related-name summary

- `Job.materials` → `Material` (task-attached and task-less both)
- `EstWorksheet.plan_materials` → `PlanMaterial` (plan_task-attached and task-less both)
- `Task.materials` → `Material` (task-attached subset; unchanged)
- `PlanTask.plan_materials` → `PlanMaterial` (plan_task-attached subset; unchanged)
- `WorkTemplate.materials` → `TemplateMaterial`

No name clashes: different target models.

### `AbstractWorkContainer`

Unchanged. No abstract-level materials accessor. The PlanMaterial/Material
split is genuine (only Material touches inventory), and consumer code naturally
dispatches by concrete type. This matches the existing Task/PlanTask pattern.

## Earmark & consumption semantics

### Single source of truth: `InventoryService._mutate_earmark`

All `Earmark` row writes go through one private helper:

```python
# apps/inventory/services.py
def _mutate_earmark(pli, job, delta):
    """Apply `delta` to the (pli, job) earmark. Upsert if the delta makes
    the earmark positive; delete if it hits zero. No-op if pli is not
    inventoried."""
```

Every Material lifecycle event — create, consume, restock, draw-more,
delete (via expense rejection or full-restock-on-manual-add) — calls this
helper explicitly with the appropriate signed delta. `_mutate_earmark` is
the only place in the codebase that reads or writes `Earmark` rows.

No Django signals. No `post_save` or `pre_delete` hook on Material. The
service layer is the complete boundary: reading the service method tells
you exactly when and by how much the earmark mutates. This matches the
repo's service-mediated-saves convention
(`docs/designs/2026-03-07-service-mediated-saves.md`).

### Callers of `_mutate_earmark`

All of these are service-method bodies; viewsets are thin wrappers.

| Caller | Signed delta | When |
|---|---|---|
| `MaterialService.create_on_job(...)` | `+= quantity` | Material creation, any origin (manual, template-generated, worksheet-copy, estimate-to-job, expense submit). |
| `MaterialService.consume(material)` | `-= effective_qty` | Consume op; plus `QOH -= effective_qty`, `qty_sold += effective_qty`, `state → consumed`. |
| `MaterialService.restock(material, n)` | `-= n` | Restock op; plus `restocked_qty += n`. If manual-add and reaches full, calls `MaterialService._delete_internal` — which has nothing left to mutate earmark-wise since `_mutate_earmark(-= n)` already handled it. |
| `MaterialService.draw_more(material, n)` | `+= n` | Draw-more op; plus `quantity += n`. Forbidden on expense-bound Materials. |
| `ExpenseService.reject(expense)` | `-= effective_qty` per Material | Internal rejection cascade; then `QOH -= quantity` via `reverse_ad_hoc_purchase`; then Material row deleted. |
| `InventoryService.receive_po_line_item` (existing) | `+= qty` | PO receive with job link. Unchanged today; migrates to calling `_mutate_earmark` so the new helper is the sole Earmark writer. |

### Why no hooks

- **No safety net required.** `Material.task` changes to `on_delete=SET_NULL`
  so Task deletion doesn't cascade-destroy Materials (which would orphan
  earmarks). `Material.job` stays `on_delete=CASCADE`, but `Earmark.job` is
  also CASCADE — Job deletion sweeps both cleanly.
- **No hidden behavior.** Reading the code tells you exactly when Earmark
  rows change. Fixtures, tests, and data migrations can call
  `Material.objects.create(...)` directly without triggering earmark
  mutations they didn't ask for.
- **Matches existing repo pattern.** Services mediate business logic; signals
  are avoided for state that's touched by explicit flows.

### Closing today's post-populate gap

Today, adding a `Material` to an existing Task after the initial
`create_earmarks_for_job` run leaves the earmark stale. Under the new
model, the only supported creation path is `MaterialService.create_on_job`,
which always calls `_mutate_earmark`. The gap closes as a direct consequence
of routing all creation through one place.

`InventoryService.create_earmarks_for_job` (the bulk aggregator that runs
at the end of `populate_from_template` etc.) stays as a defensive
re-aggregator for code paths outside this refactor's scope. Under the new
regime it should be a no-op in practice.

### User-facing ops

| Op | Inventoried Material effect | Non-inventoried Material effect |
|---|---|---|
| **Consume** | `QOH -= effective_qty`, `qty_sold += effective_qty`, earmark `-= effective_qty`, `state → consumed`. | `state → consumed`. No mechanical effect on inventory. |
| **Restock(n)** | earmark `-= n` (via `_mutate_earmark`), `restocked_qty += n`. If `restocked_qty == quantity` and Material is manual-add (not expense-bound): delete Material row internally (no further earmark mutation — `_mutate_earmark(-= n)` already ran). If expense-bound: Material stays, effective_qty is 0, invoice excludes it. | `restocked_qty += n`. Same manual-add-delete / expense-bound-survive rule. No earmark call since not inventoried. |
| **Draw more(n)** | `quantity += n`, earmark `+= n`. **Not available on expense-bound Materials** — the UI hides the button and the API endpoint returns 400. Extra demand is handled by the existing "Add material" button on the Job, which creates a separate manual-add Material drawing from existing stock. | `quantity += n`. Same "expense-bound not available" rule. |
| **Edit description** | description-only change. Allowed on all pending Materials. | Same. |

### Op validation

- Restock(n) requires `0 < n <= effective_qty`. Partial restock keeps state
  `pending`; full restock either deletes the row (manual-add) or leaves it
  pending with effective_qty = 0 (expense-bound).
- Draw more(n) requires `n > 0` and not expense-bound.
- Consume requires `state == 'pending'` and `effective_qty > 0`. No-op on
  materials that have nothing left to consume.
- Edit description is always allowed on pending materials.

### What's gone compared to earlier drafts

- **`waive` / `restore` / `'waived'` state** — subsumed by Restock.
- **`earmark_active` boolean** — unnecessary once consumed is terminal; the
  state + restocked_qty fields are enough.
- **User-facing Delete op** — replaced by full Restock on manual-add.
  Expense-bound Materials are never user-deletable; their lifecycle is
  owned by the Expense.
- **Edit quantity** — replaced by Restock (down) and Draw more (up).
  Prevents retroactive rewrite of purchase quantities on expense-bound
  Materials and gives both sides the same clear verbs.

### Uniformity note on `consumption_state`

`consumption_state` now applies to **all** inventoried Materials, not just
task-less ones. A task-attached inventoried Material starts in `pending`
and transitions to `consumed` when `MaterialService.consume(...)` runs at
task-start. This keeps the rule "consumed is terminal, forbidden to delete
or mutate" uniform regardless of whether the Material is task-attached.

The UI rule still differs: buttons (Consume, Restock, Draw more) appear
only on **task-less** Materials. Task-attached Materials are driven by
task lifecycle; they don't need explicit buttons.

### `work_complete` gate

Block `Job` → `work_complete` transition if any Material on the job is
task-less, inventoried, and has un-resolved commitment:

```
Material.objects.filter(
    job=job,
    task__isnull=True,
    price_list_item__is_inventoried=True,
    consumption_state='pending',
).annotate(eff=F('quantity') - F('restocked_qty')).filter(eff__gt=0).exists()
```

Fully-restocked expense-bound Materials (effective_qty = 0) do not block.
Task-attached Materials are gated by the task's own lifecycle, not this
check.

The existing `release_earmarks_for_job(job)` still runs on successful
transition and sweeps any remaining earmark balance.

## Expense flow

### Unified inventory rule

Inventory behavior is determined by `price_list_item.is_inventoried`
alone. No "path α vs path β" distinction; no `from_expense` flag.
Expenses, POs, and manual job-scope adds all route through the same
service-layer entry point (`MaterialService.create_on_job`), which calls
`_mutate_earmark` for the earmark side and defers QOH bumps to the caller
(via `receive_ad_hoc_purchase`) when appropriate.

### `ExpenseService.submit`

- Remove `find_or_create_materials_task` and its usage.
- The `new_material` branch calls
  `MaterialService.create_on_job(job=job, task=None, ...)` — which creates
  the Material row and calls `_mutate_earmark(pli, job, += quantity)` if
  inventoried.
- Then, if the resulting Material has an inventoried PLI, call
  `InventoryService.receive_ad_hoc_purchase(material)`: does **only**
  `QOH += material.quantity`. The earmark was already handled by
  `create_on_job`.
- Material is saved with `consumption_state='pending'` (inventoried, so the
  model default applies on create).

### Expense rejection / revert

Expense rejection is the **only** path that removes expense-bound Materials.
`ExpenseService.reject(expense)` (or equivalent revert op), all in one
transaction:

- Forbidden if any of the expense's Materials has `state == 'consumed'`.
  (Consumed is terminal; reversal requires manual inventory adjustment.)
- For each remaining (pending) Material:
  - Call `_mutate_earmark(pli, job, -= effective_qty)` to release the
    earmark contribution.
  - If PLI-inventoried: `QOH -= material.quantity` via
    `InventoryService.reverse_ad_hoc_purchase(material)`.
  - Delete the Material row internally (no hook; the service has already
    handled earmark and QOH).

No user-facing delete endpoint exists for expense-bound Materials. The
`Material.is_expense_bound` check fences them off from the delete API.

### Lifecycle outcomes

| Scenario | Start QOH | After `submit` | After Consume | After Restock(all) |
|---|---|---|---|---|
| Expense, inventoried PLI | X | X+qty (earmark += qty via `create_on_job`, QOH += qty via `receive_ad_hoc_purchase`) | X, qty_sold += qty | X+qty (excess in general inventory; material stays in pending with effective_qty=0) |
| Expense, non-inventoried PLI or freeform | n/a | n/a | n/a | n/a |
| Manual add, inventoried PLI | X | — (`create_on_job` upserts earmark, no QOH change) | X-qty, qty_sold += qty | X, earmark released, Material row deleted |
| Manual add, non-inventoried PLI or freeform | n/a | n/a | n/a | n/a |

The "overbuy" case (bought more than used) is handled by Restock: earmark
shrinks by the restock amount, QOH untouched, excess remains in general
inventory.

## Template population

### `WorkTemplate` gains a material-generation path

In addition to the existing `generate_tasks_for_worksheet(worksheet, quantity)`,
add a materials step that iterates `self.materials.all()` (the new reverse
relation from `TemplateMaterial.work_template`) and creates one
`PlanMaterial` per `TemplateMaterial` with:

- `est_worksheet=worksheet`
- `plan_task=None`
- copies `description`, `quantity`, `unit_cost`, `sell_price`, `price_list_item`,
  `accounting_category` from the template material.

If `quantity > 1` (multi-instance product), materials are replicated per
instance — matching how tasks replicate today.

### Job-direct population

Add a parallel `generate_materials_for_job(job, quantity)` on `WorkTemplate`
that calls `MaterialService.create_on_job(job=job, task=None, ...)` for each
template material. Every call routes through the service helper, so
earmarks upsert automatically via `_mutate_earmark`.
Called from `Job.populate_from_template`.

Since every call routes through `MaterialService.create_on_job`, earmarks
are upserted at creation time. The existing `create_earmarks_for_job`
aggregator call at the end of populate paths remains as a defensive
re-aggregation for code paths outside this refactor's scope; under the
new regime it should be a no-op in practice.

### Template editing

`TemplateMaterial` CRUD via the existing WorkTemplate admin surface
(wherever WorkTemplate is edited today). Standard templating semantics
apply: editing the template doesn't retroactively change previously-populated
worksheets or jobs.

## Invoice wizard & estimate generation

### Source pool

`InvoiceWizardService.get_source_pool(invoice)` appends one additional
group entry after the existing per-task loop:

```python
{
    'task_id': None,
    'name': 'Materials (no task)',
    'has_billable_atoms': <bool>,
    'atoms': [...],
}
```

Atoms come from task-less Materials on the job, filtered to exclude
materials with no billable balance (`effective_qty == 0`):

```python
Material.objects.filter(job=job, task__isnull=True)
    .annotate(eff=F('quantity') - F('restocked_qty'))
    .filter(eff__gt=0)
    .order_by('pk')
```

This single filter naturally hides fully-restocked expense-bound materials
(they have `effective_qty == 0`). Manual-add fully-restocked materials don't
exist as rows (they were deleted by the full Restock), so nothing to filter
there.

Claim tracking via `InvoiceLineItemSource` is unchanged; atoms of type
`SOURCE_MATERIAL` just happen to come from task-less materials now.
`_atom_computed_amount` uses `effective_qty * sell_price` so partial-
restocked materials bill correctly. `_atom_category`, `_atom_source_type`,
and `_resolve_atom` all dispatch by `isinstance(..., Material)` and
require no changes.

### Estimate generation

`EstimateGenerationService.generate_estimate_from_worksheet(worksheet)`
gains a step after the existing direct/bundled task processing: iterate
`worksheet.plan_materials.filter(plan_task__isnull=True)` and produce one
`EstimateLineItem` per entry via the existing `_create_material_line_item`
helper — same treatment as direct-task materials.

No bundling option for task-less PlanMaterials in this refactor
(out of scope).

## Copy paths

### `JobService.copy_from_worksheet`

After the existing `PlanTask → Task + PlanMaterials → Materials` loop,
add a second loop for `worksheet.plan_materials.filter(plan_task__isnull=True)`
that calls `MaterialService.create_on_job(job=job, task=None, ...)` for each
task-less PlanMaterial, copying fields the same way. `create_on_job`
handles earmark upsert via `_mutate_earmark`. The existing
`create_earmarks_for_job` trailing call stays as a defensive no-op.

**Similarly, the existing task-attached loop that creates `Material` rows
from `PlanMaterial` rows** moves from `Material.objects.create(...)` to
`MaterialService.create_on_job(job=job, task=new_task, ...)` so the same
earmark-upsert path applies uniformly.

### `Job.populate_from_estimate`

If the source estimate has line items pointing to `PlanMaterial` with
`plan_task=None`, those become task-less `Material` rows on the new job.
Concrete wiring confirmed during implementation.

### `Job.populate_from_template`

Calls the new `WorkTemplate.generate_materials_for_job(job, quantity)` after
the existing task-generation step.

## API surface

### New endpoints

All new material endpoints require `IsAuthenticated` only — no
`CanManageJobs` check. Material management is part of daily shop work
and should not be gated behind the manager-level permission atom.

- `POST /api/jobs/{id}/materials/` — create task-less Material on Job.
  Body: `{description, quantity, unit_cost, sell_price, price_list_item?, accounting_category?}`.
- `PATCH /api/materials/{id}/` — description-only edit. Other fields
  rejected to force use of Restock/Draw-more.
- `POST /api/materials/{id}/consume/` — execute Consume op.
- `POST /api/materials/{id}/restock/` — execute Restock(qty) op. Body:
  `{quantity}`.
- `POST /api/materials/{id}/draw-more/` — execute Draw-more(qty) op. Body:
  `{quantity}`. Returns 400 if Material `is_expense_bound` (UI never
  surfaces the button for expense-bound Materials; this is a defensive
  API check).

### No direct Material DELETE endpoint

User-facing Material deletion is always indirect:

- Manual-add Material: deleted as a side effect of Restock reaching full
  quantity. No standalone DELETE endpoint.
- Expense-bound Material: deleted only by Expense rejection. No user-facing
  path.

This keeps the lifecycle rules unambiguous at the API boundary.

### Modified endpoints

- `POST /api/est-worksheets/{id}/plan-materials/` — already exists for
  task-scoped PlanMaterial creation; accepts an optional `plan_task` field.
  When omitted, creates a worksheet-level PlanMaterial (`est_worksheet={id}`,
  `plan_task=None`).
- `GET /api/jobs/{id}/invoice-wizard/source-pool/` — response grows a
  `"Materials (no task)"` group appended to the tasks array.
- Template API: `GET/POST/PATCH/DELETE /api/work-templates/{id}/materials/`
  for `TemplateMaterial` CRUD. Permission: `CanManageConfig`.

## Data migration

Two migration files, one additive and one constraint-tightening, with a
RunPython data step between.

### Migration A (additive)

- Add `Material.job` (nullable initially).
- Add `Material.consumption_state` (default `'na'`).
- Add `Material.restocked_qty` (default 0).
- Add `PlanMaterial.est_worksheet` (nullable initially).
- Create `TemplateMaterial` table.

**RunPython step:**

1. Backfill `Material.job_id = Material.task.job_id` for every existing row.
2. Backfill `PlanMaterial.est_worksheet_id = PlanMaterial.plan_task.est_worksheet_id`.
3. For every existing inventoried Material with `task` set, set
   `consumption_state = 'pending'` if the task hasn't been started/completed
   (per task status), else `'consumed'`. Non-inventoried or freeform
   Materials stay at `'na'`.
4. Placeholder-task cleanup: for each Task where `name='Materials'` AND no
   Bleps AND every Material on it has `expenses.exists()`, null out
   `Material.task` for those materials and delete the Task. If any criterion
   fails, leave the Task alone; any stray fixture-side remnants will be
   tidied directly in the fixture files.

### Migration B (constraints)

- Alter `Material.job` to `NOT NULL`.
- Alter `PlanMaterial.est_worksheet` to `NOT NULL`.
- Alter `Material.task` to nullable.
- Alter `PlanMaterial.plan_task` to nullable.

### Fixtures

Affected fixture files (to be regenerated from a post-migration dev DB,
or hand-edited): `fixtures/unit_test_data.json`, `fixtures/workorder_from_estimate.json`,
`fixtures/mixed_lineitems.json`, `fixtures/invoicing_data.json`,
`fixtures/large_datasets/nealseed.json`, and any `nealseed*.json` in the repo
root. Final list confirmed during implementation.

Per `CLAUDE.md`: migrations are written by this refactor but applied by the
user. Do not run `python manage.py migrate`.

## Testing strategy

Following the repo's TDD convention — failing tests first, then implementation.

### New test files

- `tests/test_material_task_optional.py` — core refactor behavior. Covers:
  creating task-less Materials, invariant enforcement
  (`material.task.job_id == material.job_id` when task is set),
  `MaterialService.create_on_job` earmark upsert via `_mutate_earmark`,
  `ExpenseService.reject` cascade correctness, `Material.task` SET_NULL
  behavior on Task deletion.
- `tests/test_material_ops.py` — Consume, Restock (partial + full),
  Draw-more op semantics including the expense-bound-Draw-more forbiddance
  and the manual-add-full-Restock-deletes rule.
- `tests/test_loose_material_work_complete.py` — `work_complete` gate,
  effective_qty computation, fully-restocked materials not blocking.
- `tests/test_expense_material_inventory.py` — `receive_ad_hoc_purchase`
  and `reverse_ad_hoc_purchase`, end-to-end expense submit → Material
  → earmark → consume flow, overbuy Restock scenario (excess retained
  in QOH), non-inventoried PLI and freeform expense paths (no inventory
  effect), Expense rejection cascade (including the forbidden-on-consumed
  rule).
- `tests/test_template_materials.py` — `TemplateMaterial` CRUD,
  `generate_materials_for_worksheet`, `generate_materials_for_job`,
  multi-instance quantity replication, freeform-vs-PLI paths.

### Updated test files

- `tests/test_auto_earmark.py`, `tests/test_earmark_flow.py` — extended
  for `MaterialService.create_on_job` covering all creation paths
  (including the task-attached post-populate gap now being closed),
  task-less Materials, and the placeholder-task migration.
- `tests/test_invoice_wizard_service.py`, `tests/test_invoice_wizard_api.py`
  — new "Materials (no task)" group in source pool, effective_qty-based
  filter, partial-restocked billing.
- `tests/test_estimate_generation_materials.py` — task-less PlanMaterial
  becoming its own line item.
- `tests/test_api_expenses.py`, `tests/test_qbo_expense_push.py`,
  `tests/test_expense_service.py` — new material creation path without
  placeholder task; Draw-more forbidden on expense-bound; rejection
  cascade.
- Template generation tests (`test_new_templating.py`,
  `test_template_workflows.py`) — TemplateMaterial generation alongside
  TaskTemplate.

Per `CLAUDE.md`: no parallel test runs across sub-agents — one agent at
a time runs `manage.py test`.

## Manual browser testing

End-of-refactor checklist. Run against a live dev stack (`./dev.sh` or
equivalent) once all automated tests pass.

### Adding materials directly to a Job (no task)

- Freeform material on a Job: `Job detail → Add material`, leave task unset,
  save. Verify it appears in the job's material list and in the invoice
  wizard's "Materials (no task)" group.
- PLI-backed non-inventoried material: verify no earmark created, no QOH
  change, appears in invoice pool, no Consume/Restock/Draw-more buttons
  (non-inventoried → nothing to do).
- PLI-backed inventoried material: verify earmark upserted on `(pli, job)`,
  QOH unchanged, state `pending`, Consume / Restock / Draw more buttons
  present.

### Consume / Restock / Draw more

- Click **Consume**: `QOH -= effective_qty`, `qty_sold += effective_qty`,
  earmark shrinks, state → `consumed`, buttons hide, material still
  appears in invoice pool (billable).
- Click **Restock**, enter partial quantity: earmark shrinks by that
  amount, `restocked_qty` rises, QOH unchanged, still pending. Invoice
  pool shows the reduced billable amount.
- Click **Restock** with full remaining quantity on a manual-add material:
  earmark shrinks, Material row is deleted, disappears from the job.
- Click **Restock** with full remaining quantity on an expense-bound
  material: earmark shrinks, Material survives in pending state with
  `effective_qty = 0`, excluded from invoice pool, still visible in the
  job's material list (history/collapsed).
- Click **Draw more** on a manual-add material, enter qty: quantity rises,
  earmark rises. Same on a non-inventoried manual-add (quantity rises;
  no earmark).
- On an expense-bound material: verify **Draw more** button is not shown.
  Only Consume and Restock appear. Use the Job's regular "Add material"
  button to create a separate manual-add Material for any extra demand.

### `work_complete` gate

- Attempt `Mark work complete` while a task-less inventoried Material is
  `pending` with `effective_qty > 0` → blocked with a clear error listing
  the offending materials.
- **Last-task-completion path.** Set up a Job with one remaining in-progress
  task and a task-less inventoried Material still in `pending`. Complete
  the last task (which would normally advance the Job to `work_complete`
  automatically). Verify the auto-advance is blocked by the task-less
  material — the Job stays in its pre-complete state, the user sees a
  clear error, and the blocking material is listed. This covers both
  the user-initiated `Mark work complete` and the signal-driven
  last-task-done path.
- Resolve all (consume or restock-to-full each), retry → succeeds. Any
  remaining task-attached earmark balance released by
  `release_earmarks_for_job`.

### Expense-born materials (unified path)

- Submit an expense with an inventoried PLI: verify `QOH += qty`, earmark
  created (via `MaterialService.create_on_job` → `_mutate_earmark`),
  Material task-less with state `pending`.
- Consume it: QOH returns to original, `qty_sold += qty`. Net stock
  change across the full lifecycle = 0.
- Submit an expense, then Restock part of it: earmark shrinks by the
  restock amount, QOH stays bumped, invoice bills only the remainder.
- Submit an expense, then Restock all of it (overbuy case): earmark
  fully drained, QOH stays at +qty (excess in general stock), Material
  stays in pending with `effective_qty = 0`, excluded from invoice pool.
- Reject the expense → all its materials deleted, QOH reversed for the
  full purchase quantity on each, earmark contributions removed.
- Reject an expense where any material is consumed → blocked with clear
  error.
- Submit an expense with a non-inventoried PLI or freeform material: no
  QOH change, no earmark, no Consume/Restock/Draw-more buttons.

### Templates

- Edit a `WorkTemplate`, add a freeform `TemplateMaterial`, populate a
  worksheet from it. Verify a worksheet-level `PlanMaterial` appears on
  the worksheet (no QOH/earmark effect).
- Add a PLI-inventoried `TemplateMaterial`, populate a Job directly from
  the template. Verify a task-less Material is created on the Job,
  earmark upserted via `_mutate_earmark`, state `pending`.
- Populate with `quantity > 1` (multi-instance product). Verify N copies
  of each template material are generated.

### Estimate flow

- Worksheet with a task-less PlanMaterial → generate estimate. Verify the
  material appears as its own `EstimateLineItem`.
- Accept the estimate, populate a Job from it. Verify task-less Materials
  land on the Job, earmarks created correctly via `_mutate_earmark`.

### Invoice wizard

- Source pool shows a "Materials (no task)" group appended after tasks.
- Claiming task-less materials into an invoice line item works identically
  to task-attached materials.
- Partial-restocked materials show the reduced billable quantity
  (`effective_qty`).
- Fully-restocked (expense-bound) materials do not appear in the pool.

### Data migration sanity (post-migrate)

- Existing jobs: every `Material` row has `job` populated and the invariant
  holds (`material.task.job_id == material.job_id` when task is set).
- Every `PlanMaterial` has `est_worksheet` populated with the matching
  invariant on `plan_task`.
- Inventoried task-attached materials have `consumption_state` populated
  (pending or consumed as appropriate).
- `restocked_qty` defaults to 0 on all existing rows.
- Placeholder "Materials" tasks created by the old
  `find_or_create_materials_task` path are gone; their materials are now
  task-less on the same Job.
- Any fixture files that slipped through the cleanup heuristic are tidied
  manually.

## Deferred — revisit later

### Flagging pending task-less inventoried materials before work_complete

The `work_complete` gate blocks the transition when a task-less inventoried
Material is still in `pending` state with `effective_qty > 0`. Mechanically
this works: the user gets an error when they try to close the job.

But that's a late signal. The subtle situation is: **the user has to
remember these materials exist and resolve each one explicitly.** Nothing
on the Job detail page calls attention to "you have 3 task-less materials
sitting in pending state; decide Consume or Restock on each before
closing."

We don't yet have a concrete design for that surfacing. Candidates to
consider when we come back to this:

- A per-Job badge / count showing pending task-less materials, visible
  from the job list and the job detail header.
- An inline "Action needed" section on the Job detail page that groups
  pending task-less materials with one-click Consume / Restock controls.
- A block on the work_complete dialog that lists each pending material
  and forces a per-item decision before the transition proceeds (modal
  checklist).
- A dashboard / notification for the shop showing all jobs with
  unresolved task-less materials.

Open questions to settle:

- Is the gate enough, or is proactive surfacing required?
- If surfacing, which surface (job detail, job list, dashboard,
  work_complete modal, or multiple)?
- Does this extend to task-attached pending materials too (where the
  task lifecycle is the usual driver), or stay scoped to task-less?

Not in scope for this refactor. The underlying `consumption_state` +
`effective_qty` fields are the data that any future surfacing would read,
so the data model is ready when we get to the UX.

### Audit: QOH can go negative

The current inventory code appears to allow `PriceListItem.qty_on_hand`
to go negative — `consume_material` does `QOH = F('qty_on_hand') - quantity`
without a guard, and there's no `CheckConstraint` on the field. In reality
you can't consume stock you don't have; a negative QOH indicates a data
error (double-consume, missed PO receive, untracked manual usage, etc.)
rather than a real state.

To revisit when we come back to this:

- Identify every place QOH changes: `consume_material`,
  `complete_task_adjustment`, `manual_adjustment`, `receive_po_line_item`,
  the new `receive_ad_hoc_purchase` / `reverse_ad_hoc_purchase`.
- Decide the enforcement strategy: pre-op validation (raise if the
  resulting QOH would go negative), DB-level `CheckConstraint`, or both.
- Decide the break-glass path: `manual_adjustment` probably needs to
  remain able to set negative QOH for reconciliation-after-the-fact.
- Audit existing fixture and production data for any current negatives
  and resolve them before enforcement goes in.

Not in scope for this refactor — the materials-on-jobs work doesn't
introduce new QOH-drop paths (Consume still goes through the existing
`consume_material`). Flagging here so we don't forget.

### Surface earmark overcommitment (total earmarks > QOH)

The point of earmarks is to tell the shop "you've promised more stock
than you have on hand — order more." Today, nothing surfaces that
condition. `get_earmark_preview(job)` computes per-job shortfall at
populate time only, and there's no ongoing view of total earmarks
across jobs vs. QOH per PLI.

The data is trivial to compute:

```python
Earmark.objects.values('price_list_item').annotate(
    total_earmarked=Sum('quantity'),
).values(
    'price_list_item', 'total_earmarked',
)
# compare to PriceListItem.qty_on_hand
```

To revisit when we come back to this:

- Where should overcommitment surface? Candidates: inventory dashboard,
  per-PLI detail page, a shop-wide "attention needed" feed, a filterable
  alert on each affected Job, or multiple.
- Threshold: flag when `total_earmarked > qty_on_hand` (true shortfall)
  or also when `total_earmarked > qty_on_hand - safety_stock` (low-stock
  warning)? Do we introduce a safety-stock field on PLI?
- Refresh model: computed on demand (view query), materialized column on
  PLI updated via signal, or periodic task?
- Purchase-order tie-in: is there a one-click "create PO for the
  shortfall" action?

Not in scope for this refactor — the earmark-write plumbing this refactor
cleans up is what makes the data reliable enough to build on. Flagging
here so we come back to turn earmarks from bookkeeping into an actual
reorder signal.
