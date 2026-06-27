# Phase 10 — Rewrite the durable docs to the consolidated model

> Design draft §14 step 9. Documentation only — no code. Do this **last**, once
> Phases 3–9 have settled, so the docs describe what actually shipped.

**Goal:** Bring the durable `docs/designs/` references (and `ui-flows`) in line with
the consolidated model: the Plan / Client View / Estimate vocabulary, atoms-only
authoring (documents are pure projections), the two-action add surface + Price List,
the single-view Estimate pillar + re-projection marker, the combined Tasks &
Materials pillar, removed direct line authoring + Phase B, slimmed line items, and
job-scoped adjustments.

**Depends on:** whatever of Phases 3–9 actually shipped (document the real end
state, not the plan).

## Global constraints
- Docs only. Keep the project's doc conventions (per CLAUDE.md: `docs/designs/` is
  the durable record; `docs/plans/` is disposable). Update, don't duplicate.
- Verify every claim against the code as it stands when writing (the reviewers in
  earlier phases checked code-vs-doc; do the same here).

## Targets (from CLAUDE.md's topic-doc table)
- `docs/designs/estimates-and-prices.md` — Plan/Client View, atoms→projection, the
  Price List add surface, ServiceItem, adjustments (job-scoped), re-projection
  marker, supersession (one Plan → many Client Views).
- `docs/designs/jobs-tasks-and-worksheets.md` — the Plan (worksheet) as build view,
  "Start Estimate" entry, get-or-create (one Plan per job), the combined Tasks &
  Materials pillar, the Estimate pillar toggle.
- `docs/designs/invoicing-and-expenses.md` — invoice = projection of Job
  Task/Material/Expense atoms, no direct authoring, job-scoped adjustments
  auto-apply, the retired agreement-adjustments panel.
- `docs/designs/architecture-and-conventions.md` — if the line-item/service-layer
  patterns changed (slimmed line items; the "all CRUD through a service" chokepoint
  still holds; projection model).
- `docs/designs/materials-inventory-and-purchasing.md` — confirm the
  PLI-on-line-item removal is reflected; materials reach documents only as atoms.
- `docs/ui-flows/` — update the estimate/worksheet/invoice flow docs (the Price List
  picker, Start Estimate, the pillar toggle, projection verbs).
- `docs/designs/LATER.md` — fold in / clear any items resolved by these phases;
  capture anything deferred (the Fee atom, billing groups, invoice-only adjustments).

## Tasks
1. Rewrite `estimates-and-prices.md` and `jobs-tasks-and-worksheets.md` (the core of
   the change), verifying against code.
2. Rewrite `invoicing-and-expenses.md` for projection + job-scoped adjustments.
3. Touch up `architecture-and-conventions.md`, `materials-inventory-and-purchasing.md`,
   and `ui-flows/` for the consolidated surfaces.
4. Reconcile `LATER.md` and retire/refresh the design draft
   (`2026-06-24-planning-billing-consolidation-draft.md`) — mark which phases shipped,
   or move its durable content into the designs and delete the draft per the
   docs/plans-is-disposable convention.

## Out of scope
- No code changes. If writing reveals a code/doc mismatch that's a real bug, log it
  (LATER or a new spec) rather than fixing it inline.

## Decisions to confirm
- Whether to keep the design draft as a historical artifact or fold it into the
  durable docs and delete it (lean: fold + delete once the designs are updated).
