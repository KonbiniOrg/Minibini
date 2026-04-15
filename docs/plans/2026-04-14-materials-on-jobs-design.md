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
that are backed by inventoried `PriceListItem`s, extends those semantics to
task-less materials with an explicit consume/waive action, and unifies the
"expense-born inventoried material" path with the existing PO-receive path
(both become "stock in, earmark, normal consume").

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
- Add task-less Material consumption state machine and explicit
  consume/waive/restore actions.
- Unify expense-born inventoried materials into the earmark pipeline
  (expense submit → QOH bump + earmark, mirror of PO receive).
- Update invoice wizard source pool, estimate generation, and
  worksheet→job copy paths to handle task-less materials.
- Data migration: backfill `job`/`est_worksheet` FKs; clean up placeholder
  "Materials" tasks.

**Out of scope:**

- PO receive path changes. Untouched; folds naturally into the same Path-α
  earmark pipeline when an inventoried PLI is received with a job link.
- Retroactive PLI firm-up flow for existing freeform materials (already
  settled by the 2026-03-06 lifecycle doc amendment).
- Bundling task-less PlanMaterials on estimates. Each becomes its own
  direct line item; a future "bundle these worksheet-level materials" flag
  is out of scope.
- Expense UI error handling (flagged in memory as a pre-existing issue).

## Schema changes

### `Material` (`apps/inventory/models.py`)

- `task` → `ForeignKey(Task, on_delete=CASCADE, null=True, blank=True, related_name='materials')`
- **new** `job` → `ForeignKey(Job, on_delete=CASCADE, related_name='materials')`, not-null
- **new** `consumption_state` → `CharField(max_length=20, choices=CONSUMPTION_STATE_CHOICES, default='na')`
  - Choices: `na`, `pending`, `consumed`, `waived`
- `clean()` enforces: `self.task is None or self.task.job_id == self.job_id`
- `save()` auto-sets `consumption_state='pending'` at creation when
  `task is None and price_list_item_id is not None and price_list_item.is_inventoried`;
  otherwise `'na'`.

### `PlanMaterial` (`apps/inventory/models.py`)

- `plan_task` → `ForeignKey(PlanTask, on_delete=CASCADE, null=True, blank=True, related_name='plan_materials')`
- **new** `est_worksheet` → `ForeignKey(EstWorksheet, on_delete=CASCADE, related_name='plan_materials')`, not-null
- `clean()` enforces: `self.plan_task is None or self.plan_task.est_worksheet_id == self.est_worksheet_id`
- No `consumption_state` (worksheet side never touches inventory).

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

- All fields from `MaterialBase` are optional (matches instance-side): freeform
  template materials are explicitly supported. "Trust the user."
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

### Widened earmark aggregation

`InventoryService.create_earmarks_for_job(job)` filter changes from
`Material.objects.filter(task__job=job, ...)` to
`Material.objects.filter(job=job, ...)`. Because `Material.job` is required
and invariant-enforced, this single filter covers both task-attached and
task-less materials with no special-casing.

### Per-save earmark hook

Today, adding a `Material` to a job *after* the initial population leaves the
earmark stale until something re-runs the aggregator — an existing gap.

Add a post-save signal handler on `Material` that re-upserts the
`(pli, job)` earmark when the material is saved with an inventoried PLI
(and is not part of an already-received expense path — see "Expense flow"
below for why that carve-out matters). Runs uniformly for task-attached and
task-less materials.

### Consumption state machine for task-less materials

Task-less inventoried materials carry a `consumption_state` that moves
through:

```
                 (material.save, task is None, PLI inventoried)
                                     │
                                     ▼
                                 pending
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
                  consumed                            waived
                  (terminal)                    (can restore → pending)
```

- `pending` → `consumed` via `POST /api/materials/{id}/consume/`. Calls
  `InventoryService.consume_material(material)` (which already handles
  QOH down, qty_sold up, earmark shrink). One tweak to `consume_material`:
  read the job from `material.job` instead of `material.task.job`, so it
  works uniformly for both paths.
- `pending` → `waived` via `POST /api/materials/{id}/waive/`. New op
  `InventoryService.waive_material(material)`: shrinks the `(pli, job)`
  earmark by `material.quantity`, leaves QOH alone.
- `waived` → `pending` via `POST /api/materials/{id}/restore/`. New op
  `InventoryService.restore_material(material)`: re-upserts the earmark
  by `+= material.quantity`. No QOH change.
- `consumed` is terminal (undoing would require manual inventory adjustment,
  not a button).

Actions are idempotent no-ops when the material is already in the target
state; illegal transitions return 400 (e.g., consume on a `waived` material
requires restore first).

### Eligibility for the state machine

Only materials where `task is None AND price_list_item is not None AND
price_list_item.is_inventoried` have a non-`na` state. Freeform task-less
materials, non-inventoried PLI-linked task-less materials, and any
task-attached material remain `na` — no buttons, no gate.

### `work_complete` gate

