# Billable cancellation ("cancelled-with-invoice") — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-25
**Scope:** the third of three sequenced specs.

Sibling specs:
1. **Deliverables** — `docs/plans/2026-05-25-deliverables-spec.md`.
2. **Change orders + `on_hold`** — `docs/plans/2026-05-25-change-orders-spec.md`.
3. **Billable cancellation** — *this doc.*

---

## 1. Problem

A job sometimes has to **stop early but still be billed for the work already
done** — a change too big for a change order (the "finalize and start a new job"
escape hatch the CO/deliverables specs lean on), a rejected CO where the shop
chooses to stop rather than resume, or any pause that concludes "we're done here."
Today the Job's terminals don't cover this:

- **`completed`** — finished as agreed, fully billed/paid.
- **`cancelled`** — a dead stop that implies *no* billing.
- **`rejected`** — never started.

There's no sanctioned way to cancel a job *and* bill for partial work.

---

## 2. Decision: no new status — make `cancelled` billable

We do **not** add a `cancelled_with_invoice` status. Instead, **`cancelled`
becomes a billable state.** "With invoice" is simply whether the user opens the
invoice wizard after cancelling — a follow-on choice, not a second flavor of
cancel.

Why this over a distinct status (the alternative we rejected):

- The only thing a separate status bought was a glanceable "billed vs. dead"
  label — but that's **derivable from invoice presence** and already shown: the
  board's `ClosedCard` computes billed/spent/profit for every closed job from its
  invoices.
- Collapsing makes two interactions fall out **for free** (they were special-cases
  under a distinct status):
  - **Payment can't auto-complete a cancelled job.** `_maybe_complete_job` walks
    `approved → in_progress → work_complete → completed`; the state machine
    forbids `cancelled → completed` (cancelled only goes to `in_progress`), so a
    paid invoice leaves a cancelled job cancelled. No special handling.
  - **The new all-shipped gate (§6) exempts cancelled automatically** — cancelled
    isn't `completed`, so the gate never applies.
- One "stop the job" action, simpler mental model, less spec surface.

The cost we accept: billing/actuals-editing affordances open on **every** cancelled
job, not a narrow subset. It's opt-in (a dead-stop job just never gets an invoice)
and `can_manage_*`-gated, so benign.

---

## 3. What changes

### 3.1 Allow billing on `cancelled`

- Add `Job.STATUS_CANCELLED` to `InvoiceWizardService.BILLABLE_JOB_STATUSES`
  (currently `{approved, in_progress, work_complete, completed}`). This is the
  literal "allow billing" — `open_for_job` stops refusing.
- The invoice wizard pool is unchanged: it draws from **non-cancelled Tasks** (with
  their bleps) + Materials. Because we **do not cancel the Tasks** when cancelling
  the Job (§3.3), every task that has real work stays in the pool and is billable.
  Not-started tasks appear with zero actuals; the user simply doesn't bill them.

### 3.2 Allow actuals-finalization on `cancelled`

To bill accurately you often need to *finish* the actuals after stopping:

- **Close open bleps on entry** to `cancelled` — capture their elapsed time as
  final actuals. No running timer should survive on a stopped job. (Applies to all
  cancellation, billed or not; may be a latent gap in today's job-cancel — see
  §8.) Implemented via a job-scoped `BlepService._close_open(task=…)` sweep over
  the job's tasks.
- **Extend the blep billable/backfill window to include `cancelled`.** The guard
  today allows backfilled `create_historical` in `work_complete`; add `cancelled`
  so forgotten time for pre-stop work can be logged for billing.
- **Permit `actual_qty` edits on tasks of a cancelled job** so a partly-done
  `entered_qty` task can have its billable quantity set. (Mirrors the work_complete
  billable window.)

### 3.3 Tasks are not individually cancelled

Cancelling the Job does **not** cascade to its Tasks. They keep their state and
actuals, which is exactly what keeps them in the wizard pool (§3.1). Leaving a task
`in_progress` on a terminal job is cosmetically odd but harmless — the Job status
is authoritative and the job is off the active board. (Optional, not required:
auto-cancel only the *zero-work* tasks for tidiness. Tasks with actuals are never
cancelled, since that would drop them from the wizard.)

### 3.4 Earmarks

Entry to `cancelled` already releases earmarks (`release_earmarks_for_job`) —
unchanged. Consumed materials (on work done) stay consumed and billable.

---

## 4. The stop-and-bill flow

No new transitions — all the doorways already exist (`approved → cancelled`,
`in_progress → cancelled`, `work_complete → cancelled`, and `on_hold → cancelled`
added by the CO spec §2.1):

1. The user cancels the job (from the active band, or from `on_hold` after a
   rejected CO, or as the "too big for a CO → finalize and restart" hatch). Entry
   closes open bleps (§3.2) and releases earmarks (§3.4).
2. If there's work to bill, the user opens the **invoice wizard** (now permitted,
   §3.1), finalizes actuals as needed (§3.2), builds line items from the actuals,
   and sends to QBO via the existing path.
