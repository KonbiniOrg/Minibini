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
| 0 | **RateScheme/ServiceItem rename** | `phase0-ratescheme-serviceitem-rename.md` | **DONE** (4 commits; rate card→`RateScheme`, saved-work→`ServiceItem`) |
| 1 | **"Add Line"** rework | `phase1-add-from-price-list.md` | **DONE** (search ServiceItems[saved work] + InventoryItems; free-text → attach RateScheme / one-off material; inline save-to-catalog, not config-gated; dropped template default qty) |
| 2 | Estimating starts on the Plan | `phase2-plan-first-and-express.md` | **DONE** (Start Estimate creates the Plan directly; create-worksheet page removed) |
| 3 | UI vocabulary + single-view Estimate pillar | `phase3-vocabulary-and-estimate-pillar.md` | **DONE** |
| 4 | Re-projection / out-of-sync flag | `phase4-reprojection-change-marker.md` | **DONE, then SIMPLIFIED** — shipped snapshot-based states + re-pull/keep-mine, then reverted (per user) to a **live "out of sync with atoms" check** on Client View + wizard; no snapshot (migration 0034 removed) |
| 5 | Combined Tasks & Materials pillar | `phase5-combined-tasks-materials-pillar.md` | **DONE** |
| 6 | Remove direct line authoring + Phase B | `phase6-remove-direct-line-authoring.md` | **revised 06-27 — NEXT**; estimate-only (**invoice deferred**) |
| 7 | Slim line-item fields | `phase7-slim-line-item-fields.md` | revised 06-27 (migration); estimate-side `source_template` only — `inventory_item` deferred with invoicing |
| 8 | Job-scoped adjustments | `phase8-job-scoped-adjustments.md` | revised 06-27, least-decided |
| 9 | Seed data (nealsdata) | `phase9-seed-data-update.md` | revised 06-27 (rename already in nealsdata; shape + regen left) |
| 10 | Rewrite the durable docs | `phase10-docs-rewrite.md` | revised 06-27, last |

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
- **Phases 0–5 are shipped.** Next functional phase is **Phase 6** — estimate-only:
  remove the Client-View direct line authoring + Phase B; **invoice authoring removal
  is deferred** (focus on getting the estimate right first).
- **Phase 7** removes `EstimateLineItem.source_template` now; the shared
  `inventory_item` field waits for the deferred invoice work (still read invoice-side).
- **Phase 8** (job-scoped adjustments) still wants a design pass before it's turnkey.

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
