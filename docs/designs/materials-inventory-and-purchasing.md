# Materials, Inventory & Purchasing

This document is the consolidated reference for the inventory catalog
(`PriceListItem`), the materials lifecycle (`Material` / `PlanMaterial`,
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
- `docs/designs/invoicing-and-expenses.md` (forthcoming) — `Invoice` /
  `InvoiceLineItem`, `Bill` payment lifecycle, expense-bound Materials.
- `docs/designs/quickbooks-integration.md` (forthcoming) — Bill QBO sync.
- `CLAUDE.md` — line-item delete rule, document numbering, `Configuration`
  key-value store, terminal-DB-write rules.

---

## 1. Overview

The data model splits into three layers:

| Layer | Models | Purpose |
|---|---|---|
| Catalog | `PriceListItem` | Reusable items with prices, units, accounting category, optional QOH tracking |
| Plan & instance | `MaterialBase` (abstract) → `PlanMaterial`, `Material`, `TemplateMaterialAssociation` | Materials live on Worksheets (`PlanMaterial`), Jobs (`Material`), or Templates (`TemplateMaterialAssociation`) |
| Procurement | `PurchaseOrder`, `PurchaseOrderLineItem`, `Bill`, `BillLineItem` | Order goods from vendors, receive them, record vendor invoices |

A `Material` on a Job represents a *commitment*. Inventoried Materials
hold an `Earmark` against the linked PriceListItem from the moment the
Material is created. Earmarks are released by Consume (decrements QOH and
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

## 2. PriceListItem (catalog)

`apps/inventory/models.py` — `PriceListItem`, `db_table='price_list'`.

Catalog of reusable items that can flow into estimates, invoices, POs,
bills, and Materials.

### Fields

| Field | Type | Notes |
|---|---|---|
| `code` | `CharField(50)` unique | Primary user-visible identifier |
| `description` | `TextField` | |
| `units` | `CharField(50)` default `'none'` | Validated against `units_list` Configuration |
| `purchase_price` | `Decimal(10,2)` | Vendor cost |
| `selling_price` | `Decimal(10,2)` | What we charge |
| `qty_on_hand` | `Decimal(10,2)` | Physical stock; only meaningful when `is_inventoried` |
| `qty_sold` | `Decimal(10,2)` | Lifetime cumulative; bumped on Consume |
| `qty_wasted` | `Decimal(10,2)` | Bumped by negative `manual_adjustment` |
| `is_active` | bool | Soft-delete; pickers default to `?is_active=true` |
| `is_inventoried` | bool | Drives QOH/earmark behavior |
| `accounting_category` | FK PROTECT | Required |

Derived:

- `qty_earmarked` — `Sum(earmark_set.quantity)`
- `qty_available` — `qty_on_hand - qty_earmarked`

### Inventoried vs non-inventoried

- **Inventoried** (`is_inventoried=True`): every unit tracked through
  QOH, earmarks, Consume/Restock bookkeeping. Receiving a PO line bumps
  QOH; Consume decrements it; Restock releases the earmark only.
- **Non-inventoried** (`is_inventoried=False`): no QOH tracking, no
  earmarks. Materials still exist for billing and AC routing, but the
  state machine's QOH side effects are no-ops.

### Cascade rules

Line items reference `PriceListItem` with `PROTECT` (preserves
historical documents). `MaterialBase.price_list_item` uses `SET_NULL`
so a PLI deletion doesn't destroy in-progress Materials, but in
practice deletion is gated by `can_be_deleted`:

```python
PriceListItem.can_be_deleted  # False if any line item, earmark, or adjustment exists
```

Catalog admins use the `is_active` soft-delete instead of hard
deletion.

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
| `price_list_item` | FK SET_NULL nullable | Optional PLI link |
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

A `Material` (or `PlanMaterial`) with a non-null `price_list_item` is a
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
| `create_on_job(*, job, task=None, ..., price_list_item=None, ...)` | Creates `Material`, calls `_mutate_earmark(pli, job, +quantity)` |
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
| `price_list_item` | FK CASCADE | |
| `job` | FK CASCADE | |
| `quantity` | `Decimal(10,2)` | Aggregate per (PLI, Job) |
| `created_date` | auto_now_add | |

`unique_together = [('price_list_item', 'job')]` — one row per (PLI,
Job) pair. Per-PLI-per-Job aggregate, not per-Material.

### `_mutate_earmark` is the sole writer

```python
InventoryService._mutate_earmark(pli, job, delta)
```

- No-op if `pli is None` or `not pli.is_inventoried`
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

- **Created** when an inventoried Material is added to the Job (any
  task or job-scoped path: manual add, template population,
  worksheet-to-job copy, PO line creation, expense submit).
- **Released** as Materials Consume/Restock through normal flows. The
  `Job → work_complete` transition runs
  `InventoryService.release_earmarks_for_job(job)` to sweep any
  remaining balance.
- **Aggregator (`create_earmarks_for_job`)** runs at the end of each
  populate path (`populate_from_template`, `populate_from_estimate`,
  `copy_from_worksheet`) as a defensive re-aggregation. Under the
  current regime where every Material write goes through
  `MaterialService.create_on_job`, this is effectively a no-op.

### InventoryAdjustment trail

`apps/inventory/models.py` — `InventoryAdjustment`,
`db_table='inv_adjustments'`. Audit row written by:

- `InventoryService.manual_adjustment` (positive or negative; tracks
  waste on negative)
- `PurchaseOrderReceivingService.receive_items` (bumps QOH for
  inventoried PO lines)
- `PurchaseOrderReceivingService.reverse_receipt` (decrements QOH;
  negative adjustment row)

`receive_ad_hoc_purchase` and `reverse_ad_hoc_purchase` (the
expense-bound paths) currently do *not* write `InventoryAdjustment`
rows.

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

- `PriceListItem.units`
- `MaterialBase.units` (on `PlanMaterial`, `Material`)
- `BaseLineItem.units` (on every line item subclass)
- `Task.units`, `TaskTemplate.units`

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

Pins a `PriceListItem` to a `WorkTemplate`, optionally pairing to a
`TemplateTaskAssociation` so the generated PlanMaterial/Material
attaches to the corresponding generated PlanTask/Task.

| Field | Type | Notes |
|---|---|---|
| `work_template` | FK CASCADE | |
| `price_list_item` | FK PROTECT | **Required** — no freeform template materials |
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
`receipt_note = ''`). For inventoried PLIs, decrements `qty_on_hand` by
the reversed quantity and writes a negative `InventoryAdjustment`.

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
price_list_item=None, qty, unit_cost, description,
accounting_category=None, material_id=None)`:

1. **Explicit** — if `material_id` is given, link that Material
   (validates: same job if both supplied, pending, unlinked).
2. **Claim** — if `job` and `price_list_item` given, look for pending
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
`{our_user_name}`, `{our_business_name}`, `{document_number}`) is
also available. Defaults also include an `attachments_preview` list
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

`apps/purchasing/models.py` — `Bill`, `db_table='bills'`. Vendor
invoice, optionally linked to a `PurchaseOrder`.

| Field | Type | Notes |
|---|---|---|
| `purchase_order` | FK PROTECT nullable | PO must be in `issued` or later (not `draft`) |
| `business` | FK PROTECT | Required |
| `contact` | FK PROTECT nullable | If set, must belong to `business` |
| `vendor_invoice_number` | `CharField(50)` | Vendor's own invoice number; primary human-facing identifier for the Bill (no Minibini-side auto-number) |
| `status` | choices | See state machine |
| `due_date`, `received_date`, `paid_date`, `cancelled_date` | datetime nullable | |
| `qbo_id`, `qbo_payment_status` | char | QBO sync state |

Status machine:

| From | Allowed |
|---|---|
| `draft` | `received` |
| `received` | `partly_paid`, `paid_in_full`, `cancelled` |
| `partly_paid` | `paid_in_full` |
| `paid_in_full` | `refunded` |
| `cancelled`, `refunded` | (terminal) |

Date fields are protected after first save. `Bill.delete()` is
draft-only.

### Line items

`BillLineItem`, `db_table='bill_li'`. Inherits from `BaseLineItem`.
`task` FK PROTECT nullable. No receiving fields — Bills don't track
physical receipt (the linked PO does).

### `BillService`

| Method | Purpose |
|---|---|
| `create_bill(**kwargs)` | Create a Bill |
| `create_bill_from_po(po_id, **kwargs)` | Create bill and copy PO line items |
| `update_status(pk, new_status)` | Status change |
| `delete_bill(pk)` | Draft-only delete |
| `add_line_item`, `add_line_item_from_pli`, `update_line_item`, `reorder_line_items`, `reorder_line_item`, `delete_line_item` | Line item CRUD; all draft-only |

QBO sync: pointer to `docs/designs/quickbooks-integration.md`
(forthcoming). The viewset action
`POST /api/bills/{id}/send-to-qbo/` calls `QBOBillSyncService.push_bill`.

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

Components in `frontend/src/components/purchaseorders/`:

- `PurchaseOrderList.svelte` — list + status filter
- `PurchaseOrderForm.svelte` — header form (business, contact, requested
  date)
- `PurchaseOrderDetail.svelte` — header, line items table, status
  actions, history; per-line "Change Job" action; consolidated sever
  modal on cancel-PO / cancel-line / delete-PO / line-job-change
- `LineItemForm.svelte` — line entry; includes `JobPicker` (typeahead
  against active jobs) and `PriceListItemPicker`
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

PriceListItem CRUD UI is part of the settings surface
(`routes/SettingsPage.svelte`). PLI pickers across the SPA use
`frontend/src/components/PriceListItemPicker.svelte` (catalog) and
`frontend/src/components/CatalogPicker.svelte` (when a price-list view
is needed in-line).

`PriceListItemPicker` fetches the full active catalog
(`?page_size=9999&is_active=true`) and filters client-side per
keystroke. Server-side `?search=` filtering is unfinished work for when
the catalog grows.

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
- **Server-side `?search=` filtering on `PriceListItemPicker`** once the
  catalog grows.
- **`accounting_category` required on `PurchaseOrderLineItem` and `BillLineItem`** — part of the project-wide line-item AC-NOT-NULL migration tracked in `architecture-and-conventions.md`.
- **Legacy TaskTemplate Django HTML forms** (`add_task_template_standalone.html`,
  `task_template_edit.html`) still bind to fields removed by the
  RateScheme refactor (`form.units`, `form.rate`,
  `form.accounting_category`). Display-only templates were patched;
  form-driven templates need a RateScheme picker rewrite.
