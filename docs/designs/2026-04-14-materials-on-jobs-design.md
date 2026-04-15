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
  (expense submit → QOH bump via a dedicated op; earmark via the uniform
  save hook).
- Per-save / pre-delete hooks on Material as the single source of earmark
  upsert/downsert.
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

- `task` → `ForeignKey(Task, on_delete=CASCADE, null=True, blank=True, related_name='materials')`
- **new** `job` → `ForeignKey(Job, on_delete=CASCADE, related_name='materials')`, not-null
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

### Single source of truth: save/delete hooks

The Material lifecycle drives all earmark upserts and downserts. Every code
path that brings a Material into existence — manual add, expense submit,
template populate, worksheet copy, estimate-to-job — uses the same save
hook for its earmark effect. Every code path that removes a Material uses
the same delete hook.

**Post-save hook on Material** (fires on creation only, `created=True`):

- If `price_list_item` is inventoried: upsert `(pli, job)` earmark
  `+= quantity`.
- Idempotent per Material (only fires on the create event).

**Pre-delete hook on Material** (fires when a Material row is about to be
deleted):

- If `price_list_item` is inventoried and `consumption_state == 'pending'`:
  earmark `-= effective_qty`. (If `effective_qty == 0` because fully
  restocked, the earmark has no contribution left; no-op.)
- If `consumption_state == 'consumed'`: delete is forbidden at the API
  layer and never reaches the hook. (Consumed is terminal; QOH/qty_sold
  have already moved. Recovery goes through `manual_adjustment`, not row
  deletion.)

These hooks are the sole earmark-upsert/downsert paths for Material-born
flows. No service method else touches earmarks directly during
Material-create or Material-delete.

This uniform handling closes today's latent gap where adding a `Material` to
an existing `task` after initial populate leaves the earmark stale.

### User-facing ops

| Op | Inventoried Material effect | Non-inventoried Material effect |
|---|---|---|
| **Consume** | `QOH -= effective_qty`, `qty_sold += effective_qty`, earmark `-= effective_qty`, `state → consumed`. | `state → consumed`. No mechanical effect on inventory. |
| **Restock(n)** | earmark `-= n`, `restocked_qty += n`. If `restocked_qty == quantity` and Material is manual-add (not expense-bound): delete Material row (pre-delete hook runs, but effective_qty is already 0 so no-op on earmark). If expense-bound: Material stays, effective_qty is 0, invoice excludes it. | `restocked_qty += n`. Same manual-add-delete / expense-bound-survive rule. |
| **Draw more(n)** | `quantity += n`, earmark `+= n`. **Forbidden on expense-bound Materials** — expense quantity is tied to the purchase record; extra demand creates a separate manual-add Material drawing from existing stock. | `quantity += n`. Same "expense-bound forbidden" rule. |
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
and transitions to `consumed` when `consume_material` runs at task-start.
This keeps the delete-hook rule (`forbid on consumed`, `shrink earmark on
pending`) uniform and removes the task-vs-no-task branch.

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
Expenses, POs, and manual job-scope adds all go through the same
earmark pipeline via the save hook.

### `ExpenseService.submit`

- Remove `find_or_create_materials_task` and its usage.
- The `new_material` branch creates `Material.objects.create(job=job, task=None, ...)` directly.
- If the resulting Material has an inventoried PLI, call
  `InventoryService.receive_ad_hoc_purchase(material)` (new op): `QOH += material.quantity`.
  **Nothing else.** The earmark is already upserted by the save hook.
- Material is saved with `consumption_state='pending'` (inventoried, so the
  save-hook default applies).

### Expense rejection / revert

Expense rejection is the **only** path that removes expense-bound Materials.
`ExpenseService.reject(expense)` (or equivalent revert op):

- Forbidden if any of the expense's Materials has `state == 'consumed'`.
  (Consumed is terminal; reversal requires manual inventory adjustment.)
