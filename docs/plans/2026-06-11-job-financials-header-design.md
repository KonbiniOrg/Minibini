# Job-header financial rollups — design

**Date:** 2026-06-11
**Status:** Approved for planning
**Branch:** feature/deliverablesagain (repurposed)

## Goal

Replace the four hardcoded `$—` placeholders in the job detail header with real
figures, and consolidate the job-board "Unpaid" card's overlapping numbers onto
the same definitions so there is **one source of truth** for job financials.

Header columns (left → right): **Estimate | Spent | Invoiced | Profit**.

(A fifth column, **Billable**, is intentionally deferred — see "Deferred:
Billable" below. The header shows four columns until it is defined.)

## Single source of truth

A new module `apps/jobs/financials.py` exposes one entry point:

```python
def compute_job_financials(job) -> dict  # {'estimated', 'spent', 'invoiced', 'profit'}  all Decimal
```

Pure, read-only aggregation across estimates / inventory / expenses / invoicing /
bleps. No DB writes. Like `ScheduleService`, it lives under `apps/jobs/` but reads
from several apps. Both the job-detail serializer and the board's Unpaid card
consume it, so the two surfaces can never drift.

## The four numbers

### Estimated

The agreement-or-best-guess total.

- `job.start_date is not None` (the immutable "ever reached Approved / an estimate
  was once accepted" marker — set on first transition to Approved, never cleared,
  and an accepted estimate keeps its `accepted` status even after the job is
  rejected/cancelled) → `compose_agreement(job)['grand_total']`
  (`apps/estimates/agreement.py`). This covers active-approved jobs and
  rejected/cancelled-after-approval jobs, with accepted-estimate + accepted-CO
  deltas already folded in.
- Otherwise (never approved — still draft/submitted, or rejected/cancelled without
  ever being accepted) → the highest-`version` estimate's line-item total
  (`Σ qty × price`); `Decimal('0')` if the job has no estimates. No change orders
  can exist in this branch (a CO's FK targets the accepted estimate).

### Spent

Cash outlay plus approximate labor cost:

1. **Expenses** — `Σ expense.amount` for `Expense.objects.filter(material__job=job)`,
   **excluding** `status == 'rejected'` (a rejected reimbursement is not money the
   shop spent on the job). All other statuses count.
2. **Consumed materials with no expense** — for materials on the job with
   `consumption_state == 'consumed'` and **no** rows in their reverse `expenses`
   relation, `Σ quantity × unit_cost` (`unit_cost` is cost, sourced from
   `PriceListItem.purchase_price`). Materials that were acquired via an expense are
   already represented by that expense; counting their cost too would double-count.
   Pending/earmarked materials are not spend yet and are excluded.
3. **Labor** — `Σ (blep elapsed hours) × average_labor_cost`, over **all** bleps on
   the job's tasks (`Blep.objects.filter(task__job=job)`), using `Blep.elapsed`
   (which counts a still-running blep up to now). `average_labor_cost` is a single
   new `Configuration` value (dollars per hour). Every logged hour costs the same
   configured amount regardless of the task's billing RateScheme — labor *cost* is
   about hours worked, not how the work is billed. Bleps on cancelled tasks still
   count; the hours were genuinely worked.

`Spent = expenses + consumed-material cost + labor cost`. The three buckets are
disjoint, so no double-counting.

### Invoiced

`Σ (qty × price)` of invoice line items across the job's invoices, **excluding**
invoices with status `draft`, `cancelled`, or `superseded`. (Drafts are not yet
issued; cancelled is void; superseded would double-count its replacement.)

### Profit

`Invoiced − Spent`. **Intentionally negative** for a job that has incurred
cost/labor but has not yet been invoiced — if the work is never billed, the shop is
genuinely out that cost, so the number is accurate at every job stage.

## New Configuration key

| Key | Meaning | Notes |
|---|---|---|
| `average_labor_cost` | Approximate labor cost in dollars per hour, applied to every logged blep hour. | String value, parsed to `Decimal`. Add to test `setUp()` and fixture files per CLAUDE.md. Stand-in until per-worker pay/cost rates exist; when they do, only the labor-cost lookup in `financials.py` changes. |

The board card's old labor proxy (`elapsed_hours × rate_scheme.rate / 2`) is
**removed** — it conflated billing price with cost and was wrong for non-hourly
schemes. All labor cost now goes through `average_labor_cost`.

## API / serializer wiring

`JobSerializer` (`apps/api/jobs/serializers.py`) gains four detail-only
`SerializerMethodField`s: `estimated_amount`, `spent_amount`, `invoiced_amount`,
`profit_amount`, each serialized as a string (matching the `agreement` action's
Decimal-as-string convention).

- They return `null` in list context (`view.action == 'list'`), exactly like the
  existing `latest_change_request` field, so the board list payload stays cheap.
- `compute_job_financials(obj)` is called **once** per detail render and memoized on
  the serializer instance so the four fields don't each recompute it.

## Board card consolidation

`BoardService._compute_profitability()` (`apps/jobs/services.py`) is replaced by a
call into `compute_job_financials`. The Unpaid card
(`frontend/src/components/board/UnpaidCard.svelte`) then shows, from the shared
source:

- **Spent** — now includes the `average_labor_cost`-based labor term.
- **Invoiced** (was "Billed") — drafts now excluded, matching the header. Relabel
  the card's "Billed" to "Invoiced" for consistency.
- **Profit** — now `Invoiced − Spent` from the shared module.

The card's per-invoice table and QBO-based **Total Due** are payment-tracking
concerns and are left untouched.

## Frontend (header)

`frontend/src/components/jobs/JobHeader.svelte` replaces the four hardcoded `$—`
cells with `Estimate | Spent | Invoiced | Profit`, reading
`job.estimated_amount` / `spent_amount` / `invoiced_amount` / `profit_amount`,
formatted as currency, falling back to `$—` when the field is `null`/absent (list
payloads, or a job with nothing to show). Profit shows its existing
green/red-by-sign treatment.

## Testing (TDD)

- `tests/test_job_financials.py` — unit tests for `compute_job_financials`:
  - Estimated: accepted-estimate-with-COs via `compose_agreement` vs.
    highest-version fallback; never-approved job; no-estimate job → 0.
  - Spent: expenses summed (rejected excluded); consumed non-expense materials at
    cost; the no-double-count case (consumed material that has an expense counts
    once, via the expense); labor = blep hours × `average_labor_cost`; pending
    materials excluded.
  - Invoiced: drafts/cancelled/superseded excluded; others summed.
  - Profit: `Invoiced − Spent`, including the negative-when-unbilled case.
- Serializer test: detail response includes the four fields; list response has them
  `null`.
- Board test: `_compute_profitability` (or its replacement) returns the shared
  numbers; Spent includes labor; invoice figure excludes drafts.
- Frontend Vitest: `JobHeader` renders provided amounts and falls back to `$—` when
  null; `UnpaidCard` renders the consolidated numbers.

## Deferred: Billable

Billable is **not** built in this iteration — its definition is unsettled. Two
candidate definitions to revisit later:

1. **Actuals only** — the same quantities/work basis as Spent, but valued at
   **selling** price instead of cost.
2. **Actuals + estimate** — the above, plus estimated prices for line items that
   don't have actuals yet.

When chosen, Billable slots into `compute_job_financials` as one more function and
one more header column (between Spent and Invoiced) with no rework to the other
four numbers.

## Docs to update on completion

- `docs/designs/jobs-tasks-and-worksheets.md` — job header financial rollups.
- `docs/designs/data-constraints.md` §1.1 — the `average_labor_cost` Configuration
  key.
- `docs/designs/data-constraints.md` (Job constraints) — record that
  `Job.start_date` is **load-bearing for the Estimated rollup**: it is the
  immutable "ever reached Approved / an estimate was once accepted" marker that
  `compute_job_financials` keys off to choose `compose_agreement` vs. the
  highest-version-estimate fallback. **If `start_date` is ever made
  clearable/removable/editable, the Estimated branch in `apps/jobs/financials.py`
  must be revisited** — a cleared `start_date` would silently flip an approved job
  back to the fallback path and misreport its Estimated total.
- `docs/designs/architecture-and-conventions.md` — if the detail-only-method-field
  memoization pattern is worth noting alongside `latest_change_request`.
