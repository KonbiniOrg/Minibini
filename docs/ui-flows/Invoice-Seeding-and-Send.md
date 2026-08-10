# Invoice seeding, editing & send-gate — UI flow

> **Rewritten 2026-08 for the skeleton + three-mode surface.** Every
> new invoice on a job with an agreement now **auto-seeds** from that
> agreement on creation — there is no "start from agreement" button.
> Editing happens on one merged **Edit** mode (`InvoiceEditView.svelte`)
> that replaced the old two-mode ("lines"/reconcile-wizard) panel; the
> retired **"Show Billables"** button is gone — the uncovered-work pool
> is always part of Edit mode. Companion to `Services-and-Adjustments.md`
> (estimate-side pricing/adjustments) and `Add-Line-and-Work-Authoring.md`
> (estimate/work authoring). Reference: `docs/designs/invoicing-and-expenses.md`
> (§"Agreement-line references and seeding", §"Backing model") and the
> design doc `docs/plans/2026-08-06-better-fees.md` §7 + §9.

**Purpose:** A from-the-user's-perspective walkthrough of building and
sending an invoice under the auto-seeded, three-mode model. Guides
manual/user testing; each checklist item maps to a future automated
assertion.

**The big idea:** a draft invoice **starts from the job's agreement
automatically** — one line per remaining `compose_agreement` line, each
carrying its own **backing** (what its amount currently stands on:
`estimate`, `actuals`, `edited`, `deposit`, `deposit credit`). The
invoicer's job is reconciliation, not composition: remove what's not
being billed this time (it reseeds on the next invoice), pull in
uncovered work where it belongs, then send. Two older buttons —
**Apply everything** (atom sweep) and **Copy from estimate** (a plain
copy, no backing) — still exist for the now-rare case of a draft that
legitimately has zero lines.

## Personas

- **Financials** — `can_manage_financials`. Creates invoices, edits
  lines, sends. All the actions below need this atom (or superuser),
  except where noted.
