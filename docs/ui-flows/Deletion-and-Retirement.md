# Deletion & Retirement — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the **deletion
doctrine** (2026-07-03): committed records are never hard-deleted — they retire
through named events (cancel, release, change order, deactivate) — while
draft-phase scratch still deletes freely. Every guard here is a
should-be-blocked case, the most-missed and highest-value class to automate.
Reference: the per-object deletion rules in `docs/designs/data-constraints.md`
(and the material lifecycle in `materials-inventory-and-purchasing.md`).

**The rule under test (Rule 1):** a thing may be hard-deleted only while
*nothing references it* — no estimate/CO line claim, no invoice, no recorded
time, no consumption, no expense/PO link. Referenced things refuse with a
message naming the sanctioned path ("cancel it instead", "issue a change
order", "deactivate it instead", "remove the line first").

## Personas

- **Worker** — no atoms; can add/edit/delete tasks and own time.
- **Jobs / PM** — `can_manage_jobs` or the job's PM; fees, jobs, estimates.
- **Time** — `can_manage_time`; anyone's bleps.
- **Financials** — `can_manage_financials`; expenses, inventory.

## Prerequisites (test-data setup)

- [ ] A job with an **accepted estimate** (atom-backed task/material/fee lines)
  and a second job still in **draft** with a draft estimate.
- [ ] A **first invoice** seeded via *Copy from estimate* on the accepted job
  (claims the fee) and a task pulled onto an invoice via the wizard.
- [ ] Some **blepped time** on one task.
- [ ] A **setup fee** added by hand on the job page that no estimate has
  claimed.
- [ ] Users per persona above.

---

## 1. Fees

Entry: job task list (`#/jobs/{id}/tasklist`), Fees rows.

- [ ] **Unclaimed fee deletes freely.** Delete the hand-added setup fee → gone,
  no prompt beyond the normal action.
- [ ] **Guard — estimate-claimed fee refuses.** Delete a fee that backs an
  estimate line (even a *draft* estimate's) → 400: "backs an estimate or
  change-order line… remove the line (draft) or issue a change order."
- [ ] **Draft escape works.** On the *draft* estimate, delete the claiming line
  item first → the same fee now deletes.
- [ ] **Guard — invoiced fee refuses.** A fee on a live invoice → 400 "remove it
  from the invoice first."

## 2. Tasks

Entry: job task list, task rows (any authenticated user may delete).

- [ ] **Unclaimed pending task deletes.**
- [ ] **Guard — bleps.** A task with recorded time refuses ("has time entries…
  Cancel it instead") — pre-existing, still true.
- [ ] **Guard — sent-document claim.** A pending task claimed by an **open**
  (sent) estimate or a CO refuses ("on a sent estimate, change order, or
  invoice. Cancel it instead").
- [ ] **Draft claim still deletes.** The same task claimed only by a *draft*
  estimate deletes (the draft line loses its source row).
- [ ] **Guard — invoiced task refuses** (wizard-claimed on a live invoice).
- [ ] **Cancel remains available** in every guarded case and preserves bleps.

## 3. Bleps (time entries)

Entry: task detail blep list / time pages.

- [ ] **Own recent blep deletes** (within the 30-hour window).
- [ ] **Manager deletes anyone's blep** (`can_manage_time`), any age.
- [ ] **Guard — invoiced task freezes its time, for everyone.** Once the blep's
  task is on a live invoice, delete refuses ("its actuals are frozen") — for
  the owner *and* for `can_manage_time`.
- [ ] **Estimate claims don't freeze time.** A blep under a task claimed by a
  sent estimate (but not invoiced) still deletes normally.

## 4. Materials — released, not vanished

Entry: job task list material rows (restock), plus the automatic paths.

- [ ] **Full restock of an unclaimed material deletes the row** (scratch
  paper): quantity back to earmark/shelf, row gone.
- [ ] **Full restock of a claimed material releases it.** The row **stays**,
  greyed like a consumed one, quantity 0, with **no restock/consume actions**;
  its earmark is gone from Inventory; the estimate line that claimed it still
  shows its source.
- [ ] **Partial restock stays live.** Quantity drops, earmark follows, row still
  pending with actions.
- [ ] **Job-completion loose release keeps claimed history.** Complete a job via
  the unattended path (last invoice paid + shipment picked up) with a loose
  pending claimed material — the job's tasks all complete/cancelled → history
  records the release and the material row survives as released. *(This exact
  path used to crash the estimates page — regression-guard it.)*
- [ ] **Guard — open tasks block unattended completion.** The same trigger on a
  job with any open task is a no-op (job stays put; no release) — paying an
  invoice or picking up a shipment never closes unfinished work.
- [ ] **PO delete with the "delete" sever decision** on a claimed material
  releases it instead of deleting.
- [ ] **CO removal releases** — covered in `Change-Orders.md` §6.
- [ ] **Duplicating a job skips released materials** — the copy has no empty
  qty-0 rows.

## 5. Jobs

Entry: job list / job page delete.

- [ ] **Unworked draft quote deletes.** A draft job with only a draft estimate
  and no time/invoices hard-deletes.
- [ ] **Guard — recorded time.** Any blep on the job → 400 "has recorded time…
  Cancel it instead."
- [ ] **Guard — invoices.** Any invoice → 400.
- [ ] **Guard — sent documents.** Any non-draft estimate or change order → 400.
- [ ] **Cancel remains available** (status → cancelled) in every guarded case.

## 6. Cross-references

- [ ] **Inventory items:** delete guarded to never-referenced; write-off/demote
  never auto-delete — `Inventory.md` §2/§3/§5a.
- [ ] **Expense reject:** refused while its material is consumed *or* claimed —
  `Expenses.md` §11.
- [ ] **Documents were already doctrine-shaped:** estimates/COs/invoices/POs/
  bills delete only as drafts; sent ones supersede/reject/cancel (their own
  flow docs).

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Fee | unclaimed deletes · draft-claim refused until line removed · invoiced refused |
| Task | unclaimed deletes · blep guard · sent-claim refused · draft-claim allowed · invoiced refused · cancel always offered |
| Blep | own-window delete · manager delete · invoiced-task frozen for all actors · estimate claim doesn't freeze |
| Material | unclaimed full restock deletes · claimed full restock releases (row stays, qty 0, no actions, earmark gone, claim resolves) · partial stays live · loose release keeps claimed history · sever releases claimed · duplicate skips released |
| Job | unworked deletes · blep/invoice/sent-doc guards · cancel offered |
| Messages | every guard names the sanctioned path (cancel / change order / remove line / deactivate) |