Block `Job` → `work_complete` transition if any task-less inventoried
Material on the job has `consumption_state='pending'`. The existing
`release_earmarks_for_job(job)` still runs on successful transition and
sweeps remaining earmark balance.

## Expense flow

### Unified rule

Inventory behavior is determined by `price_list_item.is_inventoried`
alone. No "Path α vs Path β" distinction; no `from_expense` flag.
Expenses, POs, and manual job-scope adds all follow the same rule.

### `ExpenseService.submit`

- Remove `find_or_create_materials_task` and its usage.
- The `new_material` branch creates `Material.objects.create(job=job, task=None, ...)` directly.
- If the resulting Material has an inventoried PLI, call
  `InventoryService.receive_ad_hoc_purchase(material)` (new op, cousin of
  `receive_po_line_item`): `QOH += material.quantity`, upsert
  `(pli, job)` earmark `+= material.quantity`. The per-save earmark hook
  described above skips inventoried expense-born materials to avoid
  double-counting — the `receive_ad_hoc_purchase` call is the sole source
  of the QOH bump and earmark upsert for this path.
- Material is saved with `consumption_state='pending'` (task-less, inventoried
  → standard init rule). Same Consume/Waive/Restore buttons apply as for
  any other task-less inventoried material.

### Lifecycle outcomes

| Scenario | Start QOH | After `receive_ad_hoc_purchase` | After Consume | After Waive |
|---|---|---|---|---|
| Expense, inventoried PLI | X | X+qty (earmark+=qty) | X, qty_sold+=qty | X+qty (excess retained) |
| Expense, non-inventoried PLI or freeform | n/a | n/a | n/a | n/a |
| Manual add, inventoried PLI | X | — (no bump; earmark created via save hook) | X-qty, qty_sold+=qty | X (earmark released) |
| Manual add, non-inventoried PLI or freeform | n/a | n/a | n/a | n/a |

The "overbuy" case (bought more than used) is handled automatically by
Waive: the earmark shrinks, the excess QOH stays in general inventory.

### Reversal

If a Material is deleted — because the expense was edited to remove it,
rejected, or otherwise invalidated — `InventoryService.reverse_ad_hoc_purchase(material)`
undoes the QOH bump and earmark contribution. Applies only to materials
that had an associated Expense and an inventoried PLI (derivable from the
material at delete-time). Non-inventoried expense-born materials never
bumped anything, so no reversal needed.

Reversal on a material that has already been consumed or waived is
restricted to leave consistent bookkeeping. Edge cases (consumed-then-expense-rejected)
are enumerated in the test suite and expected to be rare; the simplest
workable rule is "un-linking an expense from a material doesn't trigger
reversal — only material deletion does."

## Template population

### `WorkTemplate` gains a material-generation path

In addition to the existing `generate_tasks_for_worksheet(worksheet, quantity)`,
add a materials step that iterates `self.materials.all()` (where `materials`
is the new reverse relation from `TemplateMaterial.work_template`) and
creates one `PlanMaterial` per `TemplateMaterial` with:

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

The earmark-creation hook in `create_earmarks_for_job` picks up these
materials via the widened filter; no separate wiring.

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

Atoms come from
`Material.objects.filter(job=job, task__isnull=True).exclude(consumption_state='waived').order_by('pk')`.
The `waived` exclusion is the key UX rule: waived materials are not billable
to the customer. `consumed`, `pending`, and `na` all remain in the pool
(a `pending` material is still billable in principle — you can draft an
invoice before the physical consumption happens, which is common workshop
practice).

Claim tracking via `InvoiceLineItemSource` is unchanged; atoms of type
`SOURCE_MATERIAL` just happen to come from task-less materials now.
`_atom_computed_amount`, `_atom_category`, `_atom_source_type`, and
`_resolve_atom` all dispatch by `isinstance(..., Material)` and require
no changes.

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
copying fields the same way. Then `create_earmarks_for_job` runs as today,
picking up both task-attached and task-less materials.

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
  Triggers `receive_ad_hoc_purchase` if PLI-inventoried and created through
  an expense context (otherwise the per-save hook handles the earmark).
  Permission: `CanManageJobs`.
- `PATCH /api/materials/{id}/` — update a Material. Quantity is locked on
  already-consumed materials (QOH ledger depends on it); other fields remain
  editable. Permission: `CanManageJobs`.
- `DELETE /api/materials/{id}/` — delete a Material. Runs
  `reverse_ad_hoc_purchase` if applicable. Permission: `CanManageJobs`.
- `POST /api/materials/{id}/consume/` — state `pending` → `consumed`.
  Permission: `CanManageJobs`.
- `POST /api/materials/{id}/waive/` — state `pending` → `waived`.
  Permission: `CanManageJobs`.
- `POST /api/materials/{id}/restore/` — state `waived` → `pending`.
  Permission: `CanManageJobs`.

