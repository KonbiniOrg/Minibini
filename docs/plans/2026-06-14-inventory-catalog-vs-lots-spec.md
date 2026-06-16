# Inventory reframe: catalog items vs. transient lots — spec + plan

**Status:** Active spec (rev. 2 — incorporates the 2026-06-14 adversarial
review). Promotes the 2026-06-13 proto-spec to an agreed design + phased plan.

**Goal:** Make quantity tracking universal — every physical thing in the shop is
tracked while it's here — so leftover stock becomes findable and reusable instead
of invisible "lost money." A catalog flag distinguishes reorderable *types* from
one-time *lots*; the unified, browsable inventory list is the payoff surface.

**Tech stack:** Django 5.2 / DRF / MySQL backend, Svelte 5 SPA frontend.

**Sequencing:** **B (backend reframe) ships before A (frontend).**

---

## 1. Background — today's model

- `PriceListItem` (table `price_list`) is the universe; `is_inventoried` opts an
  item *into* quantity tracking. Freeform Materials (no PLI) and non-inventoried
  PLIs carry no on-hand tracking → leftover stock is invisible.
- `Material` / `PlanMaterial` both subclass `MaterialBase`. `Material` lives on a
  Job; `PlanMaterial` is the planning forecast (worksheet/estimate).
- `Earmark` reserves stock per `(price_list_item, job)` — `unique_together`
  (`apps/inventory/models.py:17`). Created from a Job's **Materials** (never
  PlanMaterials) at carry-over (`create_earmarks_for_job`), **only** for
  `is_inventoried=True` items. Released on terminal job states via
  `release_earmarks_for_job` — a **bulk** `Earmark.objects.filter(job=job).delete()`.
- `InventoryAdjustment` (`inv_adjustments`) logs QOH deltas, `on_delete=CASCADE`.
  **Write-only** — nothing reads/sums it except `validate_data` lints. QOH is an
  independently-maintained stored field.
- **FKs into `PriceListItem` (the canonical list, per `can_be_deleted`
  `apps/inventory/models.py:83-99`):**
  - `Earmark.price_list_item` — CASCADE
  - `InventoryAdjustment.price_list_item` — CASCADE (being deleted in B2)
  - `MaterialBase.price_list_item` — SET_NULL (both `Material` + `PlanMaterial`)
  - `BaseLineItem.price_list_item` — **PROTECT** (abstract → `EstimateLineItem`,
    `InvoiceLineItem`, `PurchaseOrderLineItem`, `BillLineItem`; `apps/core/models.py:333`)
  - `TemplateMaterialAssociation.price_list_item` — **PROTECT** (`apps/inventory/models.py:219`)
  - `Expense.stock_pli` — SET_NULL (`apps/expenses/models.py:64`)
- `MaterialBase._populate_from_pli` copies cost/sell/desc/units/category from the
  linked item **at creation, only if unset** (`apps/inventory/models.py:153-165`)
  — a snapshot, not a live read.
- HistoryEntry: `record_history(object_type, ...)` routes to a concrete per-domain
  table via `_domain_models()` (`apps/core/history.py:31-42`): JobHistory /
  CrmHistory / PurchasingHistory. `'material' → JobHistory` already; `Material` is
  already `@history`-decorated. Target ref is loose `object_type`+`object_id`
  (CharField/IntegerField) → **survives target deletion**.

---

## 2. The reframe — core decisions (B)

