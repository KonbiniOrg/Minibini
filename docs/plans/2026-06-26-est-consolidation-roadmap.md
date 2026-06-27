# Estimate Consolidation — phase roadmap

Index of the implementation plans executing the design draft
`2026-06-24-planning-billing-consolidation-draft.md`. **Phases 1–3 are shipped** on
`feature/est-consolidation`; the rest are planned.

> ⚠️ **2026-06-27 design revision — read this first.** The design draft was reworked:
> - **Naming swap.** The rate card reverts `ServiceItem` → **`RateScheme`**; the
>   saved-work-item `TaskTemplate` → **`ServiceItem`** (the *salable concept* you add).
> - **Add model.** One **"Add Line"** action: type → type-ahead over **ServiceItems
>   (saved work) + InventoryItems (goods)** → pick (→ PlanTask / PlanMaterial); free
>   text → modal fork into **work** (attach a `RateScheme` via a plain select) or a
>   **one-off material** (freeform, direct price). A `RateScheme` is the *rate you
>   attach*, never a thing you search.
> - **Line concept.** Every line = a salable concept + qty + price; price source
>   differs (materials: our **purchase price** + auto markup; work: the RateScheme
>   **sell** rate).
> - **The rename is now proposed as an EARLY phase** (Phase 0), reversing the earlier
>   "defer all renames" stance.
>
> **The phase docs below — especially 6–10 — predate this revision** and use the OLD
> names + add-model. Read them through the design draft; their names/specifics are
> stale until refreshed. The built **Phase-1 picker is superseded** (rebuild to "Add
> Line").

## Status

| # | Phase | Doc | Status |
|---|---|---|---|
| 0 | **RateScheme/ServiceItem rename** (rate card `ServiceItem`→`RateScheme`; `TaskTemplate`→`ServiceItem`) | _(plan TBD — write next)_ | **CONFIRMED — do FIRST** |
| 1 | **"Add Line"** (rework of the built picker) | `phase1-add-from-price-list.md` | built picker shipped; **rework spec written** (search ServiceItems[saved work] + InventoryItems; free-text → attach RateScheme / one-off material; drop template default qty). **Next functional phase, after Phase 0.** |
| 2 | Estimating starts on the Plan | `phase2-plan-first-and-express.md` | **DONE** (+ later: Start Estimate creates the Plan directly; create-worksheet page removed) |
| 3 | UI vocabulary + single-view Estimate pillar | `phase3-vocabulary-and-estimate-pillar.md` | **DONE** |
| 4 | Re-projection "underlying changed" marker | `phase4-reprojection-change-marker.md` | planned (migration) |
| 5 | Combined Tasks & Materials pillar | `phase5-combined-tasks-materials-pillar.md` | planned |
| 6 | Remove direct line authoring + Phase B | `phase6-remove-direct-line-authoring.md` | planned — **predates 06-27** |
| 7 | Slim line-item fields | `phase7-slim-line-item-fields.md` | planned — **predates 06-27** (migration) |
| 8 | Job-scoped adjustments | `phase8-job-scoped-adjustments.md` | planned — **predates 06-27**, least-decided |
| 9 | Seed data (nealsdata) | `phase9-seed-data-update.md` | planned — **predates 06-27** |
| 10 | Rewrite the durable docs | `phase10-docs-rewrite.md` | planned — **predates 06-27**, last |

## Dependencies / suggested order
- **Phase 0 (the rename) first** if we accept the early-rename proposal — then
  everything below reads with the right names. Confirm before it leapfrogs functional
  work.
- **Rework the Phase-1 picker** into "Add Line" (search ServiceItems[saved work] +
  InventoryItems; free-text → attach a RateScheme, or a one-off material) — supersedes
  the built picker. Sequence relative to Phase 0 (do the rename first so the picker is
  built with the right names).
- 3 ✅; 5 (edits `JobDetail`); 4 independent; **6 → 7** (remove field *use* before the
  fields); 8 after projection is stable; 9 after the model changes; 10 last.

## Where to focus review
- **Naming swap (Phase 0) — CONFIRMED, do first.** Then the "Add Line" rework
  (Phase 1) uses the new names. Phase 0 plan to be written next.
- **Phase 8** (adjustments) still wants a design pass before it's turnkey; **Phase 6**
  manual-line removal; **Phase 7** `inventory_item` Option A vs B (lean A).

## Deferred (design draft §15)
- Fee atom (one-off charges); billing groups (N work atoms → one fixed line);
  invoice-only / finer adjustment controls (§13).

## Constraints (every phase)
- Never write the dev DB (test DB only; **fresh build after any migration** —
  `feedback_fresh_db_after_migrations`). One test process at a time. Frontend:
  `cd frontend && npm run test:run`.
- The **RateScheme/ServiceItem rename moves early** (Phase 0). The other renames stay
  deferred: `EstWorksheet`→Plan and `Estimate`→Client View are UI *labels* today;
  table renames can wait. Mapping: backend `EstWorksheet` = Plan, `Estimate` = Client
  View.
- Nothing merged/pushed/PR'd automatically (per the user's standing instruction).
