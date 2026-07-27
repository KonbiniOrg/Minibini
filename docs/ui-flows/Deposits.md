# Deposits — UI flow

> Covers creating a deposit invoice (the invoice panel's **Add Deposit
> Invoice** / **Make this a deposit invoice** button + modal), the resulting
> **DEPOSIT** pill on the invoices list, the **DEP PAID** / **DEP REQUESTED**
> board banner, pulling a paid deposit's credit into a follow-up invoice as a
> negative **Less deposit (...)** line — including the claim lifecycle (the
> banner clears while the claiming draft is live, and returns if the draft
> is discarded) — and the **unapplied deposit credit** notice + send-time
> confirm that nudges toward applying an outstanding credit before sending
> another invoice. Reference: `docs/plans/deposit-invoices-spec.md`, Task 21
> (2026-07 — replaced the picker's Add Deposit entry with this streamlined
> generator; refined 2026-07-26 into the three-state button below), Task 22
> (2026-07-26 — the unapplied-credit notice + send confirm, §4 below).

**QBO is unreachable in e2e**, so send/pay transitions are not driven here.
The **paid** deposit invoice (`INV-E2E-DEP-1`, on the seeded job `08026`) is
seeded directly in `fixtures/playwright/seed.json` — see
`docs/designs/e2e-testing.md` §3.

## Personas

- **Financials** (`finjobs` — `can_manage_financials` + `can_manage_jobs`).
  Creates invoices, adds deposit lines, reconciles deposit credits.

## Prerequisites (test-data setup)

- [ ] An `AccountingCategory` with `is_deposit: true` (`is_active`,
  non-taxable — a deposit category must be non-taxable) and the
  `default_deposit_accounting_category` Configuration key pointing at its pk.
- [ ] A **paid** deposit invoice on a seeded `in_progress` job with no other
  draft invoice, carrying one deposit-category line.
- [ ] A separate invoice-less approved/in_progress job, for the
  deposit-creation flow (the deposit-credit job already carries the seeded
  paid deposit, so it's excluded from that search).

---

## 1. Creating a deposit invoice

Entry: Job invoice panel (`#/jobs/{id}/invoice`), any state (empty or already
carrying invoices).

The action has **three states**, derived from whether the job already has an
open draft and whether that draft already carries any line items:

1. **No draft on the job** → button reads **"Add Deposit Invoice"**. In the
   empty state it sits next to **Start Invoice**; once the job has other
   (non-draft) invoices, it sits next to the version bar's **+ New invoice**
   action.
2. **A draft exists with zero line items** → button relabels to **"Make
   this a deposit invoice"** (same placement as state 1's non-empty case,
   next to the version bar). Creating still works — the invoice-create call
   is idempotent and resolves to the existing empty draft, so only the
   deposit line gets added to it.
3. **A draft exists WITH line items already** → the action is **suppressed
   entirely**, in both placements. (Once a deposit line lands on a draft
   that already has other lines, or once other lines get added to a
   deposit-only draft, the action stays suppressed — "mixing" a deposit
   line with ordinary lines on one invoice is legal, it's just no longer
   offered as a fresh deposit-invoice starting point.)

Both placements are gated the same way Start Invoice is (billable job status
+ `can_manage`), and — in states 1/2 — disabled with a "Set a deposit
category in Settings first" hint when no active deposit category exists.

- [ ] **Modal.** Clicking it opens a small "Add Deposit Invoice" modal with
  one **Amount** field (required, > 0) and Create/Cancel.
- [ ] **Create** does the two-step create in one action: opens (or reuses)
  the job's draft invoice the same way Start Invoice does, then posts the
  deposit line to it (description defaults to "Deposit on {job_number}"; no
  accounting-category field — the server stamps the configured deposit
  category).
- [ ] **Post-create freshness.** If the user is already viewing the draft
  that just received the line (state 2, triggered from that draft's own
  page), the invoice reloads **in place** — no navigation, the new line
  just appears (the same convention as any other add-line save). Otherwise
  (state 1's brand-new draft, or state 2 triggered while viewing a
  different document) the panel navigates to the draft, same as Start
  Invoice.
- [ ] **The line renders** with the deposit category and the entered amount.
- [ ] **DEPOSIT pill.** The invoices list (`#/invoices`) shows a **DEPOSIT**
  pill next to this invoice's status.

