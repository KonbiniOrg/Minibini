# Outsourced work: porting Phase 5 (PO reconciliation + rate prompt)

RM commissioned 2026-09-21. Source: the complete Phase 5 implementation on
`feature/fees` (commits 09a1e920, 148a419c, d500def1, add14122, a8efed8c,
544a4449, f9218be8, 21c39b73; spec §7 of
`feature/fees:docs/plans/2026-08-02-task-owned-money.md`; doc §10a of
`feature/fees:docs/designs/materials-inventory-and-purchasing.md`).
Detailed port analysis with per-component verdicts:
`docs/plans/2026-09-21-phase5-port-analysis.md` (referenced throughout as
"the analysis"). Target branch: feature/estimating.

## 1. What ships (behavior, current-branch terms)

**The outsourced-work flow end to end:**

1. **Sell side (already built — no new code):** the outsourced charge is an
   estimate line like any other: a hand service line, a flat-fee
   ServiceItem ("Outsourced powder coating" — §2.2a shape, amount on the
   item), or a task authored with §3.6c create-time rate overrides (type
   the vendor quote × markup as the rate). Acceptance/mint produces the
   task per existing rules. The task completes when vendor work is
   received (entered-qty settle-up prompt answers the final qty;
   completion never asks about money).
2. **Order:** a PO line optionally links to a task
   (`PurchaseOrderLineItem.task` — the reserved FK goes live; the API
   create-path strip is removed; `LineItemForm` gains an optional Task
   Link picker, job-cascading, all tasks eligible). Sell lives on the
   atom, cost on the PO line — mirror of the materials pattern.
3. **Receive:** existing flow, unchanged. A PO received in full but not
   reconciled surfaces as **awaiting reconciliation** (amber list badge +
   list filter) — a purchasing-side nudge, never tied to task completion.
4. **Reconcile (when the vendor bill lands; bill itself stays in QBO):**
   `POST /api/purchase-orders/{id}/reconcile/` (CanManageFinancials).
   PO-level authoritative: `bill_total`, `vendor_invoice_ref`,
   `reconciled` flag+date (editable — re-reconcile overwrites; allowed any
   time past draft, including cancelled). Line-level optional: per-line
   `final_price` (null = as ordered; REPLACE semantics — every save sends
   the complete picture). Appended **invoice-only** lines (freight, tax)
   with optional task attribution — append-only mirror semantics, always
   excluded from receiving. `variance = bill_total − ordered_total`.
5. **Rate prompt:** after each reconcile, for every line with a
   `final_price` AND a linked task that is NOT claimed by any invoice
   (`InvoiceClaimService.is_invoiced`), the response carries a prompt:
   current rate vs `suggested = final_price × (1 + markup/100)` using the
   existing `default_material_markup_percent` Configuration (absent config
   → suggestion = bare cost, honest "no markup configured" note). The
   dialog's **Accept issues the ordinary money-gated
   `PATCH .../tasks/{id}/ {rate}` — no new money-writing path**; Decline
   persists nothing; prompts recompute fresh on every reconcile.
6. **Job costing:** `compute_job_financials` gains `linked_po_variances`
   (per linked PO: ordered vs bill totals, variance, multi_job flag; no
   proration). API-only, as on fees — job-page display stays a LATER.

## 2. Port decisions (this document's rulings)

1. **parent_task machinery: excised, not ported.** Current branch law: no
   code reads or writes `Task.parent_task` (dormant). The fees-era
   top-level-task rule in `PurchaseOrderLineItem.clean()`, the
   validate_data subtask ERROR, TaskLinkPicker's client filter, and both
   subtask tests all guard an impossible state — all dropped. `clean()`
   keeps only the job-bearing defense-in-depth check (a linked task must
   belong to a job).
2. **Rate-prompt current rate is `task.effective_rate()`** (modifiers-
   aware — resolves fees' own LATER note), not raw `task.rate`. Accept
   still PATCHes bare `rate = suggested`; when the task carries active
   modifiers the dialog notes "modifiers apply on top of the accepted
   rate." (`suggested_rate` math unchanged.)
3. **What Accept means under agreement-skeleton invoicing (stated out
   loud):** reconciliation NEVER blocks invoice seeding. Accepting a
   prompt updates `Task.rate`; a backed invoice line seeded AFTER that
   lands on the new actuals basis automatically
   (`_rederive_price_from_actuals`); a line seeded BEFORE it shows the
   ordinary actuals-vs-agreement drift signals. Late variance that nobody
   accepts is recorded margin, not an error.
4. **invoice_only smuggling hole fixed in the port** (fees LATER item 3):
   the reconcile whitelist already rejects it; the ordinary line-POST path
   must also refuse caller-supplied `invoice_only` at the service level,
   not just serializer read-only.
5. **Reconcile UI lives on the standalone PO detail page only** (faithful
   to fees; the job-side POPanel gets nothing this round).
6. **Config:** reuse `default_material_markup_percent`. No new keys.
7. **Scope unchanged from fees:** no QBO Bill pull-matcher, no billed PO
   status, Bill schema stubs stay parked.

## 3. Mechanics of the port

The merge-base (c0317faa) analysis shows the entire PO surface is
byte-identical between fees' parent and HEAD except one line
(`LineItemForm.svelte` AC filter), and migration slot `purchasing/0025` is
free. Implementers port by reading the fees versions directly
(`git show feature/fees:<path>`) and re-applying, with the excisions and
re-shapes from §2 and the analysis §9 verdict table. Tests port nearly
verbatim minus subtask cases; `validate_data` checks are re-applied by
hand (the file diverged). The e2e journey is REBUILT against current
personas/seeds and current invoice semantics (final assertion: a
freshly-seeded backed invoice line reflects the accepted rate via actuals
re-derivation — not "wizard reads rate").

## 4. Docs shipped with the port

- `materials-inventory-and-purchasing.md`: §10a (reconciliation reference,
  rewritten from fees' text), supersede §9's "no billed state /
  reconciliation is QBO work" note, update the line-items table's `task`
  row ("reserved" → live).
- `data-constraints.md`: the six new fields + validation entries.
- `invoicing-and-expenses.md`: the no-hard-block rule in
  agreement-skeleton terms (§2 ruling 3 verbatim).
- `estimates-and-prices.md`: the outsourced pricing-shape (#11) resolved
  narrative re-grounded on current authoring paths; the dangling §10a
  cross-reference finally resolves.
- `quickbooks-integration.md`: bills-stay-in-QBO + future pull-matcher
  note.
- New `docs/ui-flows/Purchasing.md` (from fees, adjusted).
- LATER.md: resolve fees items 1 (fixed via ruling 2) and 2 (evaporated);
  carry: job-page display of `linked_po_variances`.
