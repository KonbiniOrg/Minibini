# Materials, Inventory & Purchasing

This document is the consolidated reference for the inventory catalog
(`InventoryItem`), the materials lifecycle (`Material` / `PlanMaterial`,
earmarks, consumption state), the configurable units system, and purchasing
(POs, Bills, receiving, PO ↔ Material integration).

Sibling docs:

- `docs/designs/architecture-and-conventions.md` — service-layer pattern,
  `LineItemMixin`, `LineItemService.delete_line_item_with_renumber`,
  delete-confirm pattern.
- `docs/designs/jobs-tasks-and-worksheets.md` — `Job`, `Task`, `EstWorksheet`,
  `PlanTask`, `WorkTemplate`, populate-from-template / -estimate /
  -worksheet paths.
- `docs/designs/estimates-and-prices.md` — `RateScheme`, billable atoms
  (Materials are atoms), atom carry-over (`PlanMaterial → Material` on
  estimate accept), AccountingCategory pass-through.
- `docs/designs/invoicing-and-expenses.md` — `Invoice` /
  `InvoiceLineItem`, expense-bound Materials.
- `docs/designs/quickbooks-integration.md` — Bill QBO sync.
- `CLAUDE.md` — line-item delete rule, document numbering, `Configuration`
  key-value store, terminal-DB-write rules.

---

## 1. Overview

The data model splits into three layers:

| Layer | Models | Purpose |
|---|---|---|
| Inventory | `InventoryItem` (was `InventoryItem`) | Every physical item — catalog *types* (`is_catalog`) and transient *lots* — with prices, units, accounting category, and universal QOH tracking |
| Plan & instance | `MaterialBase` (abstract) → `PlanMaterial`, `Material`, `TemplateMaterialAssociation` | Materials live on Worksheets (`PlanMaterial`), Jobs (`Material`), or Templates (`TemplateMaterialAssociation`) |
| Procurement | `PurchaseOrder`, `PurchaseOrderLineItem`, `Bill`, `BillLineItem`, `BillPayment` | Order goods from vendors, receive them, record vendor invoices, record payments against bills |

A `Material` on a Job represents a *commitment*. Every item-backed Material
holds an `Earmark` against the linked InventoryItem from the moment the
Material is created (universal tracking). Earmarks are released by Consume (decrements QOH and
shrinks the earmark) or by Restock (shrinks the earmark, leaves QOH
alone).

PO line items integrate with this model via `Material.po_line_item`:
adding a job-attributed PO line creates (or claims) a Material on that
Job. Receiving the PO bumps QOH but doesn't touch the Material — the
plan and the physical stock are tracked separately.

Files:

- `apps/inventory/models.py`, `apps/inventory/services.py`
- `apps/purchasing/models.py`, `apps/purchasing/services.py`,
  `apps/purchasing/pdf.py`
- `apps/api/inventory/views.py`, `apps/api/inventory/serializers.py`
- `apps/api/purchasing/views.py`, `apps/api/purchasing/serializers.py`
- `apps/core/units.py`

---

## 2. InventoryItem (catalog items & transient lots)

`apps/inventory/models.py` — `InventoryItem`, `db_table='inventory_item'`.

> **2026-06 catalog-vs-lots reframe.** The model was `InventoryItem`
> (`db_table='price_list'`) and the flag was `is_inventoried`. The reframe
> renamed both and flipped the model: **quantity tracking is now universal** —
> every physical thing in the shop is tracked while it's here — and a catalog
> flag distinguishes *types* you reorder from one-time *lots*. A follow-up
> completed the rename so nothing says "price_list" anymore: the API route is now
> `/api/inventory/`, the FK field on Material/Earmark/line items is `inventory_item`,
> and the PK is `inventory_item_id` (all formerly `inventory_item*`). See
> `docs/plans/2026-06-14-inventory-catalog-vs-lots-spec.md`.

Every physical item flows through this one table — catalog items that estimates,
invoices, POs, bills, and Materials reference, and transient lots minted behind
freeform Materials.

### Fields

| Field | Type | Notes |
|---|---|---|
| `code` | `CharField(50)` unique | Primary user-visible identifier (free-text; no enforced supplier-code policy) |
| `description` | `TextField` | |
| `units` | `CharField(50)` default `'none'` | Validated against `units_list` Configuration |
| `purchase_price` | `Decimal(10,2)` | Vendor cost |
| `selling_price` | `Decimal(10,2)` | What we charge — defaulted at creation from `purchase_price × default_material_markup_percent` (see Pricing) |
| `qty_on_hand` | `Decimal(10,2)` | Physical stock (tracked for **all** items now) |
| `qty_sold` | `Decimal(10,2)` | Lifetime cumulative; bumped on Consume |
| `qty_wasted` | `Decimal(10,2)` | Bumped by negative `manual_adjustment` / write-off |
| `is_active` | bool | Soft-delete; pickers default to `?is_active=true` |
| `is_catalog` | bool, default **True** | Catalog *type* (reorderable, survives at QOH 0) vs transient *lot* |
| `accounting_category` | FK PROTECT | Required |

Derived:

- `qty_earmarked` — `Sum(earmark_set.quantity)`
- `qty_available` — `qty_on_hand - qty_earmarked`
- `is_finished_lot` — `not is_catalog and qty_on_hand == 0 and no earmarks`

### Catalog items vs transient lots

- **Catalog item** (`is_catalog=True`): a reorderable type. Survives at
  QOH 0, never auto-hidden, allocation uncapped. All pre-reframe rows migrated
  to catalog. Items created via the inventory/price-list UI default to catalog.
- **Transient lot** (`is_catalog=False`): one specific batch, minted behind a
  freeform goods-Material (or a freeform cost-item expense). Tracks QOH/earmarks
  like any item, but when it becomes a **finished lot** (QOH 0 + no earmarks) it
  is **hidden** from the active list and allocation pickers (`?include_finished=true`
  reveals it for merge/write-off). The earmark clause keeps a freshly-minted
  demand lot (QOH 0 + a live earmark) visible until consumed or released.

### Pricing — markup at creation

`InventoryService.create_item` derives `selling_price` from
`purchase_price × (1 + default_material_markup_percent/100)` **once at
creation**, only when no explicit non-zero sell is given. Config default `'0'`
→ sell == cost; editable in the SPA at **Settings → Catalog** (the
`MaterialMarkupSetting` component, `PATCH /api/settings/`). `update_item` never
re-applies it — the stored value is authoritative. Materials copy cost+sell from
the item at creation (only-if-unset), so they stay self-contained when a lot is
later hidden.

### Lifecycle: hide-on-spend, write-off, merge

- **Hide-on-spend.** Finished lots are hidden, **not deleted** — line items
  (`EstimateLineItem`/`InvoiceLineItem`/`PurchaseOrderLineItem`/`BillLineItem`)
  and `TemplateMaterialAssociation` reference items via **PROTECT**, so physical
  deletion would raise `ProtectedError`. There is no pruner; the filter is derived.
- **Write-off** (`InventoryService.write_off`, `POST …/{pk}/write-off/`): zeroes
  QOH, books the remainder to `qty_wasted` (recording the wastage history entry
  first), making the lot a finished/hidden lot.
- **Merge** (`InventoryService.merge`, `POST …/merge/`): the manual dedup tool —
  folds a discard item into a keep item (QOH + aggregates), repoints every
  reference, deletes the discard. Hard-blocks unit mismatch and catalog-as-discard.

