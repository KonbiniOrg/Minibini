# Estimate Consolidation — phase roadmap

Index of the implementation plans that execute the design draft
`2026-06-24-planning-billing-consolidation-draft.md` (its §14 sequencing). Phases 1–2
are **shipped** on `feature/est-consolidation`; Phases 3–10 are **planned, awaiting
review** (written 2026-06-26 overnight). One doc per phase.

## Status

| # | Phase | Doc | Status | Touches | Migration? |
|---|---|---|---|---|---|
| 1 | Add-from-Price-List picker (+ backend-search rework) | `2026-06-26-phase1-add-from-price-list.md` | **DONE** | frontend (+2 backend filters) | no |
| 2 | Estimating starts on the Plan (Start Estimate; idempotent worksheet) | `2026-06-26-phase2-plan-first-and-express.md` | **DONE** | backend + frontend | no |
| 3 | UI vocabulary + single-view Estimate pillar | `2026-06-26-phase3-vocabulary-and-estimate-pillar.md` | planned | frontend | no |
| 4 | Re-projection "underlying changed" marker | `2026-06-26-phase4-reprojection-change-marker.md` | planned | backend + frontend | **yes** (snapshot) |
| 5 | Combined Tasks & Materials pillar | `2026-06-26-phase5-combined-tasks-materials-pillar.md` | planned | frontend | no |
| 6 | Remove direct line authoring + Phase B carry-over | `2026-06-26-phase6-remove-direct-line-authoring.md` | planned | backend + frontend | no |
| 7 | Slim line-item fields | `2026-06-26-phase7-slim-line-item-fields.md` | planned | backend | **yes** |
| 8 | Job-scoped, auto-applied adjustments | `2026-06-26-phase8-job-scoped-adjustments.md` | planned | backend + frontend | **yes** |
| 9 | Seed data (nealsdata) to the new shape | `2026-06-26-phase9-seed-data-update.md` | planned | data/build | (fresh build) |
| 10 | Rewrite the durable docs | `2026-06-26-phase10-docs-rewrite.md` | planned | docs only | no |

## Dependencies (suggested order)
- **3, 4, 5** are largely independent frontend/feature work and can go in any order
  (3 and 5 both heavily edit `JobDetail.svelte` — sequence them, don't parallelize).
- **6 → 7**: remove the *use* of `source_template`/line-`inventory_item` (6) before
  removing the *fields* (7).
- **8** (job-scoped adjustments) is the biggest and least-decided; it can run after
  the projection is stable (post-6). It changes adjustment data shape.
- **9** (seed) runs after the model changes (6–8) so it matches the final shape.
- **10** (docs) runs last, documenting what actually shipped.

So a reasonable execution order: **3, 5, 4, 6, 7, 8, 9, 10** — but 3/5 intersect the
user's own `JobDetail`/process rework, so confirm before starting those.

## Where to focus the review (the real open decisions)
- **Phase 3 & 5 intersect your in-progress process/modal rework of `JobDetail`** —
  decide whether you want me to do these or you do them, to avoid collisions.
- **Phase 4** — snapshot location (per-source vs per-line); ship correctness core
  (Tasks 1–3) before the reconcile UX (4–5)?
- **Phase 6** — are you OK losing the manual/free-form line *now* (design accepts it
  as a deliberate gap; Fee atom is the deferred clean fix)?
- **Phase 7** — `inventory_item` Option A (leave the shared field, stop using on
  est/invoice) vs Option B (relocate to Change-Order only). Lean A.
- **Phase 8** — the whole shape (JobAdjustment model, materialize vs compute-on-read,
  per-document waive, retiring the agreement panel). This one wants a design pass
  with you before it's turned into a turnkey plan.

## Deferred (not phased — design draft §15)
- The **Fee** atom (one-off charges, Expense's revenue twin).
- **Billing groups** (N work atoms → one fixed line, e.g. the Setup fee).
- Invoice-only adjustments / finer adjustment controls (design §13).

## Constraints that apply to every phase
- Never write the dev DB (test DB only; `--keepdb` for fast iteration, but run a
  **fresh build** after any migration — `feedback_fresh_db_after_migrations`). One
  test process at a time. Frontend: `cd frontend && npm run test:run`.
- Backend object/db-table **renames stay deferred** to a final naming pass; UI uses
  the target labels (Plan / Client View / Estimate / Price List). Backend↔UI mapping:
  `EstWorksheet`=Plan, `Estimate`=Client View.
- Nothing merged/pushed/PR'd automatically (per the user's standing instruction).
