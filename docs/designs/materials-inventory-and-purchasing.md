# Materials, Inventory & Purchasing

This document is the consolidated reference for the inventory catalog
(`InventoryItem`), the materials lifecycle (`Material`, earmarks,
consumption state), the configurable units system, and purchasing
(POs, receiving, PO ↔ Material integration). Bills (vendor invoices)
were retired to QBO 2026-07-23 — see §13.

> **Job-owns-atoms model.** A `Material` is created **directly on the
> Job** (via the Work surface or a job-attributed PO line); the former
> worksheet-side `PlanMaterial` and worksheet→job carry-over are
> **removed**. `Material` is a billable **atom** (alongside `Task` and
> `Fee`) that the estimate and invoice lenses claim.

Sibling docs:

- `docs/designs/architecture-and-conventions.md` — service-layer pattern,
  `LineItemMixin`, `LineItemService.delete_line_item_with_renumber`,
  delete-confirm pattern.
- `docs/designs/jobs-tasks-and-worksheets.md` — `Job`, `Task`, `Fee`,
  `WorkTemplate`, populate-from-template path, the Work surface.
- `docs/designs/estimates-and-prices.md` — `RateScheme`, billable atoms
  (Materials are atoms), AccountingCategory pass-through.
- `docs/designs/invoicing-and-expenses.md` — `Invoice` /
  `InvoiceLineItem`, expense-bound Materials.
- `docs/designs/quickbooks-integration.md` — QBO integration (expense
  purchases, payment accounts).
- `CLAUDE.md` — line-item delete rule, document numbering, `Configuration`
  key-value store, terminal-DB-write rules.

---

## 1. Overview

The data model splits into three layers:

| Layer | Models | Purpose |
|---|---|---|
| Inventory | `InventoryItem` | Every physical item — one kind, no catalog/lot fork — with prices, units, accounting category, and universal QOH tracking. Frequently-reordered types and one-off minted lots are the same row at different usage frequencies |
| Instance | `MaterialBase` (abstract) → `Material`, `TemplateMaterialAssociation` | Materials live on Jobs (`Material`) or Templates (`TemplateMaterialAssociation`) |
| Procurement | `PurchaseOrder`, `PurchaseOrderLineItem` | Order goods from vendors and receive them. Vendor invoices (bills) live in QBO — §13 |

A `Material` on a Job represents a *commitment*. It is created directly on
the Job (Work surface, PO line, or template populate — there is no
worksheet stage). Every item-backed Material holds an `Earmark` against
the linked InventoryItem **from the moment the Material is created**
(universal tracking) — there is no longer a deferred "earmark on
estimate acceptance" step for plan materials. Earmarks are released by
Consume (decrements QOH and shrinks the earmark) or by Restock (shrinks
the earmark, leaves QOH alone).

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

## 2. InventoryItem (one item kind, minted lots)

`apps/inventory/models.py` — `InventoryItem`, `db_table='inventory_item'`.

> **2026-06 catalog-vs-lots reframe, then 2026-07-05 `is_catalog` drop.** The
> model was `InventoryItem` (`db_table='price_list'`) and the flag was
> `is_inventoried`. The reframe renamed both and made **quantity tracking
> universal** — every physical thing in the shop is tracked while it's here. A
> follow-up completed the rename so nothing says "price_list" anymore: the API
> route is `/api/inventory/`, the FK field on Material/Earmark/line items is
> `inventory_item`, and the PK is `inventory_item_id`. The freeform-materials
> branch then **dropped `is_catalog` entirely** — there is no longer a
> catalog-*type*-vs-transient-*lot* distinction. An `InventoryItem` is just an
> item; a frequently-reordered stock type and a one-off minted lot are the same
> row at different usage frequencies. `is_active` is the only retirement flag.

Every physical item flows through this one table — items that estimates,
invoices, POs, and Materials reference, and the `LOT-{pk}` lots minted
behind freeform Materials at establishment (§3, §4).

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
| `is_active` | bool, default **True** | The only retirement flag. "Can't get this any more / won't reorder, but it is still referenced." A **human judgment**, set manually — nothing auto-retires an item. Pickers default to `?is_active=true` |
| `accounting_category` | FK PROTECT | Required |
| `qbo_id` | `CharField(50)` blank, default `''` | QBO Item mirror (2026-07-21): the id of this item's QBO Item, minted lazily (type `NonInventory`, Name = `code`) by `QBOItemMintService` on the first invoice push that sells it. `''` = not mirrored. Plain field, not `QBOSyncable`. Stock quantities never sync to QBO. See quickbooks-integration.md. |

Derived:

- `qty_earmarked` — `Sum(earmark_set.quantity)`
- `qty_available` — `qty_on_hand - qty_earmarked`

(`is_catalog` and the computed `is_finished_lot` were **dropped** by the
freeform-materials branch — there is no catalog/lot fork and no auto-hiding.)

### One item kind — manual retirement, no hiding

There is no catalog-vs-lot distinction. Every item is a single kind:

- **Everything active is visible and pickable.** There is no automatic hiding
  at QOH 0. The old hide-on-spend / `is_finished_lot` filter and the
  `?include_finished` reveal are **gone**.
- **Order is alphabetical by `code`.** The main list is browsed, so
  alphabetical wins; typeahead pickers are already narrowed by `?search` and
  need no ranking. Dead QOH-0 lots stay findable — useful history ("what did
  we pay last time"). (An in-stock-first ranking was tried 2026-07-05 and
  reverted.)
