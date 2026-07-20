# Invoice seeding, editing & send-gate — UI flow

> **New (2026-06 invoice consolidation).** Covers how a draft invoice gets its lines —
> the two **seed buttons** (Apply everything / Copy from estimate), the retained per-line
> editing, the **agreement adjustments** panel, and the **accounting-category flag +
> Send-gate**. Companion to `Services-and-Adjustments.md` (estimate-side pricing/adjustments)
> and `Add-Line-and-Work-Authoring.md` (estimate/work authoring). Reference: `docs/designs/invoicing-and-expenses.md`
> and the spec `docs/plans/2026-06-28-invoice-changes-spec.md`.

**Purpose:** A from-the-user's-perspective walkthrough of building and sending an invoice
under the consolidated model. Unlike the estimate Client View (a locked projection), the
**invoice keeps full per-line editing** — the seed buttons are just starting points. Guides
manual/user testing; each checklist item maps to a future automated assertion.

**The big idea:** a draft invoice is seeded **one of two ways** (mutually exclusive starting
points), then hand-edited freely:
- **Apply everything** — bill the job's actual **atoms** (every billable Task / Material /
  Expense), one per line.
- **Copy from estimate** — bill what was **quoted**: copy the accepted estimate (+ accepted
  change-order deltas), ignoring atoms.

## Personas

- **Financials** — `can_manage_financials`. Creates invoices, seeds/edits lines, sends. All
  the actions below need this atom (or superuser).
- **Everyone else** — read-only on invoices; none of the buttons below appear.

## Prerequisites (test-data setup)

- [ ] A **job** with billable atoms: at least one **completed** Task, one **consumed**
  Material, and one **expense** (so "Apply everything" has something to land). Incomplete
  tasks / unconsumed materials are *not* billable and should be skipped.
- [ ] An **accepted estimate** on a (second) job that carries a **percentage adjustment**
  (e.g. a 10% rush), so "Copy from estimate" and the agreement-adjustments panel have
  something to show. *(If you can't find one: take a job whose estimate has an adjustment,
  accept the estimate, then create its invoice.)*
- [ ] A `can_manage_financials` user.
- [ ] For the **progress-billing** case: a job that already has one **prior** invoice, so a
  second invoice can demonstrate "remaining atoms only" + the disabled Copy button.

---

## 1. Create / open the draft invoice

Entry: **Job overview** → the invoice area.

- [ ] **Create Invoice.** With a `can_manage_financials` user on a billable job, the overview
  shows a **Create Invoice** button. Click it → it creates a draft invoice and navigates to
  the **Invoice detail page** (`#/invoices/{id}`). A job has at most **one draft** invoice —
  clicking again opens the existing draft.
- [ ] **Draft, empty.** A freshly created invoice is `draft` with no line items — this is the
  only state in which the seed buttons appear.
- [ ] **Billable-jobs gate (2026-07-19).** The job's Invoice section (`#/jobs/{id}/invoice`)
  offers **Start Invoice** only on a billable job (`approved` and beyond); on a
  `draft`/`submitted` job the empty state reads "No invoices yet. Invoicing becomes available
  once the job is approved."

## 2. Seed the invoice — the two buttons

Entry: Invoice detail page, **Line Items** area, on a **draft invoice with no lines**.

- [ ] **Both buttons present on an empty draft.** "Apply everything" and "Copy from estimate"
  show above the usual Add Line Item / Add Adjustment controls.
- [ ] **They are starting points — they vanish once any line exists.** After seeding (or after
  adding a line by hand), the two seed buttons are gone; only the normal editing controls
  remain. To re-seed a different way you **delete the draft and create a new one**.
- [ ] **Apply everything.** Click → the invoice fills with **one line per available atom**
  (completed tasks, consumed materials incl. task-less ("no task") materials, and expenses).
  Not-billable atoms (incomplete task, unconsumed material) are skipped.
- [ ] **Copy from estimate.** On a first invoice, click → the invoice fills with the
  **agreement-of-record**: the accepted estimate's lines amended by accepted change orders,
  including the estimate's adjustment line(s). Atoms are ignored.
- [ ] **Crystallized fees arrive claimed (2026-07-03).** After Copy from estimate, open
  **Show Billables** — every Fee behind an agreement line (from estimate hand-lines *and*
  from accepted change-order add/replace lines) shows as **claimed by this invoice**, so
  the wizard can't double-bill it.

## 3. Availability rules (most-missed)

- [ ] **Empty-draft only.** Neither button appears once the invoice has a line, nor on a
  non-draft (sent/paid/cancelled) invoice.