## 2. A paid, unclaimed deposit shows on the board

Entry: Job Board (`#/jobs/board`), In Progress column.

- [ ] Hovering the job's chip reveals its hover-card; the card shows a
  **DEP PAID** banner (an **open**/**partly-paid** deposit shows
  **DEP REQUESTED** instead — not exercised here, no seeded shape).

## 3. Pulling a deposit credit into a new invoice

Entry: a second invoice on the same job, Reconcile mode ("Reconcile" toggle,
heading "Tasks and Materials").

- [ ] **Deposit credits group.** The source pool shows a **Deposit credits**
  group with a `[deposit]`-tagged row: "Deposit credit — INV-E2E-DEP-1 ...
  $5,000.00 credit".
- [ ] **Add Here.** Selecting the row and clicking **Add Here** creates a new
  line item "Less deposit (INV-E2E-DEP-1)" with a negative price/total.
- [ ] **Claimed state.** Once claimed by this (live) draft, re-opening the
  pool shows the row as claimed (checkbox disabled/checked, "→ line N").
- [ ] **Banner clears while claimed.** Because the claim lives on a live
  (non-cancelled) invoice, the board's **DEP PAID** banner clears for the job
  while the draft exists.
- [ ] **Discard releases the claim.** Discarding the draft (Discard draft)
  releases the claim — the board's **DEP PAID** banner returns.

## 4. Unapplied deposit credit — draft-panel notice + send-time confirm

Entry: any **draft** invoice on a job that has a paid, unapplied deposit
credit; and the Send Invoice screen for any invoice on such a job.

- [ ] **Notice.** Viewing a draft invoice on a job with ≥1 unapplied deposit
  credit shows a row above Line Items: "Unapplied deposit credit — $&lt;amount&gt;
  from &lt;source invoice's number&gt;" (one row per credit — multiple are
  possible). The text is visible to any viewer of the draft; only the
  **Apply deposit credit** button is gated on the same permission as
  line-item edits.
- [ ] **Apply.** Clicking **Apply deposit credit** posts the credit onto
  this draft the same way Reconcile's "Add Here" does (a negative "Less
  deposit (...)" line appears) and the notice row for that credit
  disappears.
- [ ] **Gone once claimed elsewhere too.** Pulling the same credit via
  Reconcile's "Add Here" (§3 above) also clears the notice — both paths
  land on the same claim.
- [ ] **Absent** on non-draft invoice views, and when the job has no
  unapplied deposit credits.
- [ ] **Send-time confirm (soft guard).** Confirming a send
  (`#/invoices/{id}/send`) on a job that still has ≥1 unapplied deposit
  credit at that moment shows a second confirmation — "There's an
  unapplied deposit credit on this job — send anyway?" — after the normal
  "Send this email to...?" confirm. OK proceeds with the send; Cancel
  aborts, leaving the send screen untouched. No extra confirm when there
  are no unapplied credits. **Not exercised in e2e** — QBO is unreachable
  in this env, so the send POST itself can't be driven here; covered by
  Vitest (`frontend/tests/routes/invoices/InvoiceSendPage.test.js`).

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Creation | Three-state button (Add Deposit Invoice / Make this a deposit invoice / suppressed) gated on billable/can_manage and an active deposit category · modal amount entry · two-step create (invoice + deposit line) · post-create in-place reload vs. navigation · line renders with category+amount · DEPOSIT pill on the invoices list |
| Board | DEP PAID banner on the hover card for a paid, unclaimed deposit |
| Credit pool | Deposit credits group · `[deposit]` tag · credit amount format ("$X,XXX.XX credit") · Add Here creates a negative deduction line ("Less deposit (...)") |
| Claim lifecycle | claim clears DEP PAID while the claiming draft is live · discarding the draft releases the claim and DEP PAID returns |
| Unapplied credit notice | notice text + amount + source invoice number · absent when claimed by a live invoice · present again when the claiming invoice is cancelled (parity case) · absent on non-draft views/no credits · Apply posts the exact atoms payload and clears the notice |
| Send-time confirm | confirms only when ≥1 unapplied credit exists · OK proceeds, Cancel aborts leaving state intact · no confirm when none (Vitest-only, not e2e-reachable) |
