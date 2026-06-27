# Phase 1 (rework) — "Add Line" on the Plan

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Reworks the originally-built "Add from Price List" picker to the corrected add model
> (design draft §3/§7/§8, revised 2026-06-27). **Depends on Phase 0** (the
> RateScheme/ServiceItem rename) — this doc uses the **new** names throughout.

**Names (post-Phase-0):** **ServiceItem** = a saved work item (the salable concept;
*was* `TaskTemplate`). **RateScheme** = the rate card / price (rate + algorithm +
modifier menu; *was* `ServiceItem`). **InventoryItem** = goods (unchanged).

**Goal:** One **"Add Line"** action on the Plan (build view). You type *what the line
is*; a type-ahead searches **ServiceItems (saved work) + InventoryItems (goods)**.
- Pick a **ServiceItem** → a `PlanTask` (its RateScheme rate + default modifiers
  attached; the estimator sets qty).
- Pick an **InventoryItem** → a `PlanMaterial` (+ qty); price comes with it.
- Commit **free text** (no match) → the modal asks which it is:
  - **work** → attach a **RateScheme** via a plain `<select>` (not a type-ahead — the
    rate card is short) → a `PlanTask` (typed name + that rate + qty + modifiers);
  - **one-off material** → a freeform `PlanMaterial` (description + qty + units +
    direct price + AC; no RateScheme — goods price by a number).

A **RateScheme is the rate you attach**, never something you search.

**What changes vs. what shipped.** The built picker searches **RateSchemes (rate
cards) + InventoryItems** and makes a PlanTask straight from a rate card. The rework
flips the work side: the searchable work catalog becomes **ServiceItems (saved work
items)**; a rate card is attached only to a *free-text* task, via a select. So this is
a revision of the existing `PriceListPicker` / `SearchPicker` wiring, not net-new.

## Global constraints
- **Depends on Phase 0** (rename) being merged first, so endpoints/models use the new
  names (`/api/service-items/` now lists saved work items; the rate card is
  `/api/rate-schemes/`). Don't start until the rename has landed.
- Svelte 5 runes; reuse `SearchPicker` + the existing modal shell. Never write the dev
  DB; backend tests on the test DB (one process); frontend `cd frontend && npm run
  test:run`. One model change (drop a template field) → one migration → fresh build.

## Reference (current, pre-rework — names shown post-rename)
- `frontend/src/components/PriceListPicker.svelte` — the built type-ahead (currently
  over rate cards + inventory). `frontend/src/components/SearchPicker.svelte` — the
  shared backend type-ahead. `WorkItemForm.svelte` (task add; has a pre-selected
  rate-card prop), `PlanMaterialModal.svelte` (material add; pre-selected inventory
  prop + freeform), `WorksheetDetailPage.svelte` (the **"Add Line"** button +
  wiring).
- Saved-work-item list endpoint (was `/api/task-templates/`, now `/api/service-items/`):
  add a `?search=` filter if absent (mirror the search filter the original Phase 1
  added to the rate-card + inventory lists). Rate-card list (now `/api/rate-schemes/`)
  for the plain select. `/api/inventory/?is_catalog=true&search=` exists.

## Tasks (TDD; each ends green + commit)

### Task 1 — Backend: `?search=` on the saved-work-item (ServiceItem) list
The Add-Line type-ahead searches ServiceItems (the saved work items). Add a `?search=`
filter (name + description `icontains`) to that list endpoint if it doesn't have one,
mirroring the filters added in the original Phase 1. Tests: a matching name returns
the item; a non-match excludes it.

### Task 2 — Drop the template's default qty (`default_billable_qty`)
Per the qty decision (magnitude is per-job): remove `default_billable_qty` from the
ServiceItem (saved work item) model + serializer + fixtures + nealsdata + tests;
migration; fresh-build run. Generation (Task 4) seeds qty = 1, which the estimator
adjusts. (Small; could be folded into Phase 0's template migration if sequenced
together.)

