# Phase 6 — Documents become pure projections (remove direct line authoring + Phase B)

> ⚠️ **Predates the 2026-06-27 design revision.** Names here use the OLD mapping (rate
> card = `ServiceItem`, work catalog = `TaskTemplate`); the design draft now swaps
> these (rate card → `RateScheme`, saved work item → `ServiceItem`) and reshapes the
> add surface ("Add Line"). Read against
> `2026-06-24-planning-billing-consolidation-draft.md`; re-derive specifics when
> executing.

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §5.2/§5.3/§5.4 + §14 step 5. Backend + frontend. **Both estimate and
> invoice change together** (design's "do not fork" rule).

**Goal:** Stop letting a unit of work *originate* on a customer document. Remove the
**"Add Line Item"** authoring (manual entry + "From Price List"/PLI) on the
**Client View (estimate)** and the equivalent **manual line** on the **Invoice**;
and remove the dormant **Phase B** carry-over (line-item → Task/Material). Lines
come only from atoms (the wizard / Show Client View) plus **adjustments** (which
stay for now). Editing *existing* projected lines (re-price, rename, regroup) and
reordering **stay** — design §8 "trust the user."

**Depends on:** Phases 1–2 (atoms-first flow exists) so removing authoring doesn't
strand users. **Sets up** Phase 7 (slim fields): once nothing authors via
`source_template` / line `inventory_item` and Phase B is gone, those fields have no
readers.

## Global constraints
- No model field removal here (that's Phase 7) — this removes *usage*. So no
  migrations in this phase. Never write the dev DB; backend tests on test DB, one
  process. Svelte 5 runes. Frontend `npm run test:run`.
- **Keep**: the wizard (atoms→lines), `update_line_item`/`delete_line_item`/reorder
  on existing lines, **Add Adjustment** (document-scoped until Phase 8), Phase A
  carry-over, Change Orders (CO lines are direct-authored deltas — untouched).

## Reference (from exploration)
- Estimate authoring: `frontend/src/routes/estimates/EstimateDetailPage.svelte` "Add
  Line Item" → `LineItemModal.svelte` (manual + PLI); endpoints `POST
  /api/estimates/{id}/line-items/` (manual) and the PLI variant; services
  `EstimateService.add_line_item` and `add_line_item_from_pli` (~services.py L361).
  Wizard "Create Manual Line Item" in `EstimateWizardPage.svelte`.
- Invoice authoring: `InvoiceService.add_line_item` (manual); `addManualLineItem()`
  in `frontend/src/routes/invoices/InvoiceWizardPage.svelte`.
- Phase B: `apps/estimates/carry_over.py` `AtomCarryOverService.carry_over_for_estimate`
  — Phase A (materialize worksheet, ~L29–41) then **Phase B** (~L43–50:
  `_create_task_from_line_item` via `source_template`, `_create_material_from_line_item`
  via `inventory_item`). Invoked by the `estimate_accepted` signal
  (`apps/estimates/signals.py` ~L109).
- Tests: `tests/test_atom_carry_over.py` (Phase A + `CarryOverFromDirectLineItemsTest`
  = Phase B), `tests/test_api_estimates.py` (line-item CRUD), invoice wizard tests.

## Tasks (TDD)

### Task 1 — Remove Phase B carry-over
Delete the Phase-B loop + `_create_task_from_line_item` + `_create_material_from_line_item`
from `carry_over.py`; `carry_over_for_estimate` keeps only Phase A. Remove/replace
the `CarryOverFromDirectLineItemsTest` cases; keep Phase A tests green. (This drops
the `line-item → Task` idea entirely.)

### Task 2 — Remove estimate direct line authoring
Remove `EstimateService.add_line_item` (manual) and `add_line_item_from_pli`, their
endpoints, and the "Add Line Item"/LineItemModal UI on `EstimateDetailPage` + the
wizard's "Create Manual Line Item". Keep `update_line_item`, `delete_line_item`,
reorder, and **Add Adjustment**. Update/remove the corresponding tests.

### Task 3 — Remove invoice direct line authoring (parity)
Mirror Task 2 on the invoice: remove `InvoiceService.add_line_item` (manual) +
`addManualLineItem()` in the invoice wizard; keep edit/delete/reorder + adjustments
+ the atoms wizard. Update tests.

### Task 4 — Sweep + gate
Grep for any remaining callers/links to the removed paths (serializers, routes,
fixtures, other components). Full backend + frontend suites green.

## Out of scope
- Removing the now-unused model fields (`source_template`, line `inventory_item`) —
  **Phase 7**.
- Converting adjustments to job-scoped — **Phase 8** (they stay document-scoped,
  still addable, here).

## Decisions to confirm
- **One-off / free-form lines:** removing manual + PLI authoring also removes the
  only way to type an arbitrary line. The design accepts this as a deliberate gap
  (§6.3; fallback = a `flat_fee` ServiceItem carried as a Task; clean fix = the
  deferred Fee atom). Confirm you're OK losing the manual-line escape hatch now, or
  whether to keep a minimal manual line until the Fee atom lands.
- Whether to keep the per-task "+mat" and worksheet-side adds (yes — those are
  *atom* authoring on the Plan, not document authoring; untouched).
