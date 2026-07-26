# Deposits — UI flow

> Covers creating a deposit-category invoice line (the picker's **Add Deposit**
> affordance), the resulting **DEPOSIT** pill on the invoices list, the
> **DEP PAID** / **DEP REQUESTED** board banner, and pulling a paid deposit's
> credit into a follow-up invoice as a negative **Less deposit (...)** line —
> including the claim lifecycle (the banner clears while the claiming draft is
> live, and returns if the draft is discarded). Reference: `docs/plans/deposit-invoices-spec.md`.

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

## 1. Creating a deposit line

Entry: Job invoice panel (`#/jobs/{id}/invoice`), empty draft.

- [ ] **Add Deposit is offered.** Add Line Item → picker → an **Add Deposit**
  button is present, enabled once an active deposit category exists.
- [ ] **Description prefill.** The follow-up form pre-fills Description
  "Deposit on {job_number}"; Amount is entered by hand (no accounting
  category field — the server stamps the configured deposit category).
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

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Creation | Add Deposit button gated on an active deposit category · description prefill · line renders with category+amount · DEPOSIT pill on the invoices list |
| Board | DEP PAID banner on the hover card for a paid, unclaimed deposit |
| Credit pool | Deposit credits group · `[deposit]` tag · credit amount format ("$X,XXX.XX credit") · Add Here creates a negative deduction line ("Less deposit (...)") |
| Claim lifecycle | claim clears DEP PAID while the claiming draft is live · discarding the draft releases the claim and DEP PAID returns |