### Task 3 — Rework the picker to search ServiceItems + InventoryItems
Rework `PriceListPicker` (rename it `AddLinePicker` for clarity): `SearchPicker` over
`/api/service-items/?search=` (saved work) **+** `/api/inventory/?is_active=true&is_catalog=true&search=`
(goods), one untagged list. `onPick`: a ServiceItem → `onselect({ kind:'service',
item })`; an InventoryItem → `onselect({ kind:'material', item })`. Keep the modal
shell + the widened search box. Update its tests (search hits both endpoints; pick
emits the right kind+item).

### Task 4 — Generation + the free-text fork
- **Pick a ServiceItem (saved work)** → create a `PlanTask` from it: copy its
  RateScheme + default modifiers + name/description; **qty = 1** (estimator edits).
- **Pick an InventoryItem** → `PlanMaterial` (+ qty), as today.
- **Free text** → the modal fork:
  - **work** → a plain RateScheme `<select>` (from `/api/rate-schemes/`) + qty +
    modifier selection → `PlanTask` (typed name + that RateScheme).
  - **one-off material** → freeform `PlanMaterial` (description + qty + units + direct
    price + AC).
  Reuse `WorkItemForm` (its pre-selected prop becomes a **RateScheme**, used only on
  the free-text-work path) and `PlanMaterialModal` (freeform path). Tests for each
  branch.

### Task 5 — Wire into the Plan's "Add Line" button
`WorksheetDetailPage` "Add Line" opens `AddLinePicker`; route picks/free-text to the
seeded forms. Remove any remaining rate-card-search path. Update the worksheet tests.

### Task 6 — Inline "Save to catalog" (create a ServiceItem from a free-text task)
So a user writing a free-text task can save it to the **ServiceItems catalog** (the
saved-work list) without a separate trip to a config/templates area.

- On the **free-text → work** path (Task 4), after the user has the name + attached
  RateScheme + selected modifiers, offer a **"Save to catalog"** option. Checked, it
  *also* creates a `ServiceItem` (saved work item) from `{ name, RateScheme,
  modifiers }` (no qty — per Task 2) so it appears in the Add-Line search next time.
  The PlanTask is created either way; saving to the catalog is the extra.
- **Permission — do NOT gate on `can_manage_config`.** Today the saved-work catalog
  (the renamed `TaskTemplate`, in `apps/api/templates_config/views.py`) is
  `CanManageConfig`-only. Decouple the catalog **create** so a Plan-builder (the same
  authenticated / job-manager users who author PlanTasks) can save inline. Align the
  catalog's ownership with **Inventory's** broader model
  (`CanManageFinancialsOrConfig`, `apps/api/inventory/views.py`) rather than
  config-only — the user plans to move the ServiceItems catalog **out of the
  config/Settings area** entirely (like Inventory did), so don't tie this to config.
- Tests: a user **without** `can_manage_config` can save a free-text task to the
  catalog inline, and it then appears in the Add-Line search.

> **Scope note:** the full *relocation* of the ServiceItems catalog out of Settings
> into its own area (mirroring Inventory) is a related but larger change — out of
> scope here. This task only ensures inline create is not config-gated.

## Done-when
- "Add Line" searches **saved work items + goods** (not rate cards); picking either
  creates the right atom; free text forks into work (attach a RateScheme) or a one-off
  material.
- The template (ServiceItem) no longer carries a default qty; generated PlanTasks
  start at qty 1.
- A free-text task can be **saved to the ServiceItems catalog inline**, available to
  Plan-builders **without** `can_manage_config`.
- Full backend (fresh build) + frontend suites green.

## Out of scope
- The bundle/"template group" case (deferred — design §9/§15.2).
- Adjustments, the Estimate-pillar work, line-item slimming (later phases).

## Decisions (from the user)
- Search surface = **ServiceItems (saved work) + InventoryItems** (rate cards are
  *attached*, not searched).
- **Drop the template default qty** — magnitude is always per-job; generated tasks
  start at qty 1.
- One unified "Add Line" modal (trying unified; splitting Tasks/Materials back out is
  the fallback — design §13).
- **Inline "save to catalog"** when writing a free-text task — and the ServiceItems
  catalog *create* is **not** gated on `can_manage_config` (align with Inventory's
  ownership; the catalog is expected to leave the config area, like Inventory did).
