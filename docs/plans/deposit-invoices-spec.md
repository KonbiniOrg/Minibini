# Deposit Invoices — Design Spec (2026-07-25)

Branch: `feature/deposits`. Disposable spec; the durable record lands in
`docs/designs/invoicing-and-expenses.md` (and friends) when this ships.

## What a deposit is

A deposit is a non-taxable charge collected before work starts, covering no
atoms. The shop typically does no work until it's paid (the money buys
materials). Later, the paid deposit is **deducted in full** from one
subsequent invoice (final or progress) on the same job. The deposit amount is
always user-entered — no standard percentage or amount.

## Decisions (with rationale)

1. **The accounting category is the deposit indicator.** `AccountingCategory`
   gains an `is_deposit` boolean (default `False`). A line item is a deposit
   line iff its AC is a deposit category (and it isn't a deduction — see 2);
   an invoice *is* a deposit invoice iff it contains a deposit line. Nothing
   is stored on `Invoice` or `InvoiceLineItem` — one source of truth, no
   line-schema change. Draft-time recategorization toggling deposit-ness is
   coherent editing, not corruption: line CRUD is draft-only, so everything
   load-bearing (board pill from *sent*, credit atom from *paid*) reads
   frozen lines.
2. **Deduction lines are identified by their source row** —
   `InvoiceLineItemSource` with `source_type='deposit'`,
   `source_pk=<deposit InvoiceLineItem pk>` — exactly how task/material
   lines are identified today. A deduction carries the same (deposit) AC as
   its source, so deposit-line tests are "deposit AC ∧ no deposit-source
   row".
3. **Not "AC == the configured default".** Rejected: the Configuration key
   stays mutable, so repointing it would retroactively reinterpret history
   (paid-undeducted credits vanishing). The flag lives on the category;
   the settings key only chooses which deposit category *new* deposit lines
   get.
4. **Targeted AC freeze.** Once a category is referenced by any line item (or
   other AC-bearing row — exact FK enumeration at plan time), its
   `is_deposit` and `taxable` fields become immutable: retire (`is_active`)
   and replace instead, RateScheme-style. Mutating those two on a used AC
   rewrites the meaning of existing lines; name/code and QBO mappings stay
   editable (remapping after a QBO reconnect must remain possible; push
   reads mappings at push time). Attempting a frozen edit raises a
   ValidationError coaching retire-and-replace. **Full** AC
   immutability/supersession is deferred to its own effort (noted in
   `docs/designs/LATER.md`).
5. **Deposit categories are non-taxable by invariant.** `is_deposit=True`
   requires `taxable=False`, validated on the category — enforcement, not a
   settings note. (`taxable_override` no longer exists, removed 2026-07-21;
   the QBO push derives `TaxCodeRef` from `accounting_category.taxable`.)
6. **Unsplittable credit.** A paid deposit is deducted whole by exactly one
   invoice. The source-row unique-claim constraint enforces this. If partial
   deduction across progress invoices becomes a real need, that's a future
   remaining-balance model — explicitly deferred.
7. **Paid-only availability.** The deduction atom exists only once QBO
   reports the deposit invoice paid. You can't deduct money you don't hold.
8. **Mixing is legal.** A deposit line may coexist with standard lines on one
   invoice (and any manual line given a deposit AC *becomes* a deposit line,
   coherently: non-taxable, credit-on-paid). The invoice gets the deposit
   pill; the deposit line becomes a credit atom when the whole invoice is
   paid.
9. **Multiple deposits per job are legal.** Each paid deposit line is its own
   credit atom. Multiple deposit *categories* are also possible; the
   settings key picks the default one the picker stamps.
10. **No global invoice gate.** Standard invoicing works without the deposit
    default configured. Only deposit-line creation requires it (mirrors the
    materials-default pattern: a coaching error, not a surface lockout).

## Data model

- `AccountingCategory.is_deposit` — BooleanField, default `False`.
  Invariants, validated on the category:
  - `is_deposit=True` → `taxable=False`;
  - once the category is referenced by any AC-bearing row, `is_deposit` and
    `taxable` cannot change (retire/replace instead).
- Deduction line — an ordinary `InvoiceLineItem` (negative price, qty 1,
  same AC as its source deposit line) plus an `InvoiceLineItemSource` row:
  `source_type='deposit'`, `source_pk=<source deposit line pk>`. The
  existing whole-atom unique constraint on sources prevents a second live
  claim on the same deposit line.
- No `Invoice` or `InvoiceLineItem` schema change. Serializers expose
  derived helpers as needed (per-line "is deposit", enough for the pills —
  exact shape at plan time).

## Configuration

- New key: `default_deposit_accounting_category` (AC pk as string), mirroring
  `default_material_accounting_category` end to end: Settings API validation
  (must be a real, **active, deposit** category), Settings UI component
  (copy `DefaultMaterialCategorySetting.svelte`; dropdown lists deposit
  categories only), resolved server-side when a deposit line is created via
  the picker.
- Unset behavior: creating a deposit line through the deposit path raises the
  coaching `ValidationError` ("No default deposit accounting category is
  configured. Set it in Settings."); the picker's Deposit entry is disabled
  with a hint.
- Add the key to test `setUp()` / fixtures per convention
  (`data-constraints.md` §1.1 gets the new row).

## Backend behavior

### Category management

The AC admin surface (config-gated) grows the `is_deposit` checkbox. Both
`is_deposit` and `taxable` are rejected server-side (and disabled in the UI)
once the category is in use. Retirement (`is_active=False`) remains the
change mechanism, as today.

### Creating a deposit line

The picker's Deposit choice posts a manual line with the default deposit AC
stamped server-side (coaching error if the key is unset/invalid). Amount and
description are the user's; description prefills "Deposit on {job_number}".
Draft-only, like all line CRUD. (A manual line hand-assigned a deposit AC is
equally a deposit line — same semantics, no special-casing.)

### The credit atom (wizard source pool)

`InvoiceWizardService.get_source_pool` gains a deposit-credit atom type:
deposit lines (deposit AC, no deposit-source row) belonging to **paid**
invoices of the same job with **no live claim** (a claim on a
cancelled/discarded invoice doesn't count, matching existing claim-release
semantics). Pulling the atom creates the deduction line:

- amount locked to the full deposit line total, negated; qty 1; non-editable
  amount (unsplittable rule) — description editable;
- description default: `Less deposit (INV-1042)` (the deposit invoice's
  number);
- AC copied from the source deposit line;
- source row written as above, claiming the deposit.

Deleting the deduction line (via `delete_line_item_with_renumber`, as
always), discarding its draft invoice, or cancelling its invoice releases
the claim; the credit returns to the pool.

A deposit line never appears in the pool as a *billable* atom (it covers no
work); it only ever appears as a credit.

### Status/lifecycle

Nothing new. Send, QBO push, payment polling, cancel, and the job
auto-complete gate all treat a deposit invoice as any invoice. (The
completion gate already leaves task-less deposit-paid jobs alone.)

## QBO

No new mechanics. The deposit line pushes as a normal `SalesItemLine`
(`TaxCodeRef` `'NON'` via its AC — guaranteed by the category invariant),
the deduction pushes as a negative-amount line — legal in QBO. `ItemRef`
resolution via the AC mapping, unchanged.

## Frontend

### Add-line alignment (sibling work, this branch)

Invoice line-item adding adopts the estimate flow:

- "Add line" on `InvoicePanel` opens `PriceListPicker` (services + inventory
  + manual), replacing the direct `LineItemModal` open with its stale
  Manual/From-Inventory radio. `LineItemModal` remains the *edit* modal, as
  on estimates.
- An invoice-side add-line form handles the picked choice (reuse or adapt
  `EstimateAddLineForm`; decided at plan time). Service items on invoices
  are **pure billing lines** — rate scheme × entered qty prices the line, no
  task creation, no job side effects. Use case: work done outside the app
  that still needs invoicing.
- **Deposit is one more entry in the picker, invoice surface only.** It pulls
  from no catalog: choosing it opens the small prefilled form — amount,
  editable description ("Deposit on JOB-2026-0042"), default deposit AC
  applied. Disabled with a Settings hint when the default is unconfigured.
  Estimates/change orders don't get the entry (deposits are an invoicing
  concept; an estimate line hand-assigned a deposit AC is legal but
  meaningless and gets no special handling).

### Indicators (all derived, no stored state)

- **Invoices list**: a "DEPOSIT" doc-pill in the status column beside the
  actual status pill (existing `doc-pill` vocabulary).
- **Job overview `InvoicingBlock`**: the deposit invoice's row is labeled as
  a deposit (it already lists invoices chronologically, so a deposit reads
  first naturally).
- **Job Board `JobCard`**: a pill — "DEP REQUESTED" while a deposit invoice
  is sent and unpaid; "DEP PAID" once paid **and its credit not yet claimed
  by a live invoice**; nothing for draft deposits, and nothing after the
  deduction is taken (the deposit is consumed; the signal has served its
  purpose). With multiple deposits, REQUESTED wins over PAID (any
  outstanding request shows). Visible on hover in the In Progress area via
  the existing chip-hover card; that's accepted for now — revisit if it
  proves too buried.
- The existing manual `on_hold` + "awaiting deposit" reason remains available
  and unrelated.

### Wizard UI

The deposit credit shows in the source pool with a clear label (e.g.
"Deposit credit — INV-1042, $5,000") and pulls like any atom; the resulting
line renders with its negative amount. No new pane or mode.

## Edge cases

- Cancelling a **paid** deposit invoice: out of scope (refund flows don't
  exist). The pool rule is *paid* status, and cancelled is not paid, so such
  a credit stops being offered. Already-taken deductions are untouched
  (history is history).
- Deleting a deposit line: only possible while its invoice is a draft (line
  CRUD is draft-only), at which point nothing can have claimed it. No
  orphan-deduction case exists.
- A deduction can only target deposits of the **same job** (pool is
  job-scoped by construction).
- Retiring the deposit category: existing lines keep their FK (retirement
  never touches history); the settings key validation fails on next save,
  and the picker entry disables until a new deposit category is configured.
- Sum sanity: nothing prevents a deduction larger than the invoice's other
  lines (a negative-total invoice). QBO rejects negative-total invoices at
  push time; we accept that as the guard rather than pre-validating. (Note
  in docs; revisit if it bites.)

## Testing

- **Backend** (`tests/`): category invariants (`is_deposit` → non-taxable;
  freeze of `is_deposit`/`taxable` once used, coaching error, still editable
  while unused; name/QBO-mapping edits stay allowed on used ACs);
  default-key resolution + coaching error + deposit-category-only
  validation; deposit line creation via the deposit path and via manual
  AC assignment; pool exposure rules (paid-only, unclaimed-only, job-scoped,
  cancelled-claim release, deductions never offered); deduction creation
  (amount lock, AC copy, source row, unique claim); derived deposit-ness;
  mixing; multiple deposits.
- **Vitest** (`frontend/tests/`): picker's Deposit entry (present on invoice
  surface, absent on estimate; disabled-with-hint when unconfigured);
  deposit form prefill; AC manager freeze behavior; settings dropdown
  filtering; pills in invoices list / `JobCard` / `InvoicingBlock` state
  logic; wizard credit rendering.
- **E2E** (`e2e/`): the full flow — create a deposit category, configure the
  default, create deposit invoice via picker, send, (seeded/simulated) pay,
  see "DEP PAID" on the board, build final invoice pulling the credit,
  verify deduction line and pill retirement. Per Definition of Done.

## Doc updates (same session as implementation)

- `invoicing-and-expenses.md`: deposit concept, category flag, pool rules,
  picker alignment; also fix stale `taxable_override` mentions (§118, §298).
- `estimates-and-prices.md` §687: same stale mention.
- `data-constraints.md`: `AccountingCategory.is_deposit` row + freeze/taxable
  invariants, new Configuration key (§1.1), claim-constraint note.
- `jobs-and-tasks.md`: board pill, if the board section enumerates card
  elements.
- `docs/designs/LATER.md`: entry for full AC immutability/supersession
  (added with this spec).

## Out of scope

- Partial/split deduction (remaining-balance model) — deferred until needed.
- Refund/undo of a paid deposit.
- Any invoice-readiness gate beyond the deposit-line coaching error.
- Full AC immutability/supersession (RateScheme-style) — separate future
  effort; this branch freezes only `is_deposit`/`taxable` on used
  categories.