### Cascade rules

Line items and `TemplateMaterialAssociation` reference the item with `PROTECT`
(preserves historical documents — and is why finished lots are hidden, not
deleted). `MaterialBase.inventory_item` and `Expense.stock_pli` use `SET_NULL`.
`can_be_deleted` still gates the (rare) hard delete:

```python
InventoryItem.can_be_deleted  # False if any line item or earmark references it
```

Catalog admins use the `is_active` soft-delete instead of hard deletion. Write
access to inventory items requires **either** `can_manage_financials` **or**
`can_manage_config`.

---

## 3. Material model

### MaterialBase abstract

`apps/inventory/models.py` — fields shared by `PlanMaterial`,
`Material`, and (via the related-but-separate `TemplateMaterialAssociation`)
the template side.

| Field | Type | Notes |
|---|---|---|
| `description` | `CharField(255)` blank default `''` | |
| `quantity` | `Decimal(10,2)` default 0 | |
| `units` | `CharField(50)` default `'none'` | |
| `unit_cost` | `Decimal(10,2)` default 0 | What we paid (or expect to pay) |
| `sell_price` | `Decimal(10,2)` default 0 | What we charge |
| `inventory_item` | FK SET_NULL nullable | Optional PLI link |
| `accounting_category` | FK PROTECT | Required |

`_populate_from_pli()` (called from `save()`) copies `description`,
`units`, `unit_cost`, `sell_price`, `accounting_category` from the
linked PLI when those fields are at their defaults. User overrides are
preserved.

