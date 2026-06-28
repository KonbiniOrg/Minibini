# Phase 8 — Job-scoped, auto-applied adjustments

> **Revised 2026-06-27.** The rename is done: a "percentage ServiceItem" is now a
> **percentage `RateScheme`** (the AdjustmentModal already targets it — placeholder
> "Select a rate"). Independent of the estimate/invoice authoring work. Still the
> least-decided phase — treat as "shape + decisions to make with the user," not a
> turnkey plan; re-derive specifics when executing.

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §10 + §13. **This phase is the least-decided one — treat it as
> "shape + decisions to make with the user before execution," not a turnkey plan.**
> The design itself defers the granular bits "until there's a working instance."

**Goal:** Convert percentage adjustments from **document-scoped** (added per
estimate / per invoice) to **job-scoped + auto-applied** (design §10): you define
"this job has a 10% rush on category X" once, on the **Job**, and every document
(client views *and* invoices) auto-applies it, re-evaluated against that document's
own lines, removable/adjustable per document.

**Depends on:** the estimate/invoice projection being stable (Phases 1–7). This is
cross-cutting (estimate + invoice + agreement). **Biggest blast radius of the
remaining phases.**

## What exists today (document-scoped — from exploration)
- `adjustment_service` (FK PERCENTAGE ServiceItem) + `adjustment_target_categories`
  (M2M) on **both** `EstimateLineItem` and `InvoiceLineItem`.
- `apps/core/adjustments.py`: `compute_adjustment_amount(line, siblings)` =
  `(rate/100) * Σ(total_amount of non-adjustment siblings in the target AC set; empty
  = all)`; `recompute_adjustments(lines)` auto-runs after any line mutation (via
  `LineItemService.save_line_item`).
- `POST /api/{estimates|invoices}/{id}/adjustment-lines/` + `AdjustmentModal.svelte`
  add a per-document adjustment line.
- `compose_agreement` (`apps/estimates/agreement.py`) carries adjustment metadata
  from accepted-estimate lines; `GET /api/invoices/{id}/agreement-adjustments/` +
  `AgreementAdjustmentsPanel.svelte` let the invoice pull the estimate's adjustments
  (the current carry-over mechanism — to be **replaced** by job-scoped auto-apply).
- **No Job-level adjustment exists.** `Expense` (`apps/expenses/models.py`) is the
  precedent for a job-level billable item (job FK, amount/rule, AC, status).

## Proposed shape (confirm before building)
- New model **`JobAdjustment`**: `job` FK, `adjustment_service` (PERCENTAGE
  ServiceItem), `target_categories` M2M, maybe `active`. The *rule*, stored once.
- Each document **auto-materializes** an adjustment line per JobAdjustment when it's
  projected/recomputed, computed against that document's own non-adjustment lines
  (reuse `compute_adjustment_amount`). While draft → recompute; on send → freeze
  (as today). Keep the line-item `adjustment_service`/`target_categories` fields as
  the **materialized** representation (so a document still renders an adjustment
  line) — they're now *generated from the job rule*, not hand-added.
- **Per-document override/waive**: a way for one invoice to drop or change the
  auto-applied adjustment (design: "the user can always remove or adjust it on any
  given invoice"). Likely a per-document suppression/override record keyed by
  (document, JobAdjustment).
- **Authoring**: `AdjustmentModal` now creates/edits a **JobAdjustment** (still
  picking a percentage ServiceItem from the Price List, where users look). Surfaced
  at the Job level and/or from the Client View (attaches to the Job either way).
- **Retire** the per-document add-adjustment endpoints, the agreement-adjustments
  panel/endpoint, and the compose_agreement adjustment-from-estimate-line path —
  superseded by job-scoped auto-apply.

## Tasks (TDD) — high level; refine after the design decisions below
1. **`JobAdjustment` model** (+ migration; fresh-build test run) + service to
   list/create/update/delete a job's adjustments.
2. **Auto-apply on projection/recompute** for the Client View: materialize/refresh
   adjustment lines from the job's rules against the document's lines; freeze on send.
3. **Auto-apply on the Invoice** likewise (replaces the agreement-adjustments pull).
4. **Per-document waive/override** mechanism + endpoints.
5. **Authoring UI**: repoint `AdjustmentModal` to JobAdjustment; surface at the Job;
   render auto-applied lines with their job origin + the per-document waive control.
6. **Rework `compose_agreement`**: adjustments come from job rules (and accepted
   COs), not estimate lines. Update the agreement tests.
7. **Remove** the old per-document add-adjustment endpoints + agreement panel +
   their tests; migrate any data shape in nealsdata (coordinate with Phase 9).
8. Full backend (fresh build) + frontend suites green.

## Out of scope (design §13 — explicitly deferred)
- Invoice-only adjustments that never touch the job (the design defers this; revisit
  with a working instance). Finer per-document granularity. Stacking.

## Decisions to confirm (do this with the user first)
- **Materialized lines vs computed-on-read.** Store generated adjustment lines per
  document (freezes naturally on send, reuses existing rendering) vs compute them
  purely at read time (no stored line). Lean: **materialize** (matches the
  freeze-on-send model and the existing line-item rendering).
- **Where JobAdjustment is authored** (Job page vs Client View, attaching to Job).
- **Waive/override representation** (per-document suppression record vs a per-document
  copy the user can edit).
- **Migration of existing document-scoped adjustments** — pre-prod, so likely
  regen-from-spreadsheets (Phase 9) rather than a data migration; confirm.
- Whether to split this into "model + auto-apply (estimate)" first, then "invoice +
  retire-old + agreement" second, given the size.