3. The customer pays; `qbo_payment_status` updates via polling. The job **stays
   `cancelled`** (the state machine won't let payment complete it — §2). If there's
   nothing to bill, the user simply never opens the wizard — an ordinary dead-stop
   cancellation.

Order is unconstrained: because tasks aren't cancelled and `cancelled` is in the
billable set, the user can cancel first and bill after, with no sequencing trap.

---

## 5. Visibility / board

- The board's **"Unpaid" column filters `work_complete`**, so a cancelled job with
  an **outstanding invoice won't appear there** — a real risk of losing track of
  the receivable. Surface these: expand the Unpaid query to also include cancelled
  jobs that have a non-cancelled, unpaid invoice (recommended), or lean on the
  not-yet-built standalone invoice list.
- `ClosedCard` already shows billed/spent/profit for closed jobs, so a
  cancelled-and-billed job's recovery is visible on its closed card.

---

## 6. Related rider: the "all deliverables shipped" gate on `completed`

Flagged during the brainstorm: a job shouldn't reach **`completed`** ("finished as
agreed") while ordered deliverables remain unshipped. This gate doesn't exist
today and should.

- **Where:** a precondition on entry to `completed`, enforced in **both**
  `JobService.update_job` (manual completion → `ValidationError`) and
  `_maybe_complete_job` (the payment-auto-complete path must not complete a
  not-fully-shipped job — it stays `work_complete`, paid but open).
- **Fulfillment source:** `DeliverableService.compute_fulfillment` /
  the shipment totals (deliverables spec). "All shipped" = every live Deliverable's
  `qty_picked_up == qty_ordered`.
- **`cancelled` is exempt for free** — it isn't `completed`, so the gate never
  applies. This *is* the "deliverables don't all need to ship when you stop early"
  behavior, with no special-casing.
- **Open detail (§9):** once the gate holds back a paid-but-unshipped job in
  `work_complete`, what advances it to `completed` when the last shipment lands?
  Options: a completion re-check hooked into `ShipmentService.mark_picked_up`
  (parity with the payment hook — recommended), or leave it to a manual completion.

This is a small, separable change to the *completion* flow; it's bundled here
because `cancelled`'s exemption is the reason it came up, but it can be split out
if it complicates review.

---

## 7. What we deliberately don't do

- No new status value, no new transitions.
- No cascade-cancel of Tasks (would drop their actuals from the wizard).
- No *forced* billing — the wizard is an affordance; a dead-stop cancel just never
  gets an invoice.
- No reversal of actuals — work done stays recorded and billable (consistent with
  the CO/deliverables specs).

---

## 8. Pre-implementation checks

- **Audit for code assuming `cancelled` ⟹ no invoice / no money.** This is the one
  existing assumption the collapse broadens. Believed clean (the closed card
  already handles billed-cancelled jobs via invoices), but grep before building —
  P&L/profitability, invoice-cancel behavior, any "cancelled means $0" logic.
- **Verify `_maybe_complete_job` cleanly no-ops on a cancelled job** (the state
  machine forbids `cancelled → completed`, so it should, but confirm it doesn't
  raise).
- **Confirm job-cancel doesn't already leave open bleps dangling** (and that the
  §3.2 close-on-entry sweep covers all the job's tasks, not just one user's).

---

## 9. Open decisions (recommended defaults in brackets)

1. **All-shipped gate — in this spec or split out?** *[in this spec]*, since it's
   the mechanism behind cancelled's exemption. (§6)
2. **What completes a paid-but-unshipped job after its final shipment** — a
   `mark_picked_up` completion re-check *[recommended, parity with the payment
   hook]* vs. manual completion. (§6)
3. **Tidy unfinished tasks on a cancelled job?** — leave them non-terminal
   *[recommended; keeps actuals billable, job status is authoritative]* vs.
   auto-cancel only the zero-work ones. (§3.3)
4. **Surfacing unpaid invoices on cancelled jobs** — expand the board "Unpaid"
   filter to include them *[recommended]* vs. defer to a future invoice list. (§5)

---

## 10. Out of scope / non-goals

- A distinct `cancelled_with_invoice` status (explicitly rejected, §2).
- The change-order model and `on_hold` (spec 2); the deliverable model (spec 1).
- One-click invoice generation from uninvoiced atoms (separate, already-tracked
  invoicing work) — stop-and-bill uses the normal wizard.

---

## 11. Durable-doc updates owed on completion

- `docs/designs/jobs-tasks-and-worksheets.md` — `cancelled` is billable; close
  open bleps on cancel; the all-shipped gate on `completed` (§3.3 lifecycle).
- `docs/designs/invoicing-and-expenses.md` — `BILLABLE_JOB_STATUSES` += cancelled;
  `_maybe_complete_job` all-shipped gate; the Unpaid-board surfacing of cancelled
  jobs with open invoices.
- `docs/designs/materials-inventory-and-purchasing.md` — (no change; earmark
  release on cancel already documented).
- `docs/designs/data-constraints.md` — the blep billable-window extension to
  `cancelled`; the all-shipped completion invariant.