- **Job-managing users** (`can_manage_jobs`, or a job's PM) can also
  create an invoice (Start Invoice), but not edit its lines.
- **Everyone else** — read-only on invoices; the mode bar still shows
  Customer/Reorder but Edit mode renders no action buttons.

## Prerequisites (test-data setup)

- [ ] A **job** with an **accepted estimate** carrying: one task-backed
  line (completed task, so it arrives on `actuals`), one plain hand
  line (arrives on `estimate`, no claims), and a **percentage
  adjustment** line — so auto-seeding, backing chips, and the
  agreement-adjustments panel all have something to show.
- [ ] A second, **estimate-less** job (billable status, no estimate) —
  to exercise the empty-draft / legacy-button path.
- [ ] A `can_manage_financials` user, and separately a `can_manage_jobs`
  (non-financials) user to check the create-only permission split.
- [ ] For the **progress-billing** case: a job that already has one
  **prior** (non-cancelled) invoice, so a second invoice demonstrates
  "remaining lines only" seeding.

---

## 1. Create the draft invoice — auto-seeded

Entry: **Job overview** → the Invoices section rail link, or the job's
Invoices tab.

- [ ] **Start Invoice, agreement job.** With a `can_manage_financials`
  (or `can_manage_jobs`) user on a billable job with an accepted
  estimate, click **Start Invoice** → a draft invoice is created and
  **arrives pre-filled**: one line per remaining agreement line, no
  seed button needed, no extra click. Lands on the Invoices section in
  **Edit** mode.
- [ ] **Backed line arrives on `actuals`.** The line seeded from the
  completed-task agreement line shows a **"actuals"** (or **"actuals =
  estimate ✓"** when the two agree exactly) `BackingChip`, with its
  claimed task nested underneath as an indented atom row.
- [ ] **Plain line arrives on `estimate`.** The hand-line agreement
  line shows an **"estimate"** chip, no nested atoms, and an
  `est was $X` reference caption.
- [ ] **Adjustment line arrives too**, its percent snapshot copied from
  the estimate — no separate "Add Adjustment" click needed for what's
  already in the agreement.
- [ ] **Estimate-less job seeds empty.** Start Invoice on the
  estimate-less prerequisite job → the draft has zero lines; the
  legacy **Apply everything** / **Copy from estimate** buttons appear
  above the (empty) table (§4).
- [ ] **One draft per job.** Clicking Start Invoice again (or from a
  different page) opens the **same** existing draft rather than
  creating a second one.
- [ ] **Billable-jobs gate.** On a `draft`/`submitted` job, Start
  Invoice is hidden; the empty state reads "No invoices yet. Invoicing
  becomes available once the job is approved."

## 2. Remaining lines and progress billing

Entry: the job with a **prior** (non-cancelled) invoice already
covering some agreement lines.

- [ ] **A second invoice seeds only what's left.** Start a second
  invoice on the same job → only agreement lines not already on the
  first (live) invoice appear. Nothing duplicates.
- [ ] **One live invoice per agreement line.** An agreement line
  referenced by a live invoice can never be seeded or restored onto a
  second live invoice at the same time — the invariant is
  server-enforced (an attempt fails with a message naming the invoice
  that already holds it).

## 3. Remove to defer; Restore to bring back

Entry: any draft invoice with agreement-seeded lines, Edit mode.

- [ ] **Remove from invoice** (never "Delete" — the word doesn't
  appear on this surface) on an agreement-backed line → the line
  disappears from the live table and reappears as a **struck row**
  (dashed, hatched background, amount shown but out of the total) at
  the bottom of the table, with a **Restore** button.
- [ ] **Restore** brings it back to a normal, editable row in place —
  no page reload, no re-navigation.
- [ ] **A removed-and-not-restored line reseeds on the next invoice.**
  Discard this draft (or send it without the line) and start a new
  invoice on the job → the removed agreement line is offered again.
- [ ] **Removing a hand line** (no agreement reference) just deletes it
  — nothing struck, nothing to restore (there was no agreement line
  behind it).

## 4. The legacy seed buttons (empty draft only)

Entry: a **draft with zero lines** — the estimate-less job from §1, or
any draft that's had every line removed.

- [ ] **Both buttons present, only on an empty draft.** "Apply
  everything" and "Copy from estimate" show above the line-items table
  only while it has zero lines; they vanish the moment any line exists
  (added by hand, seeded, or restored).
- [ ] **Apply everything** sweeps every billable job **atom** (complete
  tasks, consumed materials, submitted expenses) into one line each —
  unrelated to the agreement; these lines carry no `agreement_ref` and
  no backing controls.
- [ ] **Copy from estimate** copies the agreement's values onto plain
  lines **without** agreement references — these lines show no est-
  reference caption, no Use estimate/Use actuals controls, and no
  Restore if removed (there's nothing to restore *to* — they were
  never actually linked). Disabled once another non-cancelled invoice
  exists for the job (hover: "Not available once another invoice
  exists for this job").
- [ ] **Not-billable atoms are skipped** by Apply everything (incomplete
  task, unconsumed material) — no error, no duplicates.

## 5. Backing controls — Use estimate / Use actuals / Edit

Entry: any draft invoice line with an `agreement_ref` (seeded or
restored).

- [ ] **Use estimate** appears whenever the line has an agreement
  reference and isn't already on `estimate` backing — clicking resets
  qty/price to the agreement's own stored values.
- [ ] **Use actuals** appears whenever the line is on `estimate` or
  `edited` backing **and** has claimed actuals to derive from —
  clicking re-prices from `round(actuals ÷ qty, 2)` and flips the chip
  to `actuals`.
- [ ] **Edit…** (the field modal) is always available while editable;
  changing price by hand flips the chip to `edited` and shows a
  "work totals $X" reference underneath it.
- [ ] **Attachment moves money immediately.** Pulling an uncovered-work
  atom onto a line that's currently in sync re-prices it on the spot —
  the invoice total visibly changes the moment work attaches (not just
  on Send).

## 6. Uncovered work (was "Show Billables")

Entry: any draft invoice, Edit mode — **always visible**, no toggle.

- [ ] **No separate button.** The "Uncovered work" section renders
  below the line-items table on every editable draft; an
  agreement-less/atom-less job simply shows its empty-state text
  rather than hiding the section.
- [ ] **Object-first selection.** Ticking a row makes every existing
  line offer **"Add selected here"**, and a dashed **"＋ New line from
  selected"** placeholder appears at the table's foot.
- [ ] **"Bill as its own line"** on an unticked row creates (and opens
  the Edit modal for) a standalone line from that one atom.
- [ ] **INVOICED-elsewhere chip.** An atom already claimed by another
  invoice shows an amber "invoiced — INV-xxxx" chip and its checkbox is
  disabled.
- [ ] **"cancelled — work done" chip.** A cancelled task with recorded
  actuals is still billable — it shows this chip rather than
  disappearing, so billing it is a conscious choice.
- [ ] **"descoped by CO-N" chip** (2026-08-09, was "struck from
  agreement"). A task/material an accepted change order **removed**
  (not replaced — a replace moves the claim onto the CO's line instead
  of descoping the atom, so a replaced atom never shows this chip) —
  while the atom itself stayed live — shows this chip, `CO-N` naming the
  change order that descoped it. Suppressed on a cancelled task
  (cancelled wins; one amber chip is enough).
- [ ] **Deposit credits are separate.** Available deposit credits render
  in their own section (§"Deposits") with a one-click "Apply to this
  invoice" — not part of the checkbox pool.

## 7. Adjustments (unchanged behavior + dedup)

Entry: the **Agreement Adjustments** panel on the draft invoice, plus
**Add Adjustment** in Edit mode.

- [ ] **Panel surfaces the accepted estimate's adjustments not already
  on this invoice.** Each shows its description, %, and an **Add**
  button.
- [ ] **No double-apply.** An adjustment already seeded from the
  agreement (§1) — or already added by hand — shows as **Added**
  (disabled) in the panel.
- [ ] **Add Adjustment** lets you add a percentage adjustment by hand
  (choose the rate + target categories).

## 8. Customer and Reorder modes

Entry: the `DocModeBar` at the top of the invoice, any status.

- [ ] **Customer mode** shows the collapsed document — every live line
  (struck rows excluded), no backing column, no atom rows, no buttons
  of any kind, even for an editing user.
- [ ] **Reorder mode** shows the identical rows plus an arrows column;
  arrows are disabled at the top/bottom line. Only offered while the
  invoice is editable.

## 9. The accounting-category flag & the Send-gate

This is the guardrail that keeps a category-less line from being sent
(which would mis-bill tax and break the QBO item mapping).

- [ ] **Missing category is flagged.** On a draft (editable) invoice,
  any line with **no accounting category** shows an amber **"needs
  category"** marker under its description instead of a bare "—".
- [ ] **Send is blocked until every line has a category.** While any
  line is flagged, the **Send Invoice** action is disabled and a note
  explains why.
- [ ] **Assigning the category unblocks Send.** Open the flagged
  line's **Edit…**, pick a category, save → the flag clears and Send
  becomes active.
- [ ] **Belt-and-suspenders (server side).** Even bypassing the UI, the
  send endpoint refuses (400) naming the un-categorized line number(s).
- [ ] **Read-only invoices don't flag.** On a sent/paid invoice, a
  missing category renders as "—" with no flag.

## 10. Tax note (current behavior)

- [ ] A merged/joined line takes the **single** category assigned to
  it; that category's taxability governs the **whole** line
  (per-line, not per-atom, tax treatment).

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Create | Start Invoice → auto-seeded draft (agreement job) · empty draft (estimate-less job) · one draft per job · billable-jobs gate |
| Seeding | remaining agreement lines only (progress billing) · one-live-invoice invariant · backed line arrives on `actuals` · plain line arrives on `estimate` · adjustment line copies snapshot percent |
| Remove/Restore | Remove → struck row · Restore → back to normal · not-restored line reseeds on next invoice · hand-line remove has nothing to restore |
| Legacy seed buttons | Apply everything (atom sweep, no agreement_ref) · Copy from estimate (plain copy, no agreement_ref) · both hidden once any line exists · Copy disabled on a repeat invoice |
| Backing controls | Use estimate resets to agreement values · Use actuals re-derives from claims · Edit… flips to `edited` · attachment re-prices immediately |
| Uncovered work | always visible, no toggle · object-first selection · Add selected here / New line from selected / Bill as its own line · INVOICED-elsewhere chip · cancelled chip · struck-from-agreement chip (suppressed on cancelled) · deposit credits in their own section |
| Adjustments | panel dedup (Added when already seeded or hand-added) · Add Adjustment by hand |
| Modes | Customer (zero controls) · Reorder (same rows + arrows, disabled at ends, editable-only) |
| Category flag | null category flagged "needs category" when editable · not flagged when read-only |
| Send-gate | Send disabled + note while any line uncategorized · assigning category enables Send · server rejects (400) a category-less send |