Delete of task-less materials follows the repo's standard delete-confirmation
pattern (first DELETE returns impact counts, second with `?confirm=true`
executes).

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
- Add `PlanMaterial.est_worksheet` (nullable initially).
- Create `TemplateMaterial` table.

**RunPython step:**

1. Backfill `Material.job_id = Material.task.job_id` for every existing row.
2. Backfill `PlanMaterial.est_worksheet_id = PlanMaterial.plan_task.est_worksheet_id`.
3. Placeholder-task cleanup: for each Task where `name='Materials'` AND no
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
  (`material.task.job_id == material.job_id` when task is set), widened
  `create_earmarks_for_job` aggregation.
- `tests/test_loose_material_consumption.py` — state transitions
  (`pending → consumed`, `pending → waived`, `waived → pending`), illegal
  transitions, `work_complete` gate, per-save earmark hook, explicit
  consume/waive endpoints.
- `tests/test_expense_material_inventory.py` — `receive_ad_hoc_purchase`
  and `reverse_ad_hoc_purchase`, end-to-end expense submit → Material →
  earmark → consume flow, overbuy waive scenario (excess retained in QOH),
  non-inventoried PLI and freeform expense paths (no inventory effect).
- `tests/test_template_materials.py` — `TemplateMaterial` CRUD,
  `generate_materials_for_worksheet`, `generate_materials_for_job`,
  multi-instance quantity replication, freeform-vs-PLI paths.

### Updated test files

- `tests/test_auto_earmark.py`, `tests/test_earmark_flow.py` — extended
  for task-less Materials and the placeholder-task migration.
- `tests/test_invoice_wizard_service.py`, `tests/test_invoice_wizard_api.py`
  — new "Materials (no task)" group in source pool, `waived` exclusion.
- `tests/test_estimate_generation_materials.py` — task-less PlanMaterial
  becoming its own line item.
- `tests/test_api_expenses.py`, `tests/test_qbo_expense_push.py`,
  `tests/test_expense_service.py` — new material creation path without
  placeholder task.
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
  change, appears in invoice pool, no Consume/Waive buttons.
- PLI-backed inventoried material: verify earmark upserted on `(pli, job)`,
  QOH unchanged, state `pending`, Consume & Waive buttons present.

### Consumption actions

- Click **Consume**: QOH drops by qty, qty_sold rises by qty, earmark
  shrinks, state → `consumed`, buttons hide, material still appears in
  invoice pool.
- Click **Waive**: QOH unchanged, earmark shrinks, state → `waived`,
  material excluded from invoice pool. Restore button appears.
- Click **Restore**: earmark re-upserted, state → `pending`, material
  reappears in invoice pool.

### `work_complete` gate

- Attempt `Mark work complete` while a task-less inventoried Material is
  `pending` → blocked with a clear error listing the offending materials.
- Resolve all (consume or waive each), retry → succeeds. Any remaining
  task-attached earmark balance released by `release_earmarks_for_job`.

### Expense-born materials (unified path)

- Submit an expense with an inventoried PLI: verify `QOH += qty`, earmark
  created, Material task-less with state `pending`.
- Consume it: QOH returns to original, qty_sold rises by qty. Net stock
  change across the full lifecycle = 0.
- Waive it (overbuy case): QOH stays at original + qty, earmark shrinks.
  Excess lives in general stock.
- Reject or delete the expense → linked Material deleted, QOH reversal
  applied, earmark cleared.
- Submit an expense with a non-inventoried PLI or freeform material: no
  QOH change, no earmark, no Consume/Waive buttons.

### Templates

- Edit a `WorkTemplate`, add a freeform `TemplateMaterial`, populate a
  worksheet from it. Verify a worksheet-level `PlanMaterial` appears on
  the worksheet (no QOH/earmark effect).
- Add a PLI-inventoried `TemplateMaterial`, populate a Job directly from
  the template. Verify a task-less Material is created on the Job,
  earmark upserted, state `pending`.
- Populate with `quantity > 1` (multi-instance product). Verify N copies
  of each template material are generated.

### Estimate flow

- Worksheet with a task-less PlanMaterial → generate estimate. Verify the
  material appears as its own `EstimateLineItem`.
- Accept the estimate, populate a Job from it. Verify task-less Materials
  land on the Job, earmarks created correctly.

### Invoice wizard

- Source pool shows a "Materials (no task)" group appended after tasks.
- Claiming task-less materials into an invoice line item works identically
  to task-attached materials.
- Waived materials do not appear in the pool; restoring a waived material
  makes it reappear.

### Data migration sanity (post-migrate)

- Existing jobs: every `Material` row has `job` populated and the invariant
  holds (`material.task.job_id == material.job_id` when task is set).
- Every `PlanMaterial` has `est_worksheet` populated with the matching
  invariant on `plan_task`.
- Placeholder "Materials" tasks created by the old
  `find_or_create_materials_task` path are gone; their materials are now
  task-less on the same Job.
- Any fixture files that slipped through the cleanup heuristic are tidied
  manually.
