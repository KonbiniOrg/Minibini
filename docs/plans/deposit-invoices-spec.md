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

1. **The line is the special thing, not the invoice.** A new
   `InvoiceLineItem.is_deposit` boolean (default `False`). An invoice *is* a
   deposit invoice iff it contains a deposit line — derived everywhere, never
   stored on Invoice, so it can't drift (delete the line while drafting and
   the deposit-ness disappears).
2. **No `kind` enum.** Deduction lines don't need a marker: they are
   identified by their `InvoiceLineItemSource` row (`source_type='deposit'`,
   `source_pk=<deposit InvoiceLineItem pk>`), exactly how task/material lines
   are identified today. Only the deposit line itself carries a flag.
3. **Not identified by accounting category.** Testing "line's AC == the
   configured deposit AC" was considered and rejected: the Configuration
   value is mutable (repointing it would retroactively erase deposit history)
   and AC is a user-editable field on every line (recategorizing a line could
   silently create or destroy deposit-ness).
4. **Unsplittable credit.** A paid deposit is deducted whole by exactly one
   invoice. The source-row unique-claim constraint enforces this. If partial
   deduction across progress invoices becomes a real need, that's a future
   remaining-balance model — explicitly deferred.
5. **Paid-only availability.** The deduction atom exists only once QBO
   reports the deposit invoice paid. You can't deduct money you don't hold.
6. **Mixing is legal.** A deposit line may coexist with standard lines on one
   invoice. Unusual but allowed — no validation forbids it. The invoice gets
   the deposit pill; its deposit line becomes a credit atom when the whole
   invoice is paid.
7. **Multiple deposits per job are legal.** Each paid deposit line is its own
   credit atom.
8. **Taxability rides on the AC.** `taxable_override` no longer exists
   (removed 2026-07-21); the QBO push derives `TaxCodeRef` from
   `accounting_category.taxable`. The deposit default AC is expected to be a
   non-taxable category; the Settings UI says so next to the field. No
   hard enforcement.
9. **No global invoice gate.** Standard invoicing works without the deposit
   AC configured. Only deposit-line creation requires it (mirrors the
   materials-default pattern: a coaching error, not a surface lockout).

## Data model

- `InvoiceLineItem.is_deposit` — BooleanField, default `False`. Persists for
  the life of the line (including on cancelled invoices). Editable lines
  (draft invoice) keep the flag; editing a deposit line edits amount/
  description like any line but does not expose an is_deposit toggle in edit
  mode — deposit-ness is chosen at creation.
- Deduction line — an ordinary `InvoiceLineItem` (negative price, qty 1,
  same AC as its source deposit line) plus an `InvoiceLineItemSource` row:
  `source_type='deposit'`, `source_pk=<source deposit line pk>`. The
  existing whole-atom unique constraint on sources prevents a second live
  claim on the same deposit line.
- No Invoice schema change. Serializers expose derived helpers as needed
  (e.g. `is_deposit` per line; the invoice list/board data needs enough to
  render the pills — exact serializer shape decided at plan time).

## Configuration

- New key: `default_deposit_accounting_category` (AC pk as string), mirroring
  `default_material_accounting_category` end to end: Settings API
  validation (must be a real, active category), Settings UI component
  (copy `DefaultMaterialCategorySetting.svelte`), resolved server-side when a
  deposit line is created.
- Settings UI note: "Choose a non-taxable category — deposits must not be
  taxed."
- Unset behavior: creating a deposit line raises the coaching
  `ValidationError` ("No default deposit accounting category is configured.
  Set it in Settings."); the picker's Deposit entry is disabled with a hint.
- Add the key to test `setUp()` / fixtures per convention (`data-constraints.md`
  §1.1 gets the new row).

## Backend behavior

### Creating a deposit line

`InvoiceService.add_line_item` path grows deposit support (exact signature at
plan time): when a line arrives flagged `is_deposit`, the service stamps the
configured default AC (error if unset), forces nothing else — description
and amount are the user's. Draft-only, like all line CRUD.

### The credit atom (wizard source pool)

`InvoiceWizardService.get_source_pool` gains a deposit-credit atom type:
deposit lines belonging to **paid** invoices of the same job with **no live
claim** (a claim on a cancelled/discarded invoice doesn't count, matching
existing claim-release semantics). Pulling the atom creates the deduction
line:

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
(`TaxCodeRef` `'NON'` via its AC), the deduction pushes as a negative-amount
line — legal in QBO. `ItemRef` resolution via the AC mapping, unchanged.

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
  editable description ("Deposit on JOB-2026-0042"), default AC applied,
  `is_deposit` set. Disabled with a Settings hint when the default AC is
  unconfigured. Estimates/change orders don't get the entry (deposits are an
  invoicing concept).

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
  exist); if it happens, its credit simply stops being offered only if the
  pool excludes cancelled invoices — pool rule is *paid* status, and
  cancelled is not paid, so the credit disappears. Already-taken deductions
  are untouched (history is history).
- Deleting a deposit line: only possible while its invoice is a draft (line
  CRUD is draft-only), at which point nothing can have claimed it. No
  orphan-deduction case exists.
- A deduction can only target deposits of the **same job** (pool is
  job-scoped by construction).
- Sum sanity: nothing prevents a deduction larger than the invoice's other
  lines (a negative-total invoice). QBO rejects negative-total invoices at
  push time; we accept that as the guard rather than pre-validating. (Note
  in docs; revisit if it bites.)

## Testing

- **Backend** (`tests/`): default-AC resolution + coaching error; deposit
  line creation; pool exposure rules (paid-only, unclaimed-only, job-scoped,
  cancelled-claim release); deduction creation (amount lock, AC copy, source
  row, unique claim); derived deposit-ness; mixing; multiple deposits.
- **Vitest** (`frontend/tests/`): picker's Deposit entry (present on invoice
  surface, absent on estimate; disabled-with-hint when unconfigured);
  deposit form prefill; pills in invoices list / `JobCard` / `InvoicingBlock`
  state logic; wizard credit rendering.
- **E2E** (`e2e/`): the full flow — configure default deposit AC, create
  deposit invoice via picker, send, (seeded/simulated) pay, see "DEP PAID" on
  the board, build final invoice pulling the credit, verify deduction line
  and pill retirement. Per Definition of Done.

## Doc updates (same session as implementation)

- `invoicing-and-expenses.md`: deposit concept, field, pool rules, picker
  alignment; also fix stale `taxable_override` mentions (§118, §298).
- `estimates-and-prices.md` §687: same stale mention.
- `data-constraints.md`: `is_deposit` field row, new Configuration key
  (§1.1), claim-constraint note.
- `jobs-and-tasks.md`: board pill, if the board section enumerates card
  elements.

## Out of scope

- Partial/split deduction (remaining-balance model) — deferred until needed.
- Refund/undo of a paid deposit.
- Any invoice-readiness gate beyond the deposit-line coaching error.
- Estimate-side deposit lines.
