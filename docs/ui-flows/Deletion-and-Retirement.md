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
- **Jobs / PM** — `can_manage_jobs` or the job's PM; jobs, estimates.
- **Time** — `can_manage_time`; anyone's bleps.
- **Financials** — `can_manage_financials`; expenses, inventory.

## Prerequisites (test-data setup)

- [ ] A job with an **accepted estimate** (atom-backed task/material lines,
  plus a plain hand-line) and a second job still in **draft** with a draft
  estimate.
- [ ] A **first invoice** seeded via *Copy from estimate* on the accepted job,
  plus a task pulled onto the invoice via the wizard.
- [ ] Some **blepped time** on one task.
- [ ] Users per persona above.

---

## 1. Fees (retired 2026-08-09)

The `jobs.Fee` model was deleted (`docs/plans/2026-08-06-better-fees.md`);
there is no longer a Fee entity to delete or retire, so this section's old
"Fees rows on the job task list" case no longer exists — the task list has
no Fees rows at all. A former "fee" is now just a **plain hand-line** on an
estimate/CO/invoice: no service item, no inventory item. It never becomes a
job atom, so there's nothing atom-level to guard here:

- Deleting a plain hand-line while its document is **draft** is the ordinary
  line-item delete flow (`Add-Line-and-Work-Authoring.md` §2/§6,
  `Change-Orders.md` §3) — no atom-claim guard applies, because a plain line
  never crystallizes into anything for another document to claim.
- Once the estimate is sent/accepted, its lines are read-only; dropping a
  hand-line from the agreement goes through a change-order **remove** delta
  instead (`Change-Orders.md` §3/§6), which simply removes the line — there's
  no job-side atom to retire.
- On a draft invoice, a seeded agreement hand-line deletes freely via the
  invoice's normal **delete-to-defer** (it just reappears on the next
  invoice's seeding — `Invoice-Seeding-and-Send.md`); a live invoice already
  holding an agreement line is a fact tracked on the invoice side (an
  agreement line resolves to at most one live invoice reference at a time —
  `Invoice-Seeding-and-Send.md`), not a delete-time guard on the estimate/CO.

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
| Hand-line (formerly Fee) | draft-document delete is ordinary (no atom-claim guard, retired 2026-08-09) · accepted-document removal is a CO remove delta · draft-invoice delete-to-defer |
| Task | unclaimed deletes · blep guard · sent-claim refused · draft-claim allowed · invoiced refused · cancel always offered |
| Blep | own-window delete · manager delete · invoiced-task frozen for all actors · estimate claim doesn't freeze |
| Material | unclaimed full restock deletes · claimed full restock releases (row stays, qty 0, no actions, earmark gone, claim resolves) · partial stays live · loose release keeps claimed history · sever releases claimed · duplicate skips released |
| Job | unworked deletes · blep/invoice/sent-doc guards · cancel offered |
| Messages | every guard names the sanctioned path (cancel / change order / remove line / deactivate) |