- **Retirement is a manual `is_active` flip.** When an item genuinely won't be
  reordered, a human deactivates it; deactivated rows drop from the default
  `?is_active=true` picker but can still be shown/re-activated by admins.
- **Lot reuse replaces catalog conversion.** If next year someone searches
  "dragon skin" and picks last year's lot, the new material attaches to it, the
  demand earmark lands on it, Order writes a PO against it, receipt bumps its
  QOH — the lot *becomes* the ongoing home of that material type through use. No
  un-mint / promote / demote path exists or is needed.

### Pricing — markup at creation

`InventoryService.create_item` derives `selling_price` from
`purchase_price × (1 + default_material_markup_percent/100)` **once at
creation**, only when no explicit non-zero sell is given. Config default `'0'`
→ sell == cost; editable in the SPA at **Settings → Pricing** (the
`MaterialMarkupSetting` component, `PATCH /api/settings/`). `update_item` never
re-applies it — the stored value is authoritative. Materials copy cost+sell from
the item at creation (only-if-unset), so they stay self-contained.

The same markup drives the **mint-a-lot** default: `MaterialService.mint_lot`
sets a new lot's `selling_price` from `unit_cost × (1 + default_material_markup_percent/100)`
when no sell is supplied (used by establishment when minting a `LOT-{pk}` lot).

### Lifecycle: write-off, merge

- **No auto-hiding, no auto-delete.** Inventory rows are shop history and are
  never automatically removed — line items
  (`EstimateLineItem`/`InvoiceLineItem`/`PurchaseOrderLineItem`, plus legacy
  `BillLineItem` rows from before the bill retirement, §13)
  and `TemplateMaterialAssociation` reference items via **PROTECT**, so physical
  deletion would raise `ProtectedError`. The removed `is_finished_lot` hide-on-spend
  filter and the retired `collect_if_finished` auto-delete are both gone; a QOH-0
  lot simply stays in the list and can be flipped `is_active=false` by hand.
- **Write-off** (`InventoryService.write_off`, `POST …/{pk}/write-off/`): zeroes
  QOH, books the remainder to `qty_wasted` (recording the wastage history entry
  first). The item stays visible, available for reuse or a manual `is_active`
  retirement.
- **Merge** (`InventoryService.merge`, `POST …/merge/`): the manual dedup tool —
  folds a discard item into a keep item (QOH + aggregates), repoints every
  reference, deletes the discard. With `is_catalog` gone, the old
  catalog-as-discard hard-block is removed — any item may be the discard side (a
  confirm dialog in the UI carries the weight). Still hard-blocks a *real*-unit
  mismatch; a `'none'` unit on either side is treated as *unknown* and the known
  unit wins (a `'none'` keep adopts the discard's unit unless an explicit `units`
  override is given).
- **On order** (`InventoryItem.qty_on_order`, read-only on the serializer +
  the inventory list column): Σ max(qty − received − cancelled, 0) over the
  item's PO lines on non-cancelled POs — the per-material outstanding calc
  aggregated per item.

### Cascade rules

Line items and `TemplateMaterialAssociation` reference the item with `PROTECT`
(preserves historical documents — and is why inventory rows are never
auto-deleted). `MaterialBase.inventory_item` and `Expense.stock_pli` use `SET_NULL`
— which is exactly why the delete endpoint guards beyond the PROTECT set:
`InventoryService.assert_item_deletable` refuses when any line item
(`can_be_deleted`), **Material, Earmark, or Expense stock receipt** references
the item, since the SET_NULL cascades would silently demote established
materials to provisional and orphan stock records. Hard delete is mistake
correction for never-referenced rows only.

Catalog admins use the `is_active` soft-delete instead of hard deletion. Write
access to inventory items requires **either** `can_manage_financials` **or**
`can_manage_config`.

---

## 3. Material model

### MaterialBase abstract

`apps/inventory/models.py` — fields shared by `Material` and (via the
related-but-separate `TemplateMaterialAssociation`) the template side.

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
| `consumption_state` | choices `pending` / `consumed` / `released` | Default `pending` |
| `released_qty` | `Decimal(10,2)` default 0 | Quantity restocked/released back out of the plan (was `restocked_qty`, renamed 2026-07-03). Invariant: `quantity + released_qty` = originally planned — the expense-void reversal relies on it |
| `po_line_item` | FK SET_NULL `related_name='+'` | Optional PO line attribution |
| `cost_source` | `CharField(20)` choices, **null**able | Provenance enum — see below. `NULL` = provisional (no lot yet); non-null = established. `is_customer_supplied` is `cost_source == 'customer_supplied'` |

#### Provisional vs established (the core state)

A `Material` is always exactly one of two backing states, orthogonal to the
consumption lifecycle:

- **Provisional** — `inventory_item IS NULL` (⇔ `cost_source IS NULL`). A
  placeholder: we know we need *something* (description + rough qty, often a
  sell price), but pricing/backing isn't set up. **Not orderable, not
  consumable, not receivable.**
- **Established** — `inventory_item` points at a lot with a real cost; rides the
  full inventory rails (QOH, earmark, arrival-gated `consume`, Order/receipt).

**Establishment = pricing.** The act that turns provisional → established is
supplying the price, which **mints or attaches the lot** (`MaterialService.establish`,
§4). "If there's a price, there can be a lot." Ways to establish: priced at
authoring (mint `LOT-{pk}`), attach an existing item, a PO line supplying cost, an
attached expense, the customer-supplied toggle ($0 locked), or acceptance
crystallizing a marked estimate line (reverse-markup `'estimated'` cost).