- For each remaining (pending) Material:
  - If PLI-inventoried: `QOH -= material.quantity` via
    `InventoryService.reverse_ad_hoc_purchase(material)`.
  - Delete the Material row. The pre-delete hook shrinks the earmark by
    `effective_qty` (zero if fully restocked).

No user-facing delete endpoint exists for expense-bound Materials. The
`Material.is_expense_bound` check fences them off from the delete API.

### Lifecycle outcomes

| Scenario | Start QOH | After `submit` | After Consume | After Restock(all) |
|---|---|---|---|---|
| Expense, inventoried PLI | X | X+qty (earmark += qty) | X, qty_sold += qty | X+qty (excess in general inventory; material stays in pending with effective_qty=0) |
| Expense, non-inventoried PLI or freeform | n/a | n/a | n/a | n/a |
| Manual add, inventoried PLI | X | — (save hook creates earmark, no QOH change) | X-qty, qty_sold += qty | X, earmark released, Material row deleted |
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
that creates task-less `Material` rows (`job=job, task=None`) the same way.
Called from `Job.populate_from_template`.

The earmark save hook fires on each Material creation, so no separate
aggregator call is needed for template-generated Materials. The existing
`create_earmarks_for_job` call at the end of populate paths remains as a
defensive re-aggregation; under the new save-hook regime it should be a
no-op in practice.

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
that creates task-less `Material` rows on the job (`job=job, task=None`),
copying fields the same way. The save hook handles earmark upserts;
the existing `create_earmarks_for_job` trailing call stays as a defensive
no-op.

### `Job.populate_from_estimate`

If the source estimate has line items pointing to `PlanMaterial` with
`plan_task=None`, those become task-less `Material` rows on the new job.
Concrete wiring confirmed during implementation.

### `Job.populate_from_template`

Calls the new `WorkTemplate.generate_materials_for_job(job, quantity)` after
the existing task-generation step.

## API surface

### New endpoints

- `POST /api/jobs/{id}/materials/` — create task-less Material on Job.
  Body: `{description, quantity, unit_cost, sell_price, price_list_item?, accounting_category?}`.
  Permission: `CanManageJobs`.
- `PATCH /api/materials/{id}/` — description-only edit. Other fields
  rejected to force use of Restock/Draw-more. Permission: `CanManageJobs`.
- `POST /api/materials/{id}/consume/` — execute Consume op.
  Permission: `CanManageJobs`.
- `POST /api/materials/{id}/restock/` — execute Restock(qty) op. Body:
  `{quantity}`. Permission: `CanManageJobs`.
- `POST /api/materials/{id}/draw-more/` — execute Draw-more(qty) op. Body:
  `{quantity}`. Forbidden if Material `is_expense_bound`.
  Permission: `CanManageJobs`.

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
  (`material.task.job_id == material.job_id` when task is set), save-hook
  earmark upsert, pre-delete-hook earmark downsert.
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
  for the save/delete hooks (including the task-attached post-populate
  gap now being closed), task-less Materials, and the placeholder-task
  migration.
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
- Click **Draw more** on an expense-bound material: rejected with clear
  error ("expense quantity is fixed; add a separate material instead").

### `work_complete` gate

- Attempt `Mark work complete` while a task-less inventoried Material is
  `pending` with `effective_qty > 0` → blocked with a clear error listing
  the offending materials.
- Resolve all (consume or restock-to-full each), retry → succeeds. Any
  remaining task-attached earmark balance released by
  `release_earmarks_for_job`.

### Expense-born materials (unified path)

- Submit an expense with an inventoried PLI: verify `QOH += qty`, earmark
  created (by save hook), Material task-less with state `pending`.
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
  earmark upserted by save hook, state `pending`.
- Populate with `quantity > 1` (multi-instance product). Verify N copies
  of each template material are generated.

### Estimate flow

- Worksheet with a task-less PlanMaterial → generate estimate. Verify the
  material appears as its own `EstimateLineItem`.
- Accept the estimate, populate a Job from it. Verify task-less Materials
  land on the Job, earmarks created correctly via save hook.

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