`compute_amount(active_modifiers=None)` returns
`quantity * sell_price`. Uniform billable-atom interface (modifier arg
ignored — Materials don't carry modifiers).

### Material

`apps/inventory/models.py` — `Material`, `db_table='materials'`.

Concrete job-side material that participates in QOH/earmark flows.

| Field | Type | Notes |
|---|---|---|
| `job` | FK CASCADE | **Required**; Material always belongs to a Job |
| `task` | FK SET_NULL nullable | Optional Task attachment |
| `consumption_state` | choices `pending` / `consumed` | Default `pending` |
| `restocked_qty` | `Decimal(10,2)` default 0 | Tracks expense-bound restock for QOH reversal |
| `po_line_item` | FK SET_NULL `related_name='+'` | Optional PO line attribution |
| `source_plan_material` | OneToOne SET_NULL | Carry-over idempotency key |

`task` SET_NULL is deliberate: deleting a `Task` leaves Materials on
the Job as task-less rather than orphaning their earmarks. Job
deletion CASCADEs both `Material` and `Earmark` cleanly.

`po_line_item` uses `related_name='+'` (no reverse accessor); use
`PurchaseOrderLineItem.linked_material` (property that does
`Material.objects.filter(po_line_item=self).first()`) instead.
Deliberately *not* a `OneToOneField` — multiple Materials (and
therefore multiple Jobs) may eventually share a single PO line item
when one real-world purchase covers several jobs' needs. Uniqueness
is not enforced at the DB level so that future model can be allowed
without a migration.

`source_plan_material` is the carry-over key used by
`AtomCarryOverService` (see `docs/designs/estimates-and-prices.md`)
to dedupe `PlanMaterial → Material` on estimate accept.

#### Validation

`Material.clean()`:

- `task.job_id == job_id` when `task` is set
- `restocked_qty >= 0`

#### `unit_cost` provenance & expenses (cost-model redesign 2026-06-14)

`Material.unit_cost` comes from: PLI catalog (`_populate_from_pli` / carry-over),
a PO line (`resolve_or_create_for_line(unit_cost=li.price)`), or — for a
**cost-expense** — the user-entered `price` at creation (`create_on_job`,
`cost_source='document'`). A **freeform** (no-PLI) actual Material's cost is still
document-sourced only (no manual typing): `create_on_job`'s `cost_source` guard +
`MaterialSerializer.validate` + the material-modal disabling the Unit Cost field
when freeform. PLI materials and `PlanMaterial` estimates are unaffected.

**Expenses & materials** (driven by `ExpenseService`): expenses **never link an
existing material** — they only create their own (no recost, no clobber, no
division; the earlier link/unlink machinery was removed). Two modes:

- **Cost expense** → creates one consumable material at the entered `unit_cost`;
  `Expense.amount` is the job cost (cost-at-purchase). `Material.expenses` is the
  reverse of `Expense.material`.
- **Stock receipt** → an **inventoried** PLI purchase bumps QOH
  (`InventoryService.receive_stock`); **no material is created**. The cost is
  recognised at **consumption** (the job's own material), not at purchase — so
  `_spent` excludes stock-receipt expenses (`stock_pli` set). This is what lets a
  worker "buy the missing 3 sheets" as an expense without double-counting: the
  receipt tops up QOH, the existing material consumes once. See
  `docs/designs/invoicing-and-expenses.md` (Expense).

### PlanMaterial

`apps/inventory/models.py` — `PlanMaterial`, `db_table='plan_materials'`.

Worksheet-side mirror. No QOH or earmark side effects.

| Field | Type | Notes |
|---|---|---|
| `est_worksheet` | FK CASCADE | **Required** |
| `plan_task` | FK CASCADE nullable | Optional PlanTask attachment |

`PlanMaterial.clean()` enforces
`plan_task.est_worksheet_id == est_worksheet_id` when `plan_task` is
set.

### PLI-linked vs freeform: the immutability rule

A `Material` (or `PlanMaterial`) with a non-null `inventory_item` is a
faithful instance of that PLI. The labelling/categorization fields —
`description`, `units`, `accounting_category` — are populated from the
PLI at create time and locked thereafter. To change any of those, the
user deletes the row and re-adds it as a freeform Material.

**Why locked:** if a user could change `material.units` from `"sheets"`
to `"lbs"` on a PLI-linked-and-inventoried Material whose PLI is in
`"sheets"`, then `MaterialService.consume(material)` would do
`pli.qty_on_hand -= material.quantity` — decrementing sheets-of-stock
by a quantity-of-pounds. Inventory math only works when Material units
match PLI units.

**Pricing carve-out:** `unit_cost` and `sell_price` are editable in
place even on PLI-linked Materials (a real shop captures observed
vendor prices that differ from the catalog). The PATCH body accepts an
optional `propagate_to_pli` flag that, when true, also updates the
linked PLI's `purchase_price` / `selling_price` in the same
transaction. The propagate action is open to any authenticated user
(deliberate carve-out from `can_manage_financials`). See
`MaterialService.update_pricing` and `InventoryService.update_plan_material_pricing`.

**Invoice freeze on `sell_price` and `unconsume`.** Once a Material is on a
non-cancelled invoice (i.e. `InvoiceClaimService.is_invoiced('material', pk)`
returns True), two operations are hard-blocked by
`MaterialService._assert_not_invoiced`:

- **`sell_price` edits** — `MaterialService.update_pricing` raises
  `ValidationError` if `sell_price` is being changed while the material is
  claimed. (`unit_cost` edits are still allowed — cost is internal data,
  not the invoiced price.)
- **`unconsume`** — `MaterialService.unconsume` raises `ValidationError`
  before reversing consumption. Moving a material back to `pending` while it
  is on an invoice would change the invoiced amount and remove it from the
  wizard pool incorrectly.

`quantity` is already locked by the consumed state (all user ops require
`pending`), so no additional invoice-freeze is needed for quantity.

To edit a billed material's sell price or unconsume it, remove it from the
invoice first.

Enforcement lives in `apps/inventory/serializer_helpers.py`
(`enforce_pli_linked_allowlist`, `PLI_LINKED_PRICING_ALLOWED`,
`FREEFORM_ALLOWED`) and is invoked from `MaterialSerializer.update`.

### Consumption state machine

Every Material starts `pending` and transitions to `consumed` when work
begins. Consumption is one-way for users; the lone reversal is
`unconsume` (`consumed → pending`), used only by the blep-cancel undo
(see `jobs-tasks-and-worksheets.md` §4.5). The state machine is uniform
across PLI types and attachment mode.

| State | Restock | Draw more | Consume | Edit description |
|---|---|---|---|---|
| `pending`, task-attached | yes | yes (hidden on expense-bound) | — (driven by task lifecycle) | yes |
| `pending`, task-less | yes | yes (hidden on expense-bound) | yes | yes |
| `consumed` (any) | — | — | — | — |

Mechanical effects:

- **Consume** — inventoried: `qty_on_hand -= quantity`,
  `qty_sold += quantity`, earmark `-= quantity`, state → `consumed`.
  Non-inventoried: state flips as a marker; no QOH/earmark side effect.
- **Unconsume** — the exact inverse of Consume (inventoried:
  `qty_on_hand += quantity`, `qty_sold -= quantity`, earmark
  `+= quantity`; state → `pending`). Not a user op — called by
  `TaskLifecycleService.cancel_work` to undo an oops-Start, so a later
  re-Start can consume the materials again.
- **Restock(n)** — `quantity -= n`; if inventoried, earmark `-= n`. If
  `n == quantity` (full restock) and Material is manual-add (not
  expense-bound): the row is deleted server-side. If expense-bound:
  `restocked_qty += n`, row stays (with `quantity` possibly 0); excluded
  from invoice pool when `quantity == 0`.
- **Draw more(n)** — `quantity += n`; if inventoried, earmark `+= n`.
  Forbidden on expense-bound Materials.
- **Edit description** — description-only change (subject to the
  PLI-linked immutability rule).

Validation:

- `restock(n)` requires `0 < n <= quantity`
- `draw_more(n)` requires `n > 0` and not expense-bound
- `consume` requires `state == 'pending'` and `quantity > 0`
- `unconsume` requires `state == 'consumed'` (the lone consumed-state op)
- All *user* ops require `state == 'pending'`

### `is_expense_bound`

Computed: `self.expenses.exists()` (via reverse from `Expense.material`).
Expense-bound Materials are user-undeletable and cannot be drawn-more —
the only path that removes them is `ExpenseService.reject(expense)`.

### `work_complete` gate

`JobService._loose_pending_materials(job)` returns task-less pending
Materials with `quantity > 0`. Any match blocks the
`Job → work_complete` transition with a clear error. Gate is uniform
across inventoried and non-inventoried PLIs — task-less Materials
always represent an unresolved Consume-or-Restock decision.

The one exception is the **invoice-paid auto-completion path**
(`Invoice._maybe_complete_job`): it is unattended, so instead of being
blocked it calls `JobService.release_loose_materials(job)` first, which
restocks (releases) any loose pending Materials and records a
`HistoryEntry`. By the time the Job reaches `work_complete` there are no
loose materials, so the gate passes.

### Earmark release on terminal transitions

`InventoryService.release_earmarks_for_job(job)` deletes any remaining
`Earmark` rows for the job. It runs from `JobService.update_job` on entry
to `work_complete`, `cancelled`, or `rejected` — a dead or finished Job
holds no inventory reservation. Because every Job status change routes
through `update_job`, the release fires regardless of caller (the status
pill, the status-action endpoints, the estimate/invoice handlers).

---

## 4. MaterialService operations

`apps/inventory/services.py` — `MaterialService`. Sole entry point for
Material row creation and lifecycle ops. All earmark mutations route
through `InventoryService._mutate_earmark`.

| Operation | Effect |
|---|---|
| `create_on_job(*, job, task=None, ..., inventory_item=None, ...)` | Creates `Material`, calls `_mutate_earmark(pli, job, +quantity)` |
| `consume(material)` | State → `consumed`; if inventoried: `qty_on_hand -= qty`, `qty_sold += qty`, earmark `-= qty` |
| `restock(material, qty)` | `quantity -= qty`, earmark `-= qty`; manual-add full-restock deletes row; expense-bound bumps `restocked_qty` |
| `draw_more(material, qty)` | `quantity += qty`, earmark `+= qty`; rejects if expense-bound |
| `assign_task(material, task)` | Move Material to a different Task (or task=None); validates same job and non-terminal task |
| `update_pricing(material, *, unit_cost=None, sell_price=None, propagate_to_pli=False)` | Update prices; optional one-shot PLI propagation |
| `link_to_po_line(material, po_line)` | Set `po_line_item` FK; validates pending + unlinked |
| `unlink_from_po_line(material)` | Clear `po_line_item` FK |
| `sever(material, decision)` | `'keep'` clears FK; `'delete'` removes Material and backs out earmark. Raises if consumed |
| `resolve_or_create_for_line(po_line, *, job, ..., material_id=None)` | Three-step PO line ↔ Material resolver (see PO ↔ Material section) |

`MaterialService` is the only writer of Material rows beyond fixtures
and migrations. Direct `Material.objects.create(...)` is acceptable in
test setUp where no inventory side effect is wanted.

---

## 5. Earmarks

`apps/inventory/models.py` — `Earmark`, `db_table='earmarks'`.

| Field | Type | Notes |
|---|---|---|
| `inventory_item` | FK CASCADE | |
| `job` | FK CASCADE | |
| `quantity` | `Decimal(10,2)` | Aggregate per (PLI, Job) |
| `created_date` | auto_now_add | |

`unique_together = [('inventory_item', 'job')]` — one row per (PLI,
Job) pair. Per-PLI-per-Job aggregate, not per-Material.

### `_mutate_earmark` is the sole writer

```python
InventoryService._mutate_earmark(pli, job, delta)
```

- No-op only if `pli is None` (universal tracking — earmarks apply to every
  item-backed material, catalog or transient lot)
- Upsert if delta would make the earmark positive
- Delete the row if delta brings it to zero or below

Every Material lifecycle event that affects earmarks calls
`_mutate_earmark` with a signed delta. No Django signals; the service
layer is the complete boundary. Reading service code tells you exactly
when and by how much earmarks mutate.

### Callers of `_mutate_earmark`

| Caller | Delta | When |
|---|---|---|
| `MaterialService.create_on_job` | `+= quantity` | Material creation |
| `MaterialService.consume` | `-= quantity` | Consume op |
| `MaterialService.restock` | `-= n` | Restock op |
| `MaterialService.draw_more` | `+= n` | Draw-more op |
| `MaterialService.sever('delete')` | `-= quantity` | PO sever with delete decision |
| `ExpenseService.reject` | `-= quantity` per material | Expense rejection cascade |

PO receipt does **not** call `_mutate_earmark` — the earmark was
established at PO line creation time via `MaterialService.create_on_job`.
Receipt only bumps QOH.

### Earmark lifecycle on a Job

- **Created** when an item-backed Material is added to the Job (any
  task or job-scoped path: manual add, template population,
  worksheet-to-job copy, PO line creation, expense submit). Under universal
  tracking this is every goods-Material, not just inventoried ones.
- **Released** as Materials Consume/Restock through normal flows. The
  `Job → work_complete` transition runs
  `InventoryService.release_earmarks_for_job(job)` to sweep any
  remaining balance.
- **Aggregator (`create_earmarks_for_job`)** runs at the end of each
  populate path (`populate_from_template`, `populate_from_estimate`,
  `copy_from_worksheet`) as a defensive re-aggregation. Under the
  current regime where every Material write goes through
  `MaterialService.create_on_job`, this is effectively a no-op.

### Inventory history trail (InventoryHistory)

The old write-only `InventoryAdjustment` model (`inv_adjustments`, CASCADE) was
**retired** in the reframe and replaced by an **`InventoryHistory`** partition on
the `HistoryEntry` family (`apps/core/models.py`, `db_table='inventory_history'`,
routed by `object_type='inventoryitem'` in `apps/core/history.py`). Because
`HistoryEntry` references its target by loose `object_type`+`object_id` (no FK),
the trail **survives item deletion/hiding**; each entry snapshots the item's
`code`/`description` in `changes` so a hidden/deleted lot stays legible.

Every QOH event records an `action` entry via
`InventoryService._record_qoh_history` (qty change, resulting QOH, reason,
job/document, code/description snapshot, user):

- `manual_adjustment` / `write_off` (waste on negative)
- `receive_ad_hoc_purchase` / `reverse_ad_hoc_purchase`
- `PurchaseOrderReceivingService.receive_items` / `reverse_receipt`
- `merge` (two entries: discard "merged into KEEP", keep "merged from DISCARD")

Review lenses: per-item (the item's `InventoryHistory`), per-job (Material's
existing `@history` → JobHistory), and global/searchable.

---

## 6. PlanMaterial (worksheet mirror)

`apps/inventory/models.py` — `PlanMaterial`, `db_table='plan_materials'`.

Same `MaterialBase` field shape; lives on `EstWorksheet` (required) and
optionally on a `PlanTask`. No `consumption_state`, no `restocked_qty`,
no inventory side effects. The PLI-linked immutability rule applies in
the same form; `update_plan_material_pricing` mirrors
`MaterialService.update_pricing` including the `propagate_to_pli` flag.

PlanMaterial → Material carry-over is handled by the atom carry-over
service (pointer:
`docs/designs/estimates-and-prices.md`). The carry-over uses
`Material.source_plan_material` as the idempotency key — a second
acceptance of the same Estimate doesn't duplicate Materials.

---

## 7. Configurable units

`apps/core/units.py` — units validation, DRF field, Django form mixin.

Units are a controlled vocabulary stored as a JSON list in
`Configuration['units_list']`. Model fields stay `CharField(50)` storing
the unit string directly — no foreign keys, no joins, validated at the
form/serializer layer.

### Storage

```
Configuration key: 'units_list'
Configuration value: JSON array of strings
```

`'none'` is always first. List order = display order.

### Module API

| Symbol | Purpose |
|---|---|
| `DEFAULT_UNITS` | Hard-coded fallback list used when `units_list` config is missing |
| `get_units_list()` | Reads Configuration; falls back to `DEFAULT_UNITS` |
| `validate_unit(value)` | Raises `ValidationError` if value not in list |
| `units_choices()` | Django form `(value, label)` tuples |
| `UnitsField` | DRF `ChoiceField` subclass; refreshes choices from DB on each validation call |
| `UnitsFieldMixin` | ModelForm mixin that swaps the `units` field for a `Select` widget |

### Models with a `units` field

- `InventoryItem.units`
- `MaterialBase.units` (on `PlanMaterial`, `Material`)
- `BaseLineItem.units` (on every line item subclass)
- `Task.units`, `ServiceItem.units`

`MaterialBase._populate_from_pli` copies `units` from the linked PLI
when the value is `'none'` or empty.

### REST endpoint

`apps/api/templates_config/views.py` — `units_view`.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/settings/units/` | `IsAuthenticated` | Returns the units list |
| `PATCH` | `/api/settings/units/` | `can_manage_config` | Replace the list (must include `'none'` first; rejects duplicates) |

### Frontend

- `frontend/src/components/UnitsSelect.svelte` — dropdown component used
  in every form that accepts a unit
- `frontend/src/components/UnitsManager.svelte` — settings UI for
  adding/removing/reordering units

---

## 8. Templates: TemplateMaterialAssociation

`apps/inventory/models.py` — `TemplateMaterialAssociation`,
`db_table='template_material_assoc'`.

Pins a `InventoryItem` to a `WorkTemplate`, optionally pairing to a
`TemplateTaskAssociation` so the generated PlanMaterial/Material
attaches to the corresponding generated PlanTask/Task.

| Field | Type | Notes |
|---|---|---|
| `work_template` | FK CASCADE | |
| `inventory_item` | FK PROTECT | **Required** — no freeform template materials |
| `template_task_association` | FK SET_NULL nullable | Pairs to a template task association for instance pairing |
| `quantity` | `Decimal(10,2)` | Per-instance quantity at generation time |
| `sort_order` | int | |

Validation: `template_task_association.work_template` must match
`work_template`.

**Freeform template materials are explicitly disallowed.** Migration
`apps/inventory/migrations/0021_backfill_template_material_assoc.py`
errors out if any freeform `TemplateMaterial` rows exist (the prior
`TemplateMaterial` model was deleted in `0022_delete_templatematerial`).
PLI is the catalog of reusable materials; a separate template-material
catalog was redundant.

### Generation

`apps/estimates/models.py` — `WorkTemplate.generate_materials_for_worksheet`
and `WorkTemplate.generate_materials_for_job`. Both accept
`task_pairing` (a list of `(TemplateTaskAssociation, instance_index, …)`
tuples returned by `generate_tasks_for_*`) and an optional
`quantity=N` for multi-instance templates.

For each instance × association:

- If `assoc.template_task_association_id` matches a paired
  PlanTask/Task, the generated material attaches there.
- Otherwise, the generated material is task-less.

Pointer: `docs/designs/jobs-tasks-and-worksheets.md` covers the
`AbstractWorkContainer.populate_from_template` orchestration that
generates BOTH tasks AND materials and runs `create_earmarks_for_job`
afterward.

`Job.populate_from_template` (in `JobService.populate_from_template`)
calls `template.generate_tasks_for_job` then
`template.generate_materials_for_job(job, task_pairing=task_pairing)`,
then `InventoryService.create_earmarks_for_job(job)`.

---

## 9. PurchaseOrder

`apps/purchasing/models.py` — `PurchaseOrder`, `db_table='pos'`.

### Fields

| Field | Type | Notes |
|---|---|---|
| `po_number` | `CharField(50)` unique | Auto-generated via `NumberGenerationService` (see `CLAUDE.md`) |
| `business` | FK PROTECT | Required vendor |
| `contact` | FK PROTECT nullable | Optional; must belong to `business` if provided |
| `status` | choices | See state machine below |
| `created_date` | datetime | Immutable after first save |
| `requested_date` | datetime nullable | |
| `issued_date` | datetime nullable | Set on transition to `issued` |
| `received_date` | datetime nullable | Set on transition to `received_in_full` |
| `cancel_date` | datetime nullable | Set on transition to `cancelled` |

Date fields are protected after first save by `PurchaseOrder.clean()`.

**Derived billing properties** (computed from associated Bills at query time; never stored):

| Property | Type | Notes |
|---|---|---|
| `po_total` | Decimal | Sum of all `PurchaseOrderLineItem.total_amount` |
| `billed_total` | Decimal | Sum of `Bill.total` for non-cancelled Bills linked to this PO via `related_name='bills'` |
| `is_fully_billed` | bool | True when `po_total > 0` and `billed_total >= po_total` |

`PurchaseOrderSerializer` exposes all three. Double-billing is **surfaced not blocked**: when a PO's billed total covers the PO total, a warning banner appears on the Bill detail page and Bill create form — the system does not prevent a second Bill from being created. Only a draft PO is a hard refusal (Bills cannot be linked to a PO in `draft` status).

`Bill.purchase_order` FK carries `related_name='bills'`, enabling `po.bills.all()` and the `?purchase_order=<id>` filter on `GET /api/bills/`.

### Status machine

```
draft → issued → partly_received → received_in_full
          │              ▲                ▲
          │              └────────────────┘
          │
          └→ cancelled
```

Valid transitions (`PurchaseOrder.clean()`):

| From | Allowed |
|---|---|
| `draft` | `issued` |
| `issued` | `partly_received`, `received_in_full`, `cancelled` |
| `partly_received` | `received_in_full`, `issued` |
| `received_in_full` | `partly_received`, `issued` |
| `cancelled` | (terminal) |

Reverse transitions out of `received_in_full` and back from
`partly_received` to `issued` exist to support `reverse_receipt`.

Transitioning out of `draft` requires at least one line item.
`PurchaseOrder.delete()` enforces draft-only deletion (cancellation,
not deletion, is the path for issued POs).

### Line items

`PurchaseOrderLineItem`, `db_table='po_li'`. Inherits from
`BaseLineItem`.

| Field | Type | Notes |
|---|---|---|
| `purchase_order` | FK CASCADE | |
| `task` | FK PROTECT nullable | Reserved for a future "service PO" feature; not currently used by any flow |
| `qty_received` | `Decimal(10,2)` default 0 | Cumulative correct items accepted |
| `received_by` | FK User SET_NULL | Last receiver |
| `received_date` | datetime nullable | Last receipt timestamp |
| `receipt_note` | text | For problem cases |
| `qty_cancelled` | `Decimal(10,2)` default 0 | Outstanding cancelled quantity |

`linked_material` property:

```python
Material.objects.filter(po_line_item=self).first()
```

A line's job attribution is `line.linked_material.job` (or none).

### PO status auto-derivation

`PurchaseOrderReceivingService._update_po_status(po)`:

- An item is **settled** (no outstanding items to receive) when
  `qty_received + qty_cancelled >= qty`
- An item is **active** when `qty_received + qty_cancelled < qty`

Status rules:

- `received_in_full` — all items settled AND at least one has
  `qty_received > 0`
- `cancelled` — all items settled AND none have `qty_received > 0`;
  delegates to `cancel_po`
- `partly_received` — any `qty_received > 0` AND not all settled
- `issued` — nothing received, not all settled (e.g. after a reversal)

### Document numbering

Pointer: `CLAUDE.md` "Document Numbering (NumberGenerationService)" and
the `Configuration` keys `po_number_sequence` / `po_counter`.

---

## 10. PO operations

### `PurchaseOrderService` (`apps/purchasing/services.py`)

| Method | Purpose |
|---|---|
| `create_po(**kwargs)` | Create with auto-numbered `po_number` |
| `update_po(pk, **kwargs)` | Update header fields |
| `update_status(pk, new_status)` | Direct status change |
| `add_line_item(po_id, **kwargs)` | Add manual line; accepts transient `job`, `material_id` |
| `add_line_item_from_pli(po_id, pli_id, qty, job=None, material_id=None)` | Add line from PLI; same transient kwargs |
| `update_line_item(line_item_id, **kwargs)` | Draft-only field updates |
| `change_line_job(line_item_id, new_job_id, sever_decision=None)` | Reassign a line's job; runs sever then resolver |
| `reorder_line_items(po_id, item_ids)` | Bulk reorder via position list |
| `reorder_line_item(line_item_id, direction)` | Single-step reorder via `LineItemService` |
| `delete_line_item(line_item_id)` | Draft-only delete via `LineItemService.delete_line_item_with_renumber` |
| `cancel_po(pk, sever_decisions=None)` | Cancel issued PO; per-line sever decisions required for pending linked Materials |
| `delete_po(pk, sever_decisions=None)` | Delete draft PO; per-line sever decisions required for pending linked Materials |

`update_line_item` is gated to draft POs only. Line job changes go
through `change_line_job` regardless of PO status (allowed on draft,
issued, partly_received, received_in_full; rejected on cancelled).

### `PurchaseOrderReceivingService`

| Method | Purpose |
|---|---|
| `receive_items(po, items, user)` | Per-line receipt; bumps QOH for inventoried PLIs |
| `receive_all(po, user)` | Receive remaining qty on every line |
| `cancel_line_item(po, line_item_id, user, note='', sever_decision=None)` | Cancel a line's outstanding qty |
| `reverse_receipt(po, line_item_id, user, note='')` | Full receipt reversal on a single line |

#### Cancel rules

`cancel_line_item` requires the PO to be `issued` or `partly_received`
and the line to have outstanding quantity. Sets
`qty_cancelled = qty - qty_received` on that line ("stop expecting the
rest"). Partial cancellation is not supported — to keep some, issue a
new PO.

`cancel_po` (PO-level) sets `qty_cancelled = qty - qty_received` on
every line, transitions PO to `cancelled`, and applies sever decisions
for any line with a pending linked Material. Preconditions: PO is
`issued` (not `partly_received` — goods have already arrived).

#### Reverse receipt

`reverse_receipt` is a data-correction op. Resets `qty_received` to 0
(plus `qty_cancelled = 0`, `received_by = None`, `received_date = None`,
`receipt_note = ''`). For any item-backed line, decrements `qty_on_hand` by
the reversed quantity and records a negative `InventoryHistory` action entry.

If the line has a linked Material that is `consumed`, the reversal
raises `ValidationError("linked Material has been consumed. Restock the
Material first.")` — reversing into negative QOH is rejected at the
service layer. Pending linked Materials are untouched (the plan didn't
change just because the physical receipt didn't arrive).

#### Receipt overage

Receipt accepts overage on inventoried PLI lines (vendor shipped 12
when ordered 10 — `qty_on_hand += 12`, the extra 2 lands in general
inventory as `qty_available`). The Material's `quantity` and earmark
are unchanged — they are planned consumption. PO status auto-transitions
to `received_in_full` when `qty_received + qty_cancelled >= qty` on
every line.

Non-inventoried PLI lines and PLI-less lines: no QOH change on
receipt; receipt is recorded as bookkeeping only.

---

## 11. PO ↔ Material integration

`Material.po_line_item` is the only attribution mechanism — there is no
`PurchaseOrderLineItem.job` field.

### Three-step resolver

`MaterialService.resolve_or_create_for_line(po_line, *, job=None,
inventory_item=None, qty, unit_cost, description,
accounting_category=None, material_id=None)`:

1. **Explicit** — if `material_id` is given, link that Material
   (validates: same job if both supplied, pending, unlinked).
2. **Claim** — if `job` and `inventory_item` given, look for pending
   Materials on `(job, pli)` with no `po_line_item`. If exactly one
   matches, link it.
3. **Create** — otherwise call `MaterialService.create_on_job(...)` and
   link the new Material.

Runs at two moments:

- PO line creation with `job` or `material_id` (via `add_line_item` /
  `add_line_item_from_pli`).
- `change_line_job` (after severing the existing link).

On explicit and claim paths, the existing Material's qty / unit_cost /
description are NOT updated from the PO line — the Material is the
source of truth for planned consumption.

### Sever decisions

When a PO line's link to a Material breaks (line job change, line
cancellation, PO cancellation, draft PO deletion), the user picks:

- **Keep** — clear `Material.po_line_item`. Material stays pending on
  its job. Earmark unchanged.
- **Delete** — delete the Material; back out its earmark via
  `_mutate_earmark(-= quantity)`.

`MaterialService.sever(material, decision)` validates the Material is
pending; consumed Materials cannot be severed (the user must restock
first to undo consumption).

`PurchaseOrderService` methods that accept sever decisions:

- `change_line_job(..., sever_decision=...)` — single decision
- `cancel_po(..., sever_decisions={line_id: 'keep'|'delete'})` — per-line dict
- `delete_po(..., sever_decisions=...)` — same dict shape
- `cancel_line_item(..., sever_decision=...)` — single decision

Service-layer validation rejects requests that should provide a sever
decision but don't (`_validate_sever_decisions`).

### `effective_job_id` / `effective_job_number`

`POLineItemSerializer` exposes these via `linked_material.job`. No
column on the PO line itself.

### Materials are created at line-add time

PO line creation with job attribution creates (or claims) a Material
immediately. Earmark is established at line-add time, not at receipt.
Receiving the line bumps QOH only — no Material creation, no resolver
call, no Material.quantity updates.

### Cross-job traversal queries

```python
# All POs for a Job
PurchaseOrder.objects.filter(
    purchaseorderlineitem__in=Material.objects.filter(
        job=job, po_line_item__isnull=False,
    ).values_list('po_line_item_id', flat=True),
).distinct()

# All Jobs for a PO
Job.objects.filter(materials__po_line_item__purchase_order=po).distinct()
```

### PO ↔ Bill relationship

Each Bill carries a single optional `purchase_order` FK (`related_name='bills'`). A PO may have multiple Bills (e.g. partial vendor invoices or a corrected invoice), but each Bill references at most one PO. **A many-to-many model (one Bill spanning multiple POs) was considered and rejected** — the added complexity wasn't warranted for the shop's workflow; the single FK is retained.

The Bill create form includes a **PO picker** (vendor-filtered). When navigating to a Bill from the email→bill flow, the vendor-correlated PO is pre-selected. All Bills for a PO are queryable via `?purchase_order=<id>` on `GET /api/bills/`.

`BillSerializer` also returns a `po_billing` hint when a PO is linked:

```json
{
  "other_bills": [{"bill_id": …, "vendor_invoice_number": …, "status": …, "total": …}],
  "po_fully_billed": true
}
```

`other_bills` lists sibling non-cancelled Bills on the same PO; `po_fully_billed` flags when the billed total already covers the PO total. The frontend uses this to render an informational notice on the Bill detail page and a warning banner on the Bill form — double-billing is surfaced, not blocked.

---

## 12. PDF and email

`apps/purchasing/pdf.py` — `generate_purchase_order_pdf(po)`. Renders
`templates/purchasing/purchase_order_pdf.html` to PDF via WeasyPrint.
PDF contains PO number, vendor info, requested date, line items table
(description, qty, units, price, line total), grand total.

`PurchaseOrderEmailService.send_po(po, to, subject, body, cc=None,
bcc=None, extra_attachments=None, user=None)`:

- If PO is `draft`, validates at least one line item and transitions to
  `issued` (sets `issued_date`).
- Generates PDF and sends via `OutboundEmailService.send_tracked` with
  `associate_with={'purchase_order': po}` and `{po_number}.pdf`
  auto-attached. The persisted outbound `EmailRecord` is what makes
  the sent PO show up alongside the PO on the Email panel and
  participate in reply correlation when the vendor replies. (Inbound
  replies with `In-Reply-To` matching this outbound's Message-ID
  auto-link to the same PO — see `architecture-and-conventions.md`
  §7.11.) SMTP failures re-raise after the outbound EmailRecord has
  captured `last_send_error`.
- Writes a `HistoryEntry` recording the send.

`PurchaseOrderEmailService.get_email_defaults(po)` reads
`Configuration['po_email_subject_template']` and
`Configuration['po_email_body_template']` (falls back to
`DEFAULT_SUBJECT` / `DEFAULT_BODY`). Rendering goes through
`apps.core.email_templates.render_email_template` for safe handling
of unknown placeholders. The legacy `{po_number}` / `{vendor_name}`
keep working; the common set
(`{contact_fname}`, `{contact_lname}`, `{contact_business}`,
`{my_user_name}`, `{document_number}`) is also available. Defaults also include an `attachments_preview` list
so the send page can render the auto-attached PDF in the form.

API:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/purchase-orders/{id}/send-defaults/` | Pre-populated email fields + attachments_preview |
| `POST` | `/api/purchase-orders/{id}/send/` | Issue (if draft) and send. Accepts multipart `attachments` files in addition to `to`/`subject`/`body`/`cc`/`bcc`. Returns 400 on validation, 502 on SMTP failure (the outbound EmailRecord persists either way). |

SPA route: `/purchase-orders/:id/send` (`PurchaseOrderSendPage.svelte`).
The previous `SendPODialog` inline modal has been removed; the detail
page's Send button navigates to this route instead.

---

## 13. Bill

`apps/purchasing/models.py` — `Bill`, `db_table='bills'`, decorated with `@history(exclude=['bill_id'])`. Vendor invoice, optionally linked to a `PurchaseOrder`.

| Field | Type | Notes |
|---|---|---|
| `purchase_order` | FK PROTECT nullable (`related_name='bills'`) | PO must be in `issued` or later (not `draft`) |
| `business` | FK PROTECT | Required |
| `contact` | FK PROTECT nullable | If set, must belong to `business` |
| `vendor_invoice_number` | `CharField(50)` `blank` | Vendor's own invoice number; primary human-facing identifier (no Minibini-side auto-number). Optional — a draft Bill created from a PO has none until the real invoice arrives. |
| `status` | choices | **Derived** from payments via `recompute_payment_status()` for the payment statuses; see state machine |
| `due_date`, `received_date`, `paid_date`, `cancelled_date` | datetime nullable | `paid_date` managed by `recompute_payment_status()` |
| `qbo_id`, `qbo_payment_status` | char | QBO sync state |

**Computed properties** (no stored columns):

| Property | Notes |
|---|---|
| `total` | Sum of `BillLineItem.total_amount` |
| `amount_paid` | Sum of `BillPayment.amount` for all payments on this Bill |
| `balance` | `total − amount_paid` (exact) |

Status machine:

| From | Allowed |
|---|---|
| `draft` | `received` |
| `received` | `partly_paid`, `paid_in_full`, `cancelled` |
| `partly_paid` | `paid_in_full` |
| `paid_in_full` | `refunded` |
| `cancelled`, `refunded` | (terminal) |

**Status is payment-driven** for the payment statuses (`received`, `partly_paid`, `paid_in_full`). `Bill.recompute_payment_status()` re-derives the status from `amount_paid` vs `total` every time a `BillPayment` is recorded, updated, or deleted:

- `amount_paid == 0` → `received`
- `0 < amount_paid < total` → `partly_paid`
- `amount_paid >= total` → `paid_in_full`; sets `paid_date`; clears `paid_date` when moving back

Status can move **backward** (e.g. `paid_in_full` → `partly_paid` when a payment is deleted). A `_payment_driven` flag on the instance bypasses the forward-only transition guard in `clean()` during these recomputes. `recompute_payment_status()` is a no-op for `draft`, `cancelled`, and `refunded` bills.

Date fields are protected after first save (except `paid_date`, which is managed by the payment recompute). `Bill.delete()` is draft-only.

### Line items

`BillLineItem`, `db_table='bill_li'`. Inherits from `BaseLineItem`.
`task` FK PROTECT nullable. No receiving fields — Bills don't track
physical receipt (the linked PO does).

### `BillPayment`

`apps/purchasing/models.py` — `BillPayment`, `db_table='bill_payments'`. No `@history` decorator. Child of `Bill` (FK CASCADE, `bill.billpayment_set`). `Meta.ordering = ['payment_date']`.

**Payment-OUT fields** (entered in Minibini):

| Field | Type | Notes |
|---|---|---|
| `payment_id` | PK | Auto |
| `bill` | FK CASCADE | |
| `amount` | `Decimal(10,2)` | Must be > 0 |
| `payment_date` | datetime | |
| `payment_account_id` | `CharField(50)` blank | Which QBO bank/CC account paid (a `qbo_account_id` from `Configuration['qbo_payment_accounts']`); drives the QBO `BillPayment` PayType. Required while QBO is connected. **Replaces the old `method` field** — the human descriptor is derived from the account + reference. |
| `reference` | `CharField(100)` blank | Cheque number, transaction ID, etc.; becomes the QBO `DocNumber`. |
| `created_by` | FK User SET_NULL nullable (`related_name='recorded_bill_payments'`) | |
| `created_date` | datetime | auto |

**QBO sync fields** (from the `QBOSyncable` base — `qbo_id` is written by the push, `cleared_date` by the deferred clearance poller):

| Field | Type | Notes |
|---|---|---|
| `qbo_id` | `CharField(50)` blank | QBO `BillPayment` Id; written by `push_bill_payment` (was `qbo_payment_id`) |
| `qbo_sync_status` | choices | `pending` / `synced` / `sync_failed` (from `QBOSyncable`) |
| `qbo_sync_error` | text blank | Last push error message |
| `cleared_date` | datetime nullable | Set by `QBOBillPaymentPollingService` when QBO confirms clearance (deferred — poller stubbed) |

### `BillPaymentService`

Sole writer of `BillPayment` rows (`apps/purchasing/services.py`). Every method recomputes Bill status after the write.

| Method | Purpose |
|---|---|
| `record_payment(bill, *, amount, payment_date, method, reference='', user=None)` | Create a `BillPayment`; writes an `action` HistoryEntry on the Bill; triggers `_push_to_qbo` seam; bill must be `received` or `partly_paid` |
| `update_payment(payment_id, **out_fields)` | Edit payment-OUT fields (`amount`, `payment_date`, `method`, `reference`); blocked on `cancelled`/`refunded` bills |
| `delete_payment(payment_id)` | Delete payment and recompute Bill status (can move status backward) |

`_push_to_qbo(payment)` calls `QBOBillSyncService.push_bill_payment(payment)` after recording; exceptions are swallowed-and-logged (QBO hiccups must never block recording a payment).

### `BillService`

| Method | Purpose |
|---|---|
| `create_bill(**kwargs)` | Create a Bill |
| `create_bill_from_po(po_id, **kwargs)` | Create bill and copy PO line items |
| `update_bill(pk, **kwargs)` | Draft-only header update (business, contact, vendor_invoice_number, dates) |
| `update_status(pk, new_status)` | Direct status change (used by `receive` and `cancel` status actions) |
| `delete_bill(pk)` | Draft-only delete |
| `add_line_item`, `add_line_item_from_pli`, `update_line_item`, `reorder_line_items`, `reorder_line_item`, `delete_line_item` | Line item CRUD; all draft-only |

`BillService.update_bill` is the service entry point for PATCH on a Bill's header fields. `BillViewSet.perform_update` routes PATCH requests through it (draft-only; rejects updates on non-draft bills). All bill write actions require `CanManageFinancials`.

`BillViewSet.status_actions` registers: `receive` (draft → received), `cancel` (received → cancelled, requires reason). **`mark_paid` is removed** — the `paid_in_full` status is reached only via payments recorded through `BillPaymentService`.

**Payment endpoints** (all `CanManageFinancials`; DELETE returns 200 + JSON body):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/bills/{id}/payments/` | Record a payment via `BillPaymentService.record_payment` |
| `PATCH` | `/api/bills/{id}/payments/{pid}/` | Update payment-OUT fields |
| `DELETE` | `/api/bills/{id}/payments/{pid}/` | Delete payment; may roll status backward |

**`?purchase_order=<id>` filter** on `GET /api/bills/` returns bills linked to a given PO.

QBO sync: `POST /api/bills/{id}/send-to-qbo/` calls `QBOBillSyncService.push_bill` (endpoint exists; not yet wired in the UI). See `docs/designs/quickbooks-integration.md` for the push mechanics and the bill-payment push seam.

---

## 14. Line item API pattern

Every purchasing line-item viewset (PO and Bill) uses `LineItemMixin`
and `StatusTransitionMixin`. The PO viewset overrides
`line_items` (POST) and `line_item_detail` (PATCH/DELETE) to handle the
transient `job` / `material_id` / `sever_decision` parameters.

Pointer: `docs/designs/architecture-and-conventions.md` for the mixin
pattern and `LineItemService.delete_line_item_with_renumber` rule.
`CLAUDE.md` repeats the line-item-delete safety rule.

---

## 15. UI: Purchase order surfaces

Routes (`#/`-prefixed hash routes):

| Route | Component |
|---|---|
| `#/purchase-orders` | `routes/purchaseorders/PurchaseOrderListPage.svelte` → `components/purchaseorders/PurchaseOrderList.svelte` |
| `#/purchase-orders/new` | `routes/purchaseorders/PurchaseOrderFormPage.svelte` → `PurchaseOrderForm.svelte` |
| `#/purchase-orders/:id` | `routes/purchaseorders/PurchaseOrderDetailPage.svelte` → `PurchaseOrderDetail.svelte` |
| `#/purchase-orders/:id/edit` | `PurchaseOrderFormPage.svelte` (edit mode, draft only) |

The PO detail page (`PurchaseOrderDetail.svelte`) shows `billed_total`, `po_total`, and an `is_fully_billed` marker sourced from `PurchaseOrderSerializer`. It lists the PO's linked Bills (from the serializer's `bills` field — `[{bill_id, vendor_invoice_number, status}]`, prefetched on the viewset to avoid N+1) and, for users with `can_manage_financials` on a billable PO (`issued` / `partly_received` / `received_in_full`), a **Create Bill** link to `#/bills/new?po=<id>`. The PO **list** (`PurchaseOrderList.svelte`) shows a **Bill** column linking each PO's bill(s).

### Bill surfaces

Bill routes live under the **Financials** sidebar section (gated on `can_manage_financials`):

| Route | Component | Notes |
|---|---|---|
| `#/bills` | `routes/bills/BillListPage.svelte` | Bill list page |
| `#/bills/new` | `routes/bills/BillFormPage.svelte` (create mode) | Create a new Bill; accepts `?po=<id>` to pre-populate from a PO and `?email=<id>&vendor=<id>` from the email create-bill flow |
| `#/bills/:id` | `routes/bills/BillDetailPage.svelte` | Bill detail — interactive |
| `#/bills/:id/edit` | `routes/bills/BillFormPage.svelte` (edit mode, draft only) | Edit a draft Bill's header fields |

**Bill list page** (`BillListPage.svelte`):

- Columns: Vendor Inv#, Vendor, PO#, Status, Received, Due, Amount, Balance.
- Default view: status preset **Open** (includes `received` + `partly_paid`), sorted by due date ascending.
- Status presets: Open / Paid / Draft / Cancelled / Refunded / All.
- Filters: status preset, due-date range, and a `CustomerPicker` (`?business=` / `?contact=`) for filtering by vendor.
- **New Bill** button — visible to users with `can_manage_financials` only.
- **Balance column:** Exact balance (`total − amount_paid`) computed in summary mode via a Subquery on `BillPayment.amount` (fan-out-safe).

**Bill detail page** (`BillDetailPage.svelte`):

- Displays Bill header (vendor invoice#, vendor, PO link, status, dates), exact balance, and a payments section.
- On `draft` Bills, users with `can_manage_financials` can add, edit, delete, and reorder line items using `LineItemModal.svelte`.
- On `received` / `partly_paid` Bills, users with `can_manage_financials` can **Record Payment** (opens `RecordPaymentModal.svelte`; also offers a "Pay in full" shortcut that pre-fills the remaining balance) and edit or delete individual payments.
- Status actions: **Mark Received** (draft → received), **Cancel** (received → cancelled, requires a reason), **Delete** (draft only). **"Mark Paid in Full" is removed** — `paid_in_full` status is reached automatically when payments cover the total.
- When a PO is linked, an informational notice lists any sibling Bills on the same PO, and a warning banner appears if the PO is already fully billed.
- No Send-to-QBO button in the UI for this phase (the `send-to-qbo` endpoint exists but is not yet wired).

**Bill form page** (`BillFormPage.svelte`):

- Create mode (`/bills/new`): full header form (vendor business/contact, vendor invoice number, dates). Accepts `?po=<id>` to pre-fill vendor and copy PO line items via `BillService.create_bill_from_po`. Includes a **PO picker** (vendor-filtered via `PurchaseOrderPicker`). A warning banner appears when the selected PO is already fully billed.
- Edit mode (`/bills/:id/edit`): draft-only header edit; routes through `BillService.update_bill`.

**Serializers:**

- `BillSummarySerializer` — lightweight list serializer (summary mode); exposes `vendor_name`, `po_number`, `purchase_order`, `status`, dates, total, and exact balance (via annotations).
- `BillSerializer` — full detail/create/update serializer; includes all header fields, line items, nested read-only `payments`, `amount_paid`, exact `balance`, and `po_billing` hint.

**`?summary=true` opt-in (dual contract).** Like the invoice list, `BillViewSet` only uses `BillSummarySerializer` + the default-open status filter + presets/due-range/ordering in **summary mode** (the financials A/P list page calls `GET /api/bills/?summary=true`). **Without** `summary=true`, the list endpoint keeps its original contract — the full `BillSerializer` (with `line_items` and `payments`) and **all** statuses — preserving pre-existing consumers: the **Business detail** (`?business=`) and **Contact detail** (`?contact=`) bill panels and the **email-associate-bill** picker. (`?business=`/`?contact=`/`?purchase_order=` filtering applies in both modes.)

Components in `frontend/src/components/purchaseorders/`:

- `PurchaseOrderList.svelte` — list + status filter
- `PurchaseOrderForm.svelte` — header form (business, contact, requested
  date)
- `PurchaseOrderDetail.svelte` — header, line items table, status
  actions, history; per-line "Change Job" action; consolidated sever
  modal on cancel-PO / cancel-line / delete-PO / line-job-change
- `LineItemForm.svelte` — line entry; includes `JobPicker` (typeahead
  against active jobs, built on `SearchPicker`) and `InventoryItemPicker`
  (server-side `?search=`, also built on `SearchPicker`)
- `MaterialSeverDialog.svelte` — keep/delete decisions for affected
  Materials. Reused by all sever paths
- `ReceiveItemsForm.svelte` — line-by-line receipt entry
- `SendPODialog.svelte` — pre-populated email form ("Issue & Send" or
  "Resend")

The PO form supports two arrival query params:

- `?job=X` — pre-fills the Job picker on each new line
- `?material=Y` — pre-fills the first line-item entry from a Material
  (used by the "Order this" action on Job detail)

---

## 16. UI: Material edit

Material edit lives on the Job detail page (covered in
`docs/designs/jobs-tasks-and-worksheets.md`'s Job Detail section). Key
components:

- `frontend/src/components/MaterialModal.svelte` — Material create/edit;
  freeform vs PLI-linked branches
- `frontend/src/components/PlanMaterialModal.svelte` — same shape on
  the worksheet side

PLI-linked Material edit disables description / units /
accounting_category and the linked PLI itself. Pricing fields stay
editable; on save with changed prices, a modal asks "Update PLI with
the new values?" → translates to `propagate_to_pli=true|false` on the
PATCH. Restock / Draw-more / Consume buttons surface separately on
each Material row.

---

## 17. UI: Inventory and settings

Inventory-item CRUD + browse UI is the SPA `#/inventory` page
(`routes/inventory/InventoryListPage.svelte`), plus the markup config under
Settings → Catalog. Item pickers across the SPA use
`frontend/src/components/InventoryItemPicker.svelte` (renamed from
`InventoryItemPicker`), built on `SearchPicker`.

`InventoryItemPicker` queries server-side `?search=` (`code` and
`description`) as the user types. Accepts a `params` prop for additional
filters (e.g. `is_active=true`); offers a "None (freeform)" escape via the
`header` snippet.

`UnitsManager` (`frontend/src/components/UnitsManager.svelte`) is the
settings UI for editing the `units_list` Configuration value.

---

## 18. Unfinished work

- **Receive non-PLI PO line → "Create inventory item?" prompt.** Receipt
  on PLI-less lines records normally without QOH impact; the design
  calls for a follow-up "Create inventory item from this line?" modal
  per line.
- **Surface pending task-less Materials on Job page before
  work_complete.** The gate works mechanically but the user has to
  remember the Materials exist. No proactive surfacing yet.
- **Surface earmark overcommitment per PLI.** Total earmarks across all
  jobs vs QOH. Today only `get_earmark_preview(job)` exists at populate
  time; no ongoing dashboard view.
- **Simpler Material edit affordances.** Restock / Draw-more / Consume
  are separate buttons; the edit modal also exists for description /
  pricing. A single-surface design would be clearer.
- **`accounting_category` on freeform Material creation.** The Add
  Material form accepts a freeform Material without an
  `accounting_category` selection. The model field is required (PROTECT,
  no `null=True` after migration `0024`), but the form does not yet
  enforce it pre-submit. Worth a separate investigation.
- **`PurchaseOrderLineItem.task` reserved for future "service PO"
  feature.** Field exists on the model, untouched by current flows.
- **`accounting_category` required on `PurchaseOrderLineItem` and `BillLineItem`** — part of the project-wide line-item AC-NOT-NULL migration tracked in `architecture-and-conventions.md`.