#### `cost_source` — one provenance enum

Answers both "is this cost real?" and "who owns this thing?" (`Material.COST_SOURCE_*`):

| Value | Meaning |
|---|---|
| `NULL` | **provisional** — no lot, no meaningful pricing yet |
| `estimated` | reverse-markup placeholder from an accepted estimate line — **cost unconfirmed** (⚠ mark in the UI) |
| `entered` | user typed a researched/quoted cost, or attached an item and accepted its pricing |
| `po` | real document cost from a PO line (**overrides** `estimated`/`entered`; sell is never touched) |
| `expense` | real document cost from an attached expense |
| `customer_supplied` | $0, deliberate and **locked** — customer owns the thing |

`estimated` "cost unconfirmed" is **not** a display state of its own — it rides
as a small ⚠ next to the cost alongside Needed/Ordered/On Hand until a PO or
expense clears it.

**Lifecycle** (deletion doctrine, 2026-07-03): born `pending` (planned;
earmarked on committed jobs) → `consumed` (task start drew the stock;
reversible via `unconsume`) or `released` (a named event said the job planned
it and didn't use it — full restock while referenced, job-completion loose
release, PO sever, CO descope; **terminal**). A pending material that nothing
references (no expense, no PO link, no estimate/CO claim, not invoiced —
`MaterialService._is_referenced`) may instead be hard-deleted (mistake
correction / scratch paper). **Release zeroes `quantity` into `released_qty`**,
so released rows sum to zero in every aggregate consumer (financials, earmark
sweep, COGS) with no state filters; remaining filters (wizard pools) are
display tidiness. Claims are never purged by release — a released material
keeps supporting its estimate/CO/invoice lines as job history.

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

(The former `source_plan_material` carry-over idempotency key was removed
with the planning layer — Materials are authored directly on the Job, so
there is nothing to carry over from.)

#### Validation

`Material.clean()`:

- `task.job_id == job_id` when `task` is set
- `restocked_qty >= 0`

#### `unit_cost` provenance & expenses

`Material.unit_cost` comes from a lot: minted at establishment from the entered
cost (`cost_source='entered'`), copied from an attached item, supplied by a PO
line (`_apply_po_line_cost`, `cost_source='po'`), supplied by an attached expense
(`cost_source='expense'`), or the reverse-markup placeholder from acceptance
(`cost_source='estimated'`). A provisional Material has no lot and no cost
(`cost_source IS NULL`); its estimate face may still carry a **sell** price.

**Expenses & materials** (driven by `ExpenseService`). An expense is one of three:

- **Cost expense** → creates one consumable material at the entered `unit_cost`
  (`cost_source='entered'`); `Expense.amount` is the job cost. `Material.expenses`
  is the reverse of `Expense.material`.
- **Stock receipt** → an **inventory-item-backed** purchase bumps QOH
  (`InventoryService.receive_stock`); **no material is created**. The cost is
  recognised at **consumption**, not at purchase — so `_spent` excludes
  stock-receipt expenses (`stock_pli` set). (With `is_catalog` gone the rule is
  uniform: *any* item-backed purchase is a stock receipt.)
- **Attach to an existing material** (Path 2, §4) → attach to a **pending,
  non-customer** material. Attaching *is* a pricing event: on a provisional
  material it **establishes** it (mints the lot at the expense's unit cost,
  stamps `cost_source='expense'`); on an established one it overrides the cost.
  Either way it **bumps the lot QOH** by the expense quantity — attach == receipt,
  so work can start. See `docs/designs/invoicing-and-expenses.md` (Expense).

### ~~PlanMaterial~~ (removed)

> **Removed.** `PlanMaterial` (`plan_materials`) was the worksheet-side
> mirror of `Material`. It is gone with the planning layer — materials are
> authored directly on the Job as `Material` rows. There is no
> worksheet-side material model.

### PLI-linked vs freeform: the immutability rule

A `Material` with a non-null `inventory_item` is a
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
`MaterialService.update_pricing`.

**Consumption fires at every blep start, not just the first (2026-07-04).**
A blep means work is happening *now*, so recording one — live (`start_work`)
or hand-added (`create_historical`) — sweeps the task's pending materials
(`TaskLifecycleService._consume_pending_materials`; the `pending →
in_progress` promotion is just the first such sweep). The rule set:

1. A material added to (`MaterialService.create_on_job`) or reassigned onto
   (`assign_task`) a task that is already `in_progress` consumes **immediately
   when in stock** (`consume_if_task_started`) — so an after-the-fact "we used
   more" add never depends on a future blep existing.
2. Added while **out of stock** it stays `pending` (the procure-via-PO flow
   needs the row as its anchor), and then:
   a. the **next blep is refused** — `consume()`'s insufficient-stock error
      (the same coaching message the first-blep path always raised) is the
      guard: no work can be recorded while a required material is physically
      missing; or
   b. the **stock arrives** and the next blep's sweep consumes it — no
      PO-receive hook needed.

