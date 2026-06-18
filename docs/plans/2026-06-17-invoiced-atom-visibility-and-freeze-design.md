# Invoiced-atom visibility + freeze — design

**Date:** 2026-06-17
**Branch:** feature/invoiced-atoms
**Status:** design, pending implementation plan

## Problem

The system already knows which billable atoms (Task work, Materials, Expenses)
have been attached to an invoice — but that knowledge is buried inside the
invoice wizard. On the job views (starting with the overview) there is no way to
see that a Task or Material has already been billed.

Worse, the underlying data lets an atom's billed amount **drift after it's been
invoiced**: a Task's billing inputs and a Material's `sell_price` are editable
even once the atom is on an invoice. The invoice line item itself is a snapshot
and does not change, but the atom's "I've been invoiced" mark becomes a lie when
its current computed amount no longer matches what was billed.

This feature does two things:

1. **Visibility** — surface a per-atom "Invoiced" indicator (a link to the
   invoice) on the job overview's Tasks and Materials & Expenses pillars.
2. **Integrity** — guarantee that an invoiced atom can never change its billed
   amount, by combining lifecycle gates (when an atom *becomes* billable) with
   freezes (what locks once it's billed).

## How "invoiced" is recorded today (background)

There is **no flag on the atom and no FK** from Task/Material/Expense to an
invoice line. The single source of truth is the join table
**`InvoiceLineItemSource`** (`apps/invoicing/models.py:160`), keyed on
`(source_type, source_pk)` with a DB-level `unique_together` on that pair. An
atom is "invoiced" iff a row exists in that table pointing at it via a
**non-cancelled** invoice. The `unique_together` makes splitting an atom across
invoices physically impossible: one atom → at most one line item → one invoice,
so the "link to the invoice" is always unambiguous.

Invoice line items are `BaseLineItem`s that store their own `qty`/`units`/`price`
written once at creation (`apps/core/wizard.py:242`); the invoice total
aggregates those stored values (`apps/jobs/financials.py:135`). The only
re-derivation from atoms (`_resync_in_sync_line_item`) is gated to `DRAFT`
invoices (`_validate_draft`). So **a sent invoice's amounts never mutate** — the
drift we care about is the atom's mark becoming inaccurate, not the invoice
document changing.

## The unified invariant

> Once an atom has a non-cancelled `InvoiceLineItemSource`, it is read-only on
> every field that feeds its billed amount.

Each atom type reaches that invariant differently, because each becomes billable
at a different lifecycle point.

| Atom | Billable when | Frozen by |
|---|---|---|
| **Task** | `status == complete` | **Completion** freezes the whole task (terminal, no reopen) — bleps and all fields. Invoiced ⟹ complete ⟹ already frozen, so no invoice-specific task freeze is needed. |
| **Material** | `consumption_state == consumed` | `consumed` already locks quantity (restock/draw_more require `pending`). The invoice freeze adds: block `sell_price` edits and block `unconsume`. |
| **Expense** | submitted & not rejected (money already spent — billable immediately) | **Already implemented**: `ExpenseService._assert_not_invoiced` blocks all edits while the expense (or its linked material) is on a non-cancelled invoice. No new freeze code. |

### Why these specific gates

- **Task — freeze everything on complete.** `complete` is terminal
  (`STATUS_COMPLETE: []`, `apps/jobs/models.py:330`); there is no reopen and a
  complete task cannot be cancelled. We deliberately freeze *all* of the task on
  completion (not a two-stage complete-then-invoice freeze). Rationale: the rule
  is trivial to explain ("a complete task is done — done working, done
  editing"), and error-correction is still fully available because **invoice
  line items are independently editable** — the atom values are only the
  *starting defaults* for invoicing. No reopen path is built; if one is ever
  needed it can be added later.
- **Material — billable ⟺ consumed.** Task-attached materials auto-consume when
  their task *starts* (`apps/jobs/services.py:984`, `:1181`); task-less
  materials are consumed manually. This matches reality: a material is "used up"
  (and its quantity locked) at task start, well before the labor finishes — so
  materials legitimately become billable earlier than their parent task's
  labor. A `pending` (undrawn) material is not billable.
- **Expense — no readiness gate.** Unlike work-to-be-done (task) or
  stock-to-be-drawn (material), an expense is a sunk cost that is real the
  instant it's submitted. Rejected expenses simply never enter the pool. So
  expenses get **no greyed "not billable yet" state**.

### Deletion integrity (already covered — no work)

An invoiced atom must not be deleted out from under its source row (the source
is keyed by `source_pk`, not a real FK, so a delete would orphan it). This is
already prevented by existing state rules:

- Invoiced ⟹ task `complete` ⟹ `delete_task` refuses it (and it can't be
  cancelled — terminal). Safe.
- Invoiced ⟹ material `consumed`; `Material.destroy` is disabled (405,
  `apps/api/inventory/views.py:120`) and every deletion path
  (`restock`-to-zero, `sever`, expense rejection) requires `pending`. Safe.

## Scope

### Part 1 — Centralize the "is invoiced" predicate

Create one helper in the invoicing layer (e.g. `InvoiceClaimService`):

- `is_invoiced(atom)` → bool — does a non-cancelled `InvoiceLineItemSource`
  reference this atom? (mirrors the existing
  `ExpenseService._assert_not_invoiced` filter)
- `claims_for_job(job)` → `{(source_type, source_pk): {invoice_id, invoice_number}}`
  in **one query**, for the no-N+1 indicator.

Refactor `ExpenseService._assert_not_invoiced` to use the shared predicate
(preserving its expense-or-linked-material behavior). This is the single source
of truth used by the freeze guards, the wizard billability gate, `get_source_pool`,
and the indicator.

### Part 2 — Freeze enforcement

- **Task:** `TaskService.update_task` (`apps/jobs/services.py:883`) rejects edits
  to a `complete` task — **except `sort_order`** (list position is cosmetic and
  unrelated to work/billing; freezing it would block reordering any list
  containing a complete task). Both blep-creation paths (`create_historical` and
  the live-start path) reject a `complete` task.
- **Material:** once a material has a non-cancelled invoice source:
  - `MaterialService.update_pricing` (`apps/inventory/services.py:564`) rejects
    `sell_price` changes.
  - The freeform `partial_update` path
    (`apps/api/inventory/views.py:159`) rejects amount-affecting field changes.
  - `MaterialService.unconsume` (`apps/inventory/services.py:677`) is blocked,
    and `TaskLifecycleService.cancel_work` refuses (or is guarded) when any of
    the task's materials are invoiced.
- **Expense:** already done (`_assert_not_invoiced`); no change beyond the
  refactor in Part 1.

### Part 3 — Wizard billability gates

In `InvoiceWizardService.get_source_pool` (`apps/invoicing/services.py:438`) and
the add-atoms write path (defense in depth — the wizard isn't guaranteed to be
the only caller):

- **Task atoms:** a new atom state `not_billable` with reason "task not
  complete" for non-`complete` tasks. Shown **greyed / non-selectable** in the
  wizard (mirroring the existing `claimed_by_other` shown-but-disabled pattern),
  **not hidden**. The task's child materials remain listed independently.
- **Material atoms:** `not_billable` with reason "not consumed" for `pending`
  materials. Greyed / non-selectable.
- **Expense atoms:** unchanged (no readiness gate).
- The add-atoms write path rejects a non-`complete` task or non-`consumed`
  material.

### Part 4 — Indicator API

Add an `invoice` field (`null`, or `{id, number}`) to:

- `TaskSerializer` (`apps/api/tasks/serializers.py`)
- `MaterialSerializer` (`apps/api/inventory/serializers.py`)
- the Expense serializer (loose/material-less expenses)

Fed by `InvoiceClaimService.claims_for_job(job)` built once in `JobSerializer`
and passed via serializer context. The atom serializers read from context when
present and emit `null` otherwise — so expanding to the task list / task detail
later is just "pass the same context." No N+1.

### Part 5 — Overview UI (`frontend/src/components/jobs/JobDetail.svelte`)

- **Tasks pillar:** render an "Invoiced" marker on any task carrying an
  `invoice`, as a link to `#/invoices/{id}` (links navigate, per UI conventions).
- **Materials & Expenses pillar:**
  - Material rows: same "Invoiced" link when the material carries an `invoice`.
  - Material-linked expenses already annotate their material row; the link lives
    on the material (the expense isn't separately billable).
  - Loose (material-less) expense rows: the "Invoiced" link when the expense
    carries an `invoice`.
- Atoms without an `invoice` are unmarked.

### Part 6 — Detail the sources on a line item (display only)

Today a line item's Source column shows only a count — `"N atom(s)"` — from
`sourceLabel` in the shared `frontend/src/components/LineItemTable.svelte:23`.
The full per-source detail is **already serialized** and sent to the client
(`InvoiceLineItemSourceSerializer`, `apps/api/invoicing/serializers.py:22`):
each `li.sources[]` entry carries `source_type`, `source_pk`, `description`, and
`computed_amount`. The frontend just collapses it to a count.

Change: replace the count with a **stacked list** — one source per row under the
line, showing the atom's `description` and its `computed_amount`. This is a
**pure frontend change**; no backend, no new query, no serializer work.

Notes:

- `LineItemTable.svelte` is **shared**: both the invoice detail page and the
  estimate detail page render it with `showSource={true}`. The estimate source
  serializer (`apps/api/estimates/serializers.py:7`) exposes the identical
  `source_type` / `description` / `computed_amount` shape, so this improves both
  detail views at once with no extra work.
- Fallback: if the stacked list reads as too heavy in practice, fall back to a
  compact comma-joined list of descriptions. (Decision: ship the stacked list
  first; the comma-join is the cheap retreat.)
- `"No source"` (manually-authored line items with no atoms) is unchanged.

## Out of scope

- Expanding the indicator to the task list / task detail pages. The serializer
  context approach is built to make this a trivial follow-up, but it is not in
  this pass (overview first; expand after confirming the read).
- A reopen-from-complete transition for tasks (not built; revisit only if the
  no-correction-window assumption proves wrong).
- Distinguishing draft vs. finalized/sent invoices in the indicator — the mark
  is binary ("on a non-cancelled invoice").

## Testing (TDD)

Backend (`tests/`, run singly — never parallel):

- `InvoiceClaimService.is_invoiced` / `claims_for_job` correctness, including
  cancelled-invoice exclusion and the expense-or-linked-material case.
- Task freeze: `update_task` rejects field edits on a complete task; `sort_order`
  still allowed; both blep paths reject a complete task.
- Material freeze: `update_pricing` and freeform `partial_update` reject
  `sell_price` on an invoiced material; `unconsume`/`cancel_work` blocked when
  invoiced.
- Wizard: `get_source_pool` marks non-complete tasks and pending materials
  `not_billable`; child materials of a non-complete task still appear; add-atoms
  rejects non-complete task / non-consumed material.
- Serializers: `invoice` field is `null` vs `{id, number}` correctly; no N+1
  (assert query count).
- Expense freeze refactor preserves existing behavior.

Frontend (`frontend/tests/`, Vitest):

- `JobDetail.svelte` renders the "Invoiced" link on invoiced tasks, materials,
  and loose expenses, and omits it otherwise; link targets `#/invoices/{id}`.
- `LineItemTable.svelte` renders the stacked per-source list (description +
  amount) when `showSource` and `li.sources` is non-empty; `"No source"` when
  empty. Covers both invoice and estimate line items.

## Docs to update on completion

- `docs/designs/invoicing-and-expenses.md` — the freeze invariant, billability
  gates, and the centralized claim predicate.
- `docs/designs/estimates-and-prices.md` — billable-atom billability gates
  (complete / consumed / submitted).
- `docs/designs/jobs-tasks-and-worksheets.md` — task freeze-on-complete; no
  bleps on complete tasks.
- `docs/designs/materials-inventory-and-purchasing.md` — material invoice freeze
  (sell_price, unconsume).
