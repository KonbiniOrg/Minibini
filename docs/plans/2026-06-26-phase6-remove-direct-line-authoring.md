# Phase 6 — The Estimate (Client View) becomes a pure projection (remove direct line authoring + Phase B)

> **Revised 2026-06-27** to match what's been built. Changes from the original:
> - **Names updated:** rate card = `RateScheme`, saved-work catalog = `ServiceItem`
>   (the Phase-0 rename is done). "Add from Price List" is now **"Add Line"** on the
>   Plan; goods are `InventoryItem`.
> - **Estimate-only now; invoice parity deferred.** Per the user's call, we focus on
>   getting the **estimate (Client View)** right first and leave the **invoice**
>   equivalent for a later phase. This is a deliberate, temporary departure from the
>   design's "estimate and invoice change together (don't fork)" rule — we fork on
>   purpose and reunify when invoicing is tackled.
> - **Reprojection is a live check, not a snapshot.** The earlier snapshot/
>   reconcile/`reprojection_state` model was removed; a line that no longer matches
>   its atoms is flagged live ("⚠ out of sync with atoms") on both the Client View
>   and the wizard. Nothing in this phase reintroduces snapshots.

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §5.2/§5.3/§5.4 + §14 step 5. Backend + frontend.

**Goal:** Stop letting a unit of work *originate* on the customer **Estimate (Client
View)**. Remove the **"Add Line Item"** authoring (manual entry + the price-list/PLI
variant) on `EstimateDetailPage` and the wizard's "Create Manual Line Item"; and
remove the dormant **Phase B** carry-over (line-item → Task/Material). Estimate lines
then come only from **atoms** (the wizard / "Show Client View" projection) plus
**adjustments** (which stay for now). Editing *existing* projected lines (re-price,
rename, regroup) and reordering **stay** — design §8 "trust the user."

**Depends on:** Phases 1–2 (atoms-first Plan flow exists, incl. the Plan's one-off
paths — see Decisions) so removing Client-View authoring doesn't strand users.
**Sets up** Phase 7 (slim fields) — but only the *estimate-side* readers go away here
(invoice still authors lines, so its `inventory_item` usage remains until the
deferred invoice phase; Phase 7 must account for that).

## Global constraints
- No model field removal here (that's Phase 7) — this removes *usage*. No migrations.
  Never write the dev DB; backend tests on the test DB, one process. Svelte 5 runes;
  frontend `npm run test:run`. **Gate on the real `OK`/`FAILED` summary, never a
  piped exit code** (see CLAUDE.md).
- **Keep**: the wizard (atoms→lines), `update_line_item`/`delete_line_item`/reorder
  on existing estimate lines, **Add Adjustment** (document-scoped until Phase 8),
  Phase A carry-over, Change Orders (CO lines are direct-authored deltas — untouched).
- **Do NOT touch invoicing in this phase** (deferred — see below).

## Reference (from exploration; re-verify at execution)
- Estimate authoring (REMOVE): `frontend/src/routes/estimates/EstimateDetailPage.svelte`
  "Add Line Item" → `LineItemModal.svelte`; endpoints `POST /api/estimates/{id}/line-items/`
  (manual) and the PLI variant; services `EstimateService.add_line_item` and
  `add_line_item_from_pli` (`apps/estimates/services.py`). Wizard "Create Manual Line
  Item" in `EstimateWizardPage.svelte`.
- Phase B (REMOVE): `apps/estimates/carry_over.py` — Phase A (materialize worksheet)
  then **Phase B** (`_create_task_from_line_item` via `source_template`,
  `_create_material_from_line_item` via `inventory_item`). Invoked by the
  `estimate_accepted` signal (`apps/estimates/signals.py`).
- Tests: `tests/test_atom_carry_over.py` (Phase A + the Phase-B `CarryOverFromDirectLineItemsTest`),
  `tests/test_api_estimates.py` (line-item CRUD).
- Invoice authoring (DEFERRED — leave as-is): `InvoiceService.add_line_item`,
  `addManualLineItem()` in `InvoiceWizardPage.svelte`.

## Tasks (TDD)

### Task 1 — Remove Phase B carry-over
Delete the Phase-B loop + `_create_task_from_line_item` + `_create_material_from_line_item`
from `carry_over.py`; `carry_over_for_estimate` keeps only Phase A. Remove/replace
the `CarryOverFromDirectLineItemsTest` cases; keep Phase A tests green.

### Task 2 — Remove estimate direct line authoring
Remove `EstimateService.add_line_item` (manual) and `add_line_item_from_pli`, their
endpoints, and the "Add Line Item"/`LineItemModal` UI on `EstimateDetailPage` + the
wizard's "Create Manual Line Item". Keep `update_line_item`, `delete_line_item`,
reorder, and **Add Adjustment**. Update/remove the corresponding tests.

### Task 3 — Sweep + gate (estimate scope)
Grep for remaining callers/links to the removed estimate paths (serializers, routes,
fixtures, components). Full backend + frontend suites green (read the real summary).

## Deferred to a later "invoice projection" phase (NOT now)
- Removing invoice direct line authoring (`InvoiceService.add_line_item`,
  `addManualLineItem()`) for parity, and reunifying estimate+invoice behavior.
- Any invoice-side field slimming that depends on it.

## Out of scope
- Removing now-unused model fields (`source_template`, line `inventory_item`) — **Phase 7**
  (and only the estimate-side readers are gone after this phase; invoice still reads
  `inventory_item` until the deferred invoice phase).
- Converting adjustments to job-scoped — **Phase 8** (they stay document-scoped here).

## Decisions
- **One-off / free-form lines — resolved on the Plan.** Phase 1 added, on the **Plan**,
  an **"Add custom task"** (type a description + attach a `RateScheme`) and an
  **"Add freeform material"** (one-off `PlanMaterial`: qty + units + direct price + AC).
  So arbitrary work/goods can still be authored — as **atoms on the Plan** — and then
  projected. Removing manual authoring on the **Client View** therefore doesn't strip
  the escape hatch; it just moves authoring to the Plan where it belongs. (The deferred
  **Fee** atom, design §15.1, remains the clean home for a pure one-off charge.)
- Per-task "+mat" and worksheet-side adds stay (those are *atom* authoring on the Plan,
  not document authoring).