**Completion is guarded the same way:** `complete_task` refuses while the
task has pending materials ("if a material was used, consume it by hand;
otherwise release it") — a complete task can never blep again, so nothing
would ever consume a leftover. Task-attached pending rows carry a **consume**
button for the by-hand path; the return action is labelled **"restock"** only
when stock is on hand and **"release"** otherwise (for a *pending* material
the action never touches QOH either way — it removes the earmark/quantity,
and at full quantity applies the restock-to-zero rule: referenced →
`released`, unreferenced → deleted).

Every Material is now lot-backed once established, so consumption is
uniformly stock-gated: an established material can be short (QOH < quantity →
`consume` refuses), and a **provisional** (lot-less) material also refuses —
`consume` raises "set its pricing and receive it" rather than silently flipping
(the freeform-materials behavior change; the old "freeform consumes
unconditionally" path is gone). The material's display status
(needs-pricing / needed / ordered / awaiting-customer / on-hand — §16, and the
`materialStatus` SPA lib) is **derived, never stored**; the human-owned `blocked`
job status is not auto-set. Blep-cancel undo nuance: only
the *promoting* blep's cancellation un-consumes; a later blep's arrival
consumption sticks (the material genuinely is allocated — manual unconsume
exists). Tests: `tests/test_blep_start_material_sweep.py` +
`tests/test_late_material_consumption.py`.

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

- **Consume** — **established** (lot-backed): refuses if `qty_on_hand <
  quantity` (arrival gate — the shortfall message coaches "reduce to
  on-hand and add a second material for the remainder while it is procured");
  otherwise `qty_on_hand -= quantity`, `qty_sold += quantity`, earmark `-=
  quantity`, state → `consumed`. **Provisional** (lot-less, `cost_source
  IS NULL`): **refuses** ("This material is provisional — set its pricing and
  receive it before work can consume it") — never a silent flip. (Freeform-materials
  behavior change: the pre-branch null-lot silent-flip is gone.)
- **Unconsume** — the exact inverse of Consume (inventoried:
  `qty_on_hand += quantity`, `qty_sold -= quantity`, earmark
  `+= quantity`; state → `pending`). Not a user op — called by
  `TaskLifecycleService.cancel_work` to undo an oops-Start, so a later
  re-Start can consume the materials again.
- **Restock(n)** — `quantity -= n`, `released_qty += n` (universal
  tracking; conservation `quantity + released_qty` = originally planned);
  if inventoried, earmark `-= n`. At `quantity == 0` the
  **restock-to-zero rule** applies: a *referenced* material
  (expense-bound, PO-linked, claimed by an estimate/CO line, or invoiced)
  becomes `released` — kept as job history with its claims intact; an
  *unreferenced* one is deleted (scratch paper).
- **Release** — `MaterialService.release(material)`: the named
  "planned it, didn't use it" retirement (CO descope, sever of a claimed
  material). Earmark `-= quantity`, `released_qty += quantity`,
  `quantity = 0`, state → `released`. Terminal; claims are not purged.
- **Draw more(n)** — `quantity += n`; if inventoried, earmark `+= n`.
  Forbidden on expense-bound Materials.
- **Edit description** — description-only change (subject to the
  PLI-linked immutability rule).

Validation:

- `restock(n)` requires `0 < n <= quantity`
- `draw_more(n)` requires `n > 0` and not expense-bound
- `consume` requires `state == 'pending'`, an `inventory_item` (refuses
  provisional), and enough QOH (refuses on shortfall)
- `unconsume` requires `state == 'consumed'` (the lone consumed-state op)
- All *user* ops require `state == 'pending'`

### `is_expense_bound`

Computed: `self.expenses.exists()` (via reverse from `Expense.material`).
Expense-bound Materials are user-undeletable and cannot be drawn-more —
the only path that removes them is `ExpenseService.reject(expense)`, and
reject refuses while the material is **consumed or claimed** by an
estimate/CO line (block the upstream event; its delete is then always a
Rule-1-legal delete of the rejected claim's artifact).

### `work_complete` gate

`JobService._loose_pending_materials(job)` returns task-less pending
Materials with `quantity > 0`. Any match blocks the
`Job → work_complete` transition with a clear error. Gate is uniform
across inventoried and non-inventoried PLIs — task-less Materials
always represent an unresolved Consume-or-Restock decision.

The one exception is the **invoice-paid auto-completion path**
(`Invoice._maybe_complete_job`): it is unattended, so instead of being
blocked it calls `JobService.release_loose_materials(job)` first, which
restocks any loose pending Materials and records a `HistoryEntry`. Via
the restock-to-zero rule this **releases** a referenced material (kept
as history — a claimed material's estimate line keeps resolving) and
deletes an unreferenced one. By the time the Job reaches
`work_complete` there are no loose pending materials, so the gate passes.

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
| `create_on_job(*, job, task=None, ..., inventory_item=None, cost_source=None, customer_supplied=False)` | Creates `Material`. **Priced at authoring** (no item, non-zero `unit_cost`, `cost_source ∈ {None, entered}`) → born **established** via `establish` (mints `LOT-{pk}`). `customer_supplied=True` → born established at locked $0 (`cost_source='customer_supplied'`; rejects any pricing input). Item-backed or document-cost adds record `cost_source` without minting. Otherwise **provisional**. Earmarks `+quantity` **only for committed (`approved`+) jobs** — pre-approval jobs earmark later at acceptance |
| `establish(material, *, inventory_item=None, unit_cost=None, sell_price=None, cost_source='entered')` | provisional → established: attach the given item **or** mint a `LOT-{pk}` lot (QOH 0) at `unit_cost` (sell from markup unless an estimate-locked sell already sits on the material). Sets `cost_source`, earmarks if committed, then `consume_if_task_started`. Requires pending + currently lot-less |
| `mint_lot(material, *, unit_cost, sell_price=None)` | Create the `LOT-{pk}` `InventoryItem` behind a one-off material; QOH 0; sell defaults from `default_material_markup_percent` |
| `order(material, po=None)` | Path 1: append a line for this material to draft PO `po`, or create a new (vendor-less) draft PO. Refuses provisional / non-pending / customer-supplied / already-PO-linked. Returns `(po, line)` |
| `mark_on_hand(material, qty, *, user=None)` | Paths 3 & 4: bump the lot QOH by `qty` (no document); records an inventory-history action — `'Customer delivery'` for customer-supplied, else `'Marked on-hand'`. Refuses provisional / non-pending / non-positive qty |
| `consume(material)` | Refuses provisional (raises) and refuses on QOH shortfall; otherwise state → `consumed`, `qty_on_hand -= qty`, `qty_sold += qty`, earmark `-= qty` (earmark a no-op on pre-approval jobs) |
| `unconsume(material)` | State → `pending`; if inventoried: restores `qty_on_hand`/`qty_sold`, and restores the earmark **except on pre-approval jobs** (mirrors `consume`'s no-op) |
| `restock(material, qty)` | `quantity -= qty`, `released_qty += qty`, earmark `-= qty`; at zero: referenced → state `released`, unreferenced → row deleted |
| `release(material)` | pending → `released`: earmark `-= quantity`, `released_qty += quantity`, `quantity = 0`; claims kept (job history). Terminal |
| `_is_referenced(material)` | Rule-1 check: expense-bound, PO-linked, claimed (estimate/CO lens), or invoiced |
| `draw_more(material, qty)` | `quantity += qty`, earmark `+= qty`; rejects if expense-bound |
| `assign_task(material, task)` | Move Material to a different Task (or task=None); validates same job and non-terminal task |
| `update_pricing(material, *, unit_cost=None, sell_price=None, propagate_to_pli=False)` | Update prices; optional one-shot PLI propagation |
| `link_to_po_line(material, po_line)` | Set `po_line_item` FK; validates pending + unlinked |
| `unlink_from_po_line(material)` | Clear `po_line_item` FK |
| `sever(material, decision)` | `'keep'` clears FK; `'delete'` unlinks then releases a referenced Material (claims/expense) or deletes an unreferenced one, backing out the earmark either way. Raises if consumed |
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
  established, item-backed material; a provisional material has no lot to earmark)
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
  task or job-scoped path: Work-surface add, template population, PO line
  creation, expense submit). Under universal tracking this is every
  goods-Material, not just inventoried ones.
- **Released** as Materials Consume/Restock through normal flows. The
  `Job → work_complete` transition runs
  `InventoryService.release_earmarks_for_job(job)` to sweep any
  remaining balance.
- **Aggregator (`create_earmarks_for_job`)** runs at the end of the
  `populate_from_template` path, on job duplication, and on **estimate
  acceptance** (`EstimateAcceptanceService.on_accept`). `create_on_job`
  earmarks at creation **only for committed (`approved`+) jobs** — for
  pre-approval (`draft`/`submitted`) jobs it does not, so acceptance's
  `create_earmarks_for_job` is the point where those jobs' earmarks are
  first created (not a no-op for that path). It **excludes already-consumed
  materials** (`.exclude(consumption_state='consumed')`): a material consumed
  during pre-approval work already drew down QOH, so re-earmarking it would
  phantom-reserve stock that's already used. Correspondingly, `unconsume`
  skips earmark restoration on pre-approval jobs — they carry no earmarks by
  design. See jobs-tasks-and-worksheets.md §"Job-status guard" for the
  pre-approval-work flow that motivates both.

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

## 6. ~~PlanMaterial~~ (removed)

> **Removed.** `PlanMaterial` (`plan_materials`) — the worksheet-side
> material mirror — is gone with the planning layer, along with its
> `update_plan_material_pricing` service and the
> `Material.source_plan_material` carry-over key. Materials are authored
> directly on the Job as `Material` rows (Work surface, PO line, template
> populate). There is no plan→real material carry-over.

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
- `MaterialBase.units` (on `Material`)
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
`TemplateTaskAssociation` so the generated Material attaches to the
corresponding generated Task.

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

`apps/estimates/models.py` — `WorkTemplate.generate_materials_for_job`.
It accepts `task_pairing` (a list of `(TemplateTaskAssociation,
instance_index, Task)` tuples returned by `generate_tasks_for_job`) and an
optional `quantity=N` for multi-instance templates.

For each instance × association:

- If `assoc.template_task_association_id` matches a paired Task, the
  generated material attaches there.
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
| `business` | FK PROTECT **nullable** | Vendor. **Nullable so a draft can be started vendor-less** (the Order-from-material flow, §11) — but `PurchaseOrder.clean()` **requires it at issue**: transitioning out of `draft` with no `business` raises. Contact still must belong to it when both are set |
| `contact` | FK PROTECT nullable | Optional; must belong to `business` if provided |
| `status` | choices | See state machine below |
| `created_date` | datetime | Immutable after first save |
| `requested_date` | datetime nullable | |
| `issued_date` | datetime nullable | Set on transition to `issued` |
| `received_date` | datetime nullable | Set on transition to `received_in_full` |
| `cancel_date` | datetime nullable | Set on transition to `cancelled` |

Date fields are protected after first save by `PurchaseOrder.clean()`.

**Derived total** (computed at query time; never stored):

| Property | Type | Notes |
|---|---|---|
| `po_total` | Decimal | Sum of all `PurchaseOrderLineItem.total_amount` |

`PurchaseOrderSerializer` exposes it. (`billed_total` / `is_fully_billed`
and the serializer's `bills` field were removed with the bill retirement,
2026-07-23 — see §13. There is deliberately **no** "billed" state or flag
on the PO: invoice-vs-PO reconciliation is bookkeeper work done in QBO.)

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

On explicit and claim paths, the existing Material's qty / description are
NOT updated from the PO line — the Material is the source of truth for
planned consumption.

**A PO line supplies/overrides cost and establishes freeform materials**
(`MaterialService._apply_po_line_cost`, run on every resolver path):

- **Provisional (lot-less) material** → the PO line **establishes** it: mints a
  QOH-0 `LOT-{pk}` lot at the line price, stamps `cost_source='po'`, and — when
  the **PO line itself carries no `inventory_item`** (a freeform PO line) —
  **repoints the line at the minted lot** so `receive_items`' `li.inventory_item.qty_on_hand
  += qty` bump lands on that lot. Without the repoint a freeform-PO material
  could never arrive and `consume` would refuse it forever. `establish` is the
  sole earmark writer here (no double: the provisional row had no lot/earmark).
- **Established material** → override `unit_cost` and stamp `cost_source='po'`.
  **Sell price is never touched** (margin trues up against real cost — this is
  where the reverse-markup `'estimated'` placeholder gets cleared to `'po'`);
  no earmark change.

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

### Order — generate a PO from a material (Path 1)

`MaterialService.order(material, po=None)` is the material-side entry to
procurement, surfaced as the **Order** action on the task view page (§16):

- **Append-or-create.** With a draft `po`, appends a line for the material to
  it (must be `draft`). With `po=None`, creates a **new draft PO with no vendor**
  (`PurchaseOrderService.create_po()`) and adds the line — supplier-unknown stays
  painless; the vendor is filled in before issue (the `clean()` gate, §9).
- The line is added via `add_line_item_from_pli(..., job=material.job_id,
  material_id=material.pk)`, so the resolver's **explicit** path links this exact
  material and stamps `cost_source='po'` on it. Receipt then Just Works.
- Refuses provisional (no lot), non-pending, customer-supplied, or
  already-PO-linked materials. Endpoint: `POST /api/materials/{id}/order/`
  (`CanManageFinancials`), body optionally `{po_id}`; also feeds the SPA's
  "add to draft PO-NNNN vs start new" choice.

### Order to stock — no material, no job (`InventoryService.order_stock`)

`InventoryService.order_stock(item, quantity, po=None)` is the item-side
counterpart to `MaterialService.order` above: ordering an `InventoryItem`
**to stock**, with no job needing it and no `Material` created. A plain PO
line — `add_line_item_from_pli(po.pk, item.pk, quantity)` with no `job`, no
`material_id` — receipt bumps QOH via the normal PO-receiving path.

- Same **append-or-create** contract as the material Order flow: given a
  draft `po`, appends; given `po=None`, creates a new draft PO
  (`PurchaseOrderService.create_po()`) and adds the line. Refuses a
  non-draft `po`. Wrapped in `transaction.atomic()`.
- Endpoint: `POST /api/inventory/{id}/order/` (`CanManageFinancials`), body
  `{"quantity": "5", "po_id": <optional draft>}`; response echoes the item
  plus `po_id`/`po_number`.
- Surfaced by the shared `StockOrderDialog.svelte` component on both the
  Catalog **Inventory** tab (per-row Order button, `canManageFinancials`
  only — replaced the old navigate-to-`/purchase-orders/new?inventory_item=N`
  link) and the Catalog **Earmarks** tab (§17). The quantity prompt
  pre-fills with the item-level shortfall — `max(0, qty_earmarked_total −
  qty_on_hand − qty_on_order)` — editable before submit.

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

### Vendor-invoice emails link to the PO

The one bill-adjacent capability konbini keeps (2026-07-23): an inbound
vendor-invoice email is linked to the **PurchaseOrder** via the existing
link-to-po / associate-po / create-po-from-email flows and the
`EmailRecord.purchase_order` association, so the PO's email panel shows
that the vendor invoice arrived. Everything downstream (entry, payment,
reconciliation) happens in QBO.

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

## 13. Bills retired → QBO (2026-07-23)

Konbini no longer manages vendor invoices. Bills are entered, tracked, and
paid **in QuickBooks Online only**; konbini keeps the purchasing side it is
good at — POs, receiving, stock intake — plus one breadcrumb: vendor-invoice
emails link to the PO (§11).

**Schema retained, everything else gone.** `Bill`, `BillLineItem`, and
`BillPayment` still exist in `apps/purchasing/models.py` as **RETIRED
schema-only stubs** — bare field declarations kept so no destructive
migration is generated and legacy dev-DB rows survive in case of reversion.
No active code creates, mutates, or displays them. Removed with the
retirement:

- All Bill/BillPayment business logic (clean/save overrides, transitions,
  computed properties, `recompute_payment_status`), the `@history` capture
  on Bill, and admin registration.
- `BillService`, `BillPaymentService`, `BillViewSet`, the bill serializers,
  and every `/api/bills/` route.
- The QBO layer: `QBOBillSyncService` (bill push, bill-payment
  push/update/void), `QBOVendorSyncService` (its only caller was the bill
  push), the bill slice of payment polling and sync-failures — see
  `quickbooks-integration.md`.
- The SPA bill pages/picker/nav entry, bills in search, the business/contact
  bill panels, the PO detail billed section, and `RecordPaymentModal`.
- Email link-to-bill/unlink actions and the `'bill'` association target
  (`EmailRecord.bill` FK column retained as legacy schema only).

**What stays (passive/legacy):** the PROTECT FKs and deletion-protection
checks that reference the retired models keep guarding legacy rows
(contacts checks, business-delete impact counts,
`InventoryItem.has_document_line_refs`' BillLineItem clause, inventory-merge
repointing of legacy `BillLineItem` rows). `AccountingCategory.qbo_expense_account_id`,
`Configuration['qbo_payment_accounts']` + `QBOPaymentAccountService`, and
`Business.qbo_vendor_id` remain in active use by the expense/reimbursement
pushes and `QBODisplayNameService`.

If the retirement is not reverted, a table-dropping migration is still owed
(tracked in `docs/designs/LATER.md`).

---

## 14. Line item API pattern

The PO line-item viewset uses `LineItemMixin`
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

The PO detail page (`PurchaseOrderDetail.svelte`) shows `po_total` sourced from `PurchaseOrderSerializer`. (The billed section, the Create Bill link, and the PO list's Bill column were removed with the bill retirement, 2026-07-23 — §13.) Its email panel shows linked vendor emails, including inbound vendor invoices linked via the email→PO flow (§11).

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

## 16. UI: Material status vocabulary & actions

### Derived display status (`materialStatus`)

`frontend/src/lib/materialStatus.js` computes **one derived label per material
row** from serializer fields already present (no new backend state). Precedence
(first match wins): **released → consumed → needs-pricing → on-hand →
awaiting-customer → ordered → needed**. "On-hand" is checked **before** the
procurement states, so a material the shelf already covers reads **On Hand**
regardless of how it was going to be sourced.

| Status | Condition | Actions |
|---|---|---|
| **Needs pricing** | provisional — no `inventory_item` | *Set pricing* (opens `MaterialModal` in set-pricing mode — establishment on save), *Attach expense* (establishes + receives) |
| **Needed** | established, stock short, no PO link | **Order** (dialog), *Attach expense*, *Mark on-hand* (quiet text link) |
| **Ordered — PO-NNNN** | established, PO-linked, short | PO number links to the PO (receive there); *Attach expense* for the bought-remainder |
| **Awaiting customer** | `customer_supplied`, stock short | **Mark received** (qty prompt, default remainder) |
| **On Hand** | established, lot QOH covers `quantity` | none — the quiet good state |
| **Used** | `consumption_state == 'consumed'` | none (the visual consumed flag; displayed as "Used") |
| **Released** | `consumption_state == 'released'` | none — tombstone: greyed/struck, qty 0 |

**Cost-unconfirmed ⚠** (`costUnconfirmed` = `cost_source === 'estimated'`): a
small warning mark next to the cost, coexisting with any pending-phase status,
cleared when a PO/expense supplies a real cost.

### One row fragment, full actions everywhere (the old venue rule is gone)

Material rows render through ONE shared fragment —
`components/materials/MaterialRow.svelte` (extracted 2026-07-13 from
`TaskTree`'s triplicated blocks) — on every surface that lists materials:
the job task list's task/subtask/loose rows (`TaskTree` inside
`TasksPanel`), the task detail page's Materials section, and the parent
task's subtask tree. The **full action set** (Set pricing / Order dialog /
Attach expense / Mark on-hand / Mark received / mark used / restock–release
/ draw more / edit / Move–detach / PO link) is available on ALL of those
surfaces — the old "actions live on the task view page only" venue rule
was retired 2026-07-13. Gating is by **material status, permissions, and
job state only**: the per-status action table above, `can_manage_financials`
for Order, and the held-job freeze-plan-not-procurement rule. (Mechanically,
each button still renders only when its callback prop is wired — a
deliberately read-only mount stays passive — but every current surface
wires everything.) The handler halves are shared too: prompt-based ops in
`lib/materialOps.js`, and the Order / Mark-received dialogs in
`components/materials/MaterialFulfillmentModals.svelte`
(`startOrder`/`startReceipt` via `bind:this`). Note the task detail page
has no raw material-delete button — removal is the **release** action
(full-quantity restock), the same vocabulary as everywhere else.

The job overview (2026-07-09 six-block redesign; `jobs-tasks-and-worksheets.md`
§9) does **not** mount `TaskTree` at all — it never lists rows. Its
Materials block (`MaterialsBlock.svelte` → `materialsBlock()` in
`lib/jobOverview.js`) shows a **Coverage** stat instead: `SHORT` (red)
when any job material's `materialStatus(m).key === 'needed'`, else `OK`
(green). This coverage signal only counts the **Needed** status —
**Needs pricing** and **Awaiting customer** materials are short of
stock too but are not counted as `SHORT`; see `docs/designs/LATER.md`.

### `MaterialModal` — create / edit / set-pricing

`frontend/src/components/MaterialModal.svelte` (Work surface + full task list):

- **Item-linked** edit disables description / units / accounting_category and
  the item itself. Pricing stays editable; on save with changed prices a modal
  asks "Update the inventory item with the new values?" → `propagate_to_pli`.
- **Set-pricing mode** (from a Needs-pricing row): attach an item **or** enter a
  cost; saving *is* establishment — no separate ceremony. The mode reuses
  `materialStatus()` to infer that the row is provisional.
- **Customer-supplied toggle**: flipping it zeroes and **locks** the pricing
  fields; on save the material is born/established at $0
  (`cost_source='customer_supplied'`). A provisional row ("needs pricing") and a
  customer-owned one never look alike.

The **Order** action shows the append-or-create dialog (add to an existing draft
PO — listed by number/vendor — or start a new one); **Mark on-hand** and **Mark
received** prompt for a quantity (defaulting to the full remainder, partial
receipts allowed).

---

## 17. UI: the Catalog area

The sidebar's "Catalog" link (`href="/catalog"`, was "Inventory") is a
three-tab area, each tab a real route (not local-state tabs) sharing
`components/CatalogTabs.svelte`:

| Route | Page | Content |
|---|---|---|
| `/catalog` | `routes/catalog/CatalogInventoryPage.svelte` | Inventory list (default tab) |
| `/catalog/service-items` | `routes/catalog/CatalogServiceItemsPage.svelte` | `ServiceItemManager` (moved out of Settings) |
| `/catalog/earmarks` | `routes/catalog/CatalogEarmarksPage.svelte` | Read-only commitment report (new) |

`/inventory` was deleted with no redirect (pre-production, no bookmarks to
preserve). The whole area is visible to every authenticated user, same as
the old Inventory link.

### Inventory tab

Inventory-item CRUD + browse UI, unchanged from the old `#/inventory` page
except the per-row **Order** button now opens the shared
`StockOrderDialog.svelte` (§10) instead of navigating to
`/purchase-orders/new?inventory_item=N`; still rendered only for
`canManageFinancials`. Item pickers across the SPA use
`frontend/src/components/InventoryItemPicker.svelte`, built on `SearchPicker`.

**Nothing hidden** (`is_catalog` drop). The list and pickers show every active
item, **alphabetical by `code`** (the viewset's base ordering,
`apps/api/inventory/views.py`) — the hide-on-spend/`?include_finished` filter
is gone and no stock-based ranking replaces it (tried and reverted 2026-07-05;
pickers are `?search`-narrowed anyway). The list's former **catalog|lot** column is now an
**active/inactive** column (`is_active`); the `?is_catalog=` filter, the
`inventory_item_is_catalog` serializer fields, and the catalog badge are gone.

`InventoryItemPicker` queries server-side `?search=` (`code` and
`description`) as the user types. Accepts a `params` prop for additional
filters (e.g. `is_active=true`); offers a "None (freeform)" escape via the
`header` snippet.

### Service Items tab

`ServiceItemManager.svelte` — same component, now mounted at
`/catalog/service-items` instead of a Settings tab. Gained a read-only mode:
the table renders for any authenticated user; Add/Edit/Delete buttons render
only when the user has **any** of `can_manage_jobs`, `can_manage_financials`,
`can_manage_config` (backend: `CanManageJobsOrFinancialsOrConfig`, §users-and-permissions.md).

### Earmarks tab (new)

`CatalogEarmarksPage.svelte` — read-only commitment report, one row per
`Earmark` (item + job), fetched whole via `GET /api/earmarks/`
(`EarmarkViewSet`, `ReadOnlyModelViewSet`, `IsAuthenticated`, **unpaginated**
— earmarks stay small, sorting is client-side). Columns: item code,
description, units, job number (link → `#/jobs/{id}`), qty earmarked (this
row), item-level QOH, item-level on-order, item-level **shortfall**,
outstanding-PO links, Order button.

- **PO links**: every distinct non-cancelled PO with an outstanding line for
  the item (`qty − qty_received − qty_cancelled > 0`), rendered as
  `po_number` linking to `#/purchase-orders/{id}`. There can be several.
- **Shortfall** (`frontend/src/lib/stockShortfall.js`): `max(0,
  qty_earmarked_total − qty_on_hand − qty_on_order)`, computed at **item**
  level and repeated on each of that item's rows (like QOH/on-order). Two
  jobs each earmarking 5 of an item with QOH 5 would each show 0 per-row —
  the item-level number reads "to cover every commitment you need N more,"
  the number you'd actually purchase. Self-correcting: ordering from one row
  raises on-order, so the sibling row's shortfall drops after reload.
- **Order button**: `canManageFinancials` only; opens the same
  `StockOrderDialog.svelte` as the Inventory tab, quantity pre-filled with
  the item-level shortfall (§10).

`EarmarkSerializer` shape per row: `earmark_id`, `inventory_item`,
`item_code`, `item_description`, `units`, `job`, `job_number`, `quantity`,
`created_date`, plus item-level `qty_on_hand`, `qty_on_order`,
`qty_earmarked_total`, and `pos: [{po_id, po_number}, ...]`. Shortfall is
computed client-side from the three quantity fields.

### Settings — Pricing tab

`UnitsManager` (`frontend/src/components/UnitsManager.svelte`) — the
settings UI for editing the `units_list` Configuration value — renders
under the **Setup** tab, not Pricing. The Settings tab formerly named
"Catalog" is now **Pricing** (key `pricing`) —
`ServiceItemManager` left it for `/catalog/service-items`; it now holds the
material markup default (`MaterialMarkupSetting`), RateSchemeManager, and
`DefaultMaterialCategorySetting` (below). The old "Work templates — not yet
implemented" stub was deleted.

The `default_material_accounting_category` picker
(`DefaultMaterialCategorySetting.svelte`, gated `can_manage_config`) was
extracted out of `AccountingCategories.svelte` into its own component and is
now rendered in **both** the Accounting tab and the Pricing tab — one
implementation, two placements. See `estimates-and-prices.md` §6.4 and
`data-constraints.md` §1.1.

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
- **`accounting_category` required on `PurchaseOrderLineItem`** — part of the project-wide line-item AC-NOT-NULL migration tracked in `architecture-and-conventions.md`.