- [ ] **Copy disabled on a repeat invoice.** When the job already has another (non-cancelled)
  invoice, **Copy from estimate** is **disabled** (hover shows "Not available once another
  invoice exists for this job") — copying the whole agreement again would double-bill.
- [ ] **Apply everything bills only what's left.** On that same repeat invoice, **Apply
  everything** lands only the **remaining** atoms — anything already billed on the prior
  invoice is skipped (no error, no duplicates).

## 4. Retained per-line editing

Entry: any draft invoice with lines.

- [ ] **Add Line Item** — add a freeform/by-hand line (the estimate can't do this; the
  invoice deliberately can).
- [ ] **Edit / Delete / reorder (↑ ↓)** any line.
- [ ] **Edit a line's accounting category.** Open a line's **Edit** modal → the **category**
  dropdown (with "-- None --") is editable; saving persists it and re-runs adjustment math.
- [ ] **Show Billables** — the wizard for grouping atoms into lines (joining) is still
  available when there are billable atoms.
- [ ] **"Struck from agreement" badge (2026-07-20).** In Show Billables, a task/material
  atom whose claiming estimate line an **accepted change order** removed/replaced — while
  the atom itself stayed live (complete task, consumed material; crystallization deliberately
  leaves those alone) — carries an amber **"struck from agreement"** badge; untouched atoms
  don't. Suppressed on a cancelled task ("cancelled — work done" wins; one amber badge is a
  prompt, two is noise).

## 5. Adjustments (unchanged behavior + dedup)

Entry: the **Agreement Adjustments** panel on the draft invoice, plus **Add Adjustment**.

- [ ] **Panel surfaces the accepted estimate's adjustments.** Each shows its description, %,
  and an **Add** button.
- [ ] **No double-apply.** If the adjustment is already on the invoice — because you used
  **Copy from estimate** (which brings the estimate's adjustment line across automatically),
  or because you already clicked **Add** — the panel shows it as **Added** (disabled).
- [ ] **Apply everything leaves adjustments to the panel.** Atoms don't include adjustments,
  so after "Apply everything" the panel still offers the estimate's adjustment for you to Add.
- [ ] **Add Adjustment** lets you add a percentage adjustment by hand (choose the rate +
  target categories).

## 6. The accounting-category flag & the Send-gate

This is the guardrail that keeps a category-less line from being sent (which would mis-bill
tax and break the QBO item mapping).

- [ ] **Missing category is flagged.** On a draft (editable) invoice, any line with **no
  accounting category** shows an amber **"needs category"** in the Category column instead of
  a bare "—". (A line can end up with no category after **joining atoms of different
  categories** — see `Add-Line-and-Work-Authoring.md` — or a freeform line you didn't
  categorize.)
- [ ] **Send is blocked until every line has a category.** While any line is flagged, the
  **Send Invoice** action is **disabled** and a note reads "Assign an accounting category to
  every line before sending."
- [ ] **Assigning the category unblocks Send.** Open the flagged line's **Edit**, pick a
  category, save → the flag clears and the **Send Invoice** link becomes active.
- [ ] **Belt-and-suspenders (server side).** Even if you bypass the UI, the send endpoint
  refuses (400) with a message naming the un-categorized line number(s).
- [ ] **Read-only invoices don't flag.** On a sent/paid invoice (not editable), a missing
  category renders as "—" with no flag (nothing to fix there).

## 7. Tax note (current behavior)

- [ ] A merged/joined line takes the **single** category you assign it; that category's
  taxability governs the **whole** line. If a merge mixes taxable + non-taxable amounts, use
  the line's tax override if you need a different treatment. (Splitting tax within one merged
  line is intentionally not done — evaluate whether per-line is good enough as you go.)

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Create | Create Invoice from job overview → draft detail page · one draft per job · billable-jobs gate (draft/submitted hint) |
| Seed source | Apply everything (atoms, one per line) · Copy from estimate (agreement) |
| Seed availability | both only on empty draft · gone once a line exists · Copy disabled when a prior invoice exists · Apply-everything bills remaining atoms on a repeat invoice |
| Not-billable | incomplete task / unconsumed material skipped by Apply everything |
| Editing | add · edit · delete · reorder · edit category · Show Billables (join) · struck-from-agreement badge (present on CO-struck live atom · absent on untouched · suppressed on cancelled) |
| Adjustments | panel lists accepted estimate's adjustments · Added/dedup (copy-from-estimate auto-brings; panel marks Added) · Apply-everything leaves to panel · Add Adjustment by hand |
| Category flag | null category flagged "needs category" when editable · not flagged when read-only |
| Send-gate | Send disabled + note while any line uncategorized · assigning category enables Send · server rejects (400) a category-less send |