### 2.1 Rename + catalog flag
- `PriceListItem` → **`InventoryItem`**; `db_table 'price_list'` → `inventory_item`.
- `is_inventoried` → **`is_catalog`** (catalog item = reorderable *type*; no flag
  = transient *lot*). **This is a drop-old-field + add-new-field, NOT a
  RenameField** (see §2.2 — the values don't carry).
- **API route** `price-list-items` → `inventory-items`. The index dict in
  `apps/api/urls.py:49-50` already contains an `inventory-items` key (currently
  unused by the router) — remove the duplicate/`price-list-items` entry and point
  it at the renamed route. Update the router registration + `basename`.
- **Serializer field renames cross the API boundary** — coordinate with the SPA in
  the same phase: `is_inventoried` → `is_catalog`, and
  `price_list_item_is_inventoried` → `price_list_item_is_catalog` in **both**
  `apps/api/inventory/serializers.py` and `apps/api/tasks/serializers.py`. SPA
  consumers: TaskTree.svelte (×3), MaterialPicker.svelte (`pli.is_inventoried`).
- **Search result key** `price_list_items` (`apps/api/search/views.py:92-94`,
  `apps/search/services.py`) is consumed by `Search.svelte` — rename in lockstep
  or leave the key string stable (decide in B1; prefer stable key to limit blast).
- After: grep `PriceListItem`, `is_inventoried`, `price_list` (outside migrations)
  → expect zero. **Scope is large** — see Appendix A (app code + ~75 test files +
  7 fixtures).

### 2.2 Data migration (drop + add, all rows catalog)
Today's PriceListItems *are* the curated price list → **every existing row becomes
a catalog item**. Migration: **add** `is_catalog` (BooleanField) defaulting True,
backfill all rows to True, **then drop** `is_inventoried`. Do **not** RenameField
`is_inventoried→is_catalog` (its boolean values are the wrong semantics).

### 2.3 Universal tracking
- Every goods-`Material` is backed by an `InventoryItem` row (catalog item or
  transient lot). No untracked-freeform escape hatch.
- `PlanMaterial` stays a pure plan: no inventory row, no earmark, no QOH.

### 2.4 Lot minting + where QOH comes from
A row is created when a `Material` is born on a Job (carry-over / approval /
direct add). QOH source:
- **Purchase-backed** (cost-item expense or PO receipt) → QOH = received qty.
- **Bare planning material** (typed-in, no purchase) → QOH 0 + earmark; shortfall
  until sourced, riding the existing consume-time shortfall block.

A Material referencing an **existing** item just earmarks it — no new row.

### 2.4a Expenses reframe (the just-built feature — explicit coverage)
Today `apps/expenses/services.py` branches **stock-receipt vs. cost-material** on
`pli.is_inventoried` (`submit` ~line 41; also `_move_material_to_job`, `update`,
`delete`, `reject`; `receive_stock` gated at `services.py:114`). New rule under
universal tracking, keyed on **`is_catalog`**:
- **Picked a catalog item** → **stock receipt** (restock the catalog type): bump
  its QOH via `receive_stock`, no Material, amount not job-costed (cost lands at
  consumption). `Expense.stock_pli`/`stock_qty` unchanged in meaning.
- **Freeform (no item)** → **cost material**: mint a transient lot + consumable
  Material, QOH = qty, amount job-costed now.
- There is no longer a "non-inventoried PLI" middle path (all existing PLIs are
  catalog). Mechanical substitution `is_inventoried → is_catalog` in every expense
  branch + `receive_stock`. Update `test_expense_material_inventory.py`,
  `test_expense_service.py`, `test_api_expenses.py` accordingly.

### 2.5 Earmarks: generalized + surfaced
- **Drop the `is_inventoried` gate in ALL QOH/earmark methods** (not just two).
  Enumerated: `create_earmarks_for_job`, `_mutate_earmark`, `get_earmark_preview`,
  `complete_task_adjustment`, `receive_ad_hoc_purchase`, `reverse_ad_hoc_purchase`,
  `receive_stock`, `MaterialService.consume`, `MaterialService.unconsume`
  (`apps/inventory/services.py`), and `receive_items` + `reverse_receipt`
  (`apps/purchasing/services.py`). New condition: gate on **`price_list_item is
  not None`** (every goods-material is backed); stock-receipt/restock paths key on
  `is_catalog` where the catalog-vs-lot distinction matters.
- **Surface** earmarks: on-hand / earmarked / available everywhere (serializer
  already computes `qty_earmarked`/`qty_available`), plus an explicit "N in stock,
  earmarked for job XYZ" warning at add-to-job. Subsumes the "earmark-aware
  availability, later" comment in `MaterialSerializer.get_qty_on_hand`.

### 2.6 Lifecycle — HIDE-on-spend (not delete), with the earmark exception
**Physical deletion of a spent lot is impossible** — `BaseLineItem` (×4 line-item
tables) and `TemplateMaterialAssociation` reference items via **PROTECT**, so a lot
that was ever estimated/invoiced/ordered/billed/templated raises `ProtectedError`
(`can_be_deleted` enumerates them). Therefore:
- A **transient lot** is **hidden** (not deleted) when **QOH = 0 AND no
  outstanding earmarks** — the "finished lot" predicate. Hidden = excluded from
  the active inventory list and from allocation dropdowns. Implemented as a
  **derived filter** (`not is_catalog AND qty_on_hand == 0 AND not earmarks`), no
  new field, no migration, no deletion hook.
- A **catalog item** is always shown (subject to its own `is_active`).
- This dissolves the `release_earmarks_for_job` bulk-delete problem: when a job
  terminates and its earmarks are bulk-released, a now-finished lot simply becomes
  hidden by the predicate — nothing to delete, no orphan, no hook needed.
- **Demotion edge:** un-checking `is_catalog` on a finished item just makes it
  hidden by the same predicate (no special action).
- Hidden tombstones accumulate slowly; a future pruner is a LATER (only physical
  deletion is via merge, below). The Material/Expense remain self-contained on
  cost+sell (§2.7) so the hidden row is never read for pricing.

### 2.7 Pricing — markup config
- Configuration key **`default_material_markup_percent`** (string; default `'0'`).
  Add to settings UI, all test `setUp`s, all 7 fixtures.
- At **inventory-item creation only**, when `selling_price` is unset/zero, set
  `selling_price = round(purchase_price × (1 + markup/100), 2)`. Inject in
  `InventoryService.create_item` **before** `full_clean()`. **`update_item` must
  NOT re-apply** (guard analogous to `if not instance.pk`). Snapshot, not live.
- `Material` continues to copy cost+sell at creation (existing `_populate_from_pli`,
  only-if-unset → no double-apply). Per-Material edits stick.

### 2.8 Write-off
- Action: zero a lot's QOH, record remainder as **wasted** (`qty_wasted +=
  remaining`), then the hide predicate takes effect.
- **Ordering (critical):** write the **wastage `action` HistoryEntry FIRST**, then
  any subsequent state change — wastage must never be lost. Asserted by test.
- LATER note: whether wastage should push to QBO.

### 2.9 Merge (explicit, atomic — the only physical delete)
- Endpoint: `keep_id`, `discard_id`, + retained-field choices (description /
  pricing / units / code / catalog-flag).
- One transaction: move `discard.qty_on_hand` onto keep; **repoint EVERY FK** off
  discard onto keep — `Earmark` (**sum-and-collapse** on `(item, job)`
  `unique_together` collisions), `Material`+`PlanMaterial`, all 4 line-item tables
  (`EstimateLineItem`/`InvoiceLineItem`/`PurchaseOrderLineItem`/`BillLineItem`),
  `TemplateMaterialAssociation`, `Expense.stock_pli`; fold
  `qty_sold`/`qty_wasted`/`restocked_qty` aggregates; apply retained-field choices;
  **then delete discard** (now refless → no `ProtectedError`).
- **Hard-block on unit mismatch** (400). **`discard` may not be a catalog item**
  (400) — demote first.
- Two `action` HistoryEntries: discard "−N → merged into KEEP", keep "+N ← merged
  from [discard code]".

### 2.10 History — retire InventoryAdjustment, add an inventory partition
- **Delete `InventoryAdjustment`** (model, `inv_adjustments` table). It's
  write-only and CASCADEs away exactly when needed.
- Add a concrete **`InventoryHistory(HistoryEntryBase)`** model + `db_table` +
  migration (mirror `JobHistory` at `apps/core/models.py`), and register
  **`'inventoryitem' → InventoryHistory`** in `_domain_models()`
  (`apps/core/history.py:38`). Do **not** remap `'material'` (stays JobHistory; the
  per-job lens comes from Material's existing `@history`).
- Replace all **6** `InventoryAdjustment.objects.create(...)` sites
  (`apps/inventory/services.py:67,84,102,119`; `apps/purchasing/services.py:383,512`)
  with `record_history('inventoryitem', entry_type='action', object_id=item.pk,
  user=…, changes={'_action': …, 'qty_change': …, 'qty_on_hand': …,
  'code': item.code, 'description': item.description, 'job': …, 'document': …},
  text=reason)`. The `code`/`description` snapshot keeps deleted/hidden lots
  legible.
- **Signature changes:** `manual_adjustment` (services.py:67) and `receive_stock`
  (:119) currently carry neither job nor user → thread `user` through their
  callers for the HistoryEntry. PO sites (:383,512) already have `po` + `user`.
- **Fix all 3 `validate_data` lints**, not one: remove `check_inventory_adjustments`
  (`validate_data.py:613`); fix `check_earmarks`' `is_inventoried` error
  (~:601, now a false positive on every earmark); fix `check_price_list_items`'
  "non-inventoried but has quantity" warning (~:576).

### 2.11 Permissions
Both `can_manage_config` **and** `can_manage_financials` get full CRUD on inventory
items. Update the viewset `get_permissions` to accept either atom.

---

## 3. Frontend (A)

- **Inventory list page:** code, description, units, **on-hand / earmarked /
  available**, catalog flag, active. Active view = catalog items + lots with QOH>0
  (or earmarks); finished lots hidden but reachable via a "show finished/all"
  toggle so they remain editable/mergeable.
- **CRUD editing** (both atoms), SPA conventions (explicit saves, `data-table`,
  overlays).
- **Catalog checkbox** = promote/demote.
- **Merge UI:** keep/discard + retained-field picks + confirm (irreversible).
- **Write-off action.**
- **Earmark warning at allocation;** lots capped at available, catalog uncapped.

---

## 4. Phased plan

TDD. Commit per phase. `makemigrations` only (never `migrate`); tests use their
own DB; one backend test process at a time. Commit trailer required.

- **B0 — Markup config + pricing-at-creation** (pre-rename, low risk). Config key
  + create-time markup (guarded against update re-apply) + fixtures/setUps. Tests.
- **B1 — Rename** PriceListItem→InventoryItem, is_inventoried→is_catalog (drop+add
  migration, all rows catalog), API route, serializer fields + SPA consumers,
  search key decision. Update ~22 app files + ~75 test files + 7 fixtures. Grep
  clean. Full suite green.
- **B2 — Retire InventoryAdjustment → InventoryHistory** partition; 6 call sites;
  signature threading for user; drop model+table; fix 3 lints. Tests incl.
  survives-deletion.
- **B3 — Universal tracking + earmark generalization** (drop the gate in all ~11
  methods; lot minting; PlanMaterial mints nothing). Expenses reframe (§2.4a).
  Tests.
- **B4 — Lifecycle: hide-on-spend + earmark exception** (derived filter; catalog
  exempt; release_earmarks path). Tests.
- **B5 — Write-off** (wastage-entry-before-state-change ordering; endpoint; either
  atom). Tests + QBO LATER.
- **B6 — Merge** (repoint ALL FKs incl. line items + TemplateMaterialAssociation +
  Expense.stock_pli; sum-collapse earmarks; unit-mismatch + catalog-discard 400;
  delete discard). Tests.
- **B7 — Permissions** (either atom). Tests.
- **A1** list page (read) · **A2** CRUD + catalog checkbox · **A3** merge UI +
  write-off · **A4** earmark warning at allocation. Vitest per phase.
- **Z — Docs:** update `docs/designs/materials-inventory-and-purchasing.md` + CLAUDE.md
  model/db_table notes; LATER notes (§6); write `docs/ui-flows/Inventory.md`.

## 5. Decisions log
- Hide-on-spend (PROTECT FKs forbid physical delete); merge is the only physical
  delete and repoints everything first. No pruner (LATER).
- Bare planning material = unsourced demand → QOH 0 + earmark → shortfall block.
- Material/Expense self-contained on cost+sell → hidden rows never read for price.
- Merge: unit-mismatch + catalog-discard hard-blocked; sum-collapse earmarks.

## 6. LATER notes (`docs/designs/LATER.md`)
- **Write-off → QBO?** push wasted inventory as expense/COGS, or inventory-only.
- **Hidden-tombstone pruner** — if `inventory_item` bloats with finished lots.

## 7. Durable docs
- `docs/designs/materials-inventory-and-purchasing.md`; `docs/ui-flows/Inventory.md`
  (new); CLAUDE.md Key Models + db_table memory note.

---

## Appendix A — rename surface (grep 2026-06-14)
**App `PriceListItem`:** api/inventory/{serializers,views}, api/jobs/views,
api/search/views, api/urls, core/management/commands/validate_data, core/models,
estimates/{change_order_service,forms,models,services}, expenses/{models,services},
inventory/{forms,models,services,views}, invoicing/services, jobs/services,
purchasing/{forms,services}, search/services.
**Frontend:** CatalogPicker, expenses/MaterialPicker, LineItemModal, MaterialModal,
PlanMaterialModal, PriceListItemPicker, purchaseorders/LineItemForm, SettingsPage,
TaskTree, Search.svelte; api/tasks/serializers (`is_inventoried`).
**Tests/fixtures (NOT optional — same commit as B1):** ~75 `tests/test_*.py`
referencing `PriceListItem`/`is_inventoried`/`InventoryAdjustment` (~90
`is_inventoried` occurrences); 7 fixtures embedding `inventory.pricelistitem` +
`is_inventoried`: unit_test_data, purchasing_data, invoicing_data,
mixed_lineitems, workorder_from_estimate, large_datasets/nealsmall, nealseed.
