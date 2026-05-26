# Plan 3 — Billable Cancellation + All-Shipped Completion Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. TDD throughout. Checkbox steps.

**Goal:** Let a job be `cancelled` early but still billed for the work done (no new status — `cancelled` becomes billable), and add an "all deliverables shipped" precondition on `completed` (from which `cancelled` is exempt for free).

**Architecture:** `cancelled` joins `BILLABLE_JOB_STATUSES`; the blep backfill window and `actual_qty` editing extend to it; transitioning *into* `on_hold`/`cancelled` is rejected while a worker has an open Blep (the spec's "coordinate offline" rule — also closes a Plan-2 gap for `on_hold`). The job-completion logic moves into `JobService.maybe_complete_if_resolved(job)`, gated on BOTH all-invoices-resolved AND all-deliverables-shipped, called from both the invoice-paid path and `ShipmentService.mark_picked_up`. The board "Unpaid" lane queries by open unpaid invoice regardless of job status.

**Authoritative spec:** `docs/plans/2026-05-25-cancelled-with-invoice-spec.md`.

**Repo:** `/Users/drshiny/Documents/konbini/Minibini`, branch `feature/change-orders`. Commit per task.

**DB safety (CLAUDE.md):** no `migrate`/`shell`/`loaddata`/ORM-writes against dev DB; `makemigrations` only if a model field is added (none expected). `python manage.py test` fine (separate DB); one test run at a time (one implementer at a time).

**Pre-implementation audit (do first, in Task 1):** grep for any code assuming `cancelled` ⇒ no invoice / no money (P&L, profitability, invoice-cancel). `_maybe_complete_job` already no-ops on cancelled (`apps/invoicing/models.py:116`) — confirmed, so payment can't auto-complete a cancelled job.

---

### Task 1: Make `cancelled` a billable, finalizable state

**Files:** `apps/invoicing/services.py:206` (`BILLABLE_JOB_STATUSES`); `apps/jobs/services.py` (the `create_historical` call site of `_assert_job_allows_blep` ~line 775 — its `allowed_statuses`; and wherever `actual_qty` edits are gated, if at all); Tests: `tests/test_invoice_wizard*` (find it), `tests/test_blep_job_status_guard.py`.

- [ ] **Audit step:** `grep -rn "STATUS_CANCELLED" apps/ | grep -iv test` and scan for logic assuming cancelled means no billing/money. Note findings in the commit message; fix only if something would actively misbehave (likely nothing — the `ClosedCard` already shows profitability for closed jobs from invoices).
- [ ] **1a — wizard:** add `Job.STATUS_CANCELLED` to `InvoiceWizardService.BILLABLE_JOB_STATUSES`. Test: `InvoiceWizardService.open_for_job(job)` succeeds for a cancelled job (build a job with work/atoms, cancel it, open the wizard).
- [ ] **1b — backfill window:** at the `create_historical` call site, add `Job.STATUS_CANCELLED` to the `allowed_statuses` so forgotten time can be logged for billing on a cancelled job. Do NOT add it to the live `start_work` call site (no starting new live work on a stopped job). Test: `BlepService.create_historical` on a cancelled job's task succeeds; `start_work` on a cancelled job's task still raises.
- [ ] **1c — actual_qty:** verify whether editing `Task.actual_qty` is gated by job status; if it is, allow it on cancelled (so an `entered_qty` task's billable qty can be set). If it isn't gated, add a test confirming it works on a cancelled job and move on.
- [ ] Run the affected test modules + commit ("Make cancelled a billable, finalizable job state").

### Task 2: All-shipped completion gate (refactor + both triggers)

**Files:** `apps/invoicing/models.py:104` (`_maybe_complete_job`); `apps/jobs/services.py` (`JobService` — add `maybe_complete_if_resolved`; `update_job` ~line 305 — manual `completed` gate); `apps/deliverables/services.py` (`mark_picked_up` ~line 219 — trigger); Tests: `tests/test_*complete*`/`tests/test_shipment_service.py`/a new `tests/test_completion_gate.py`.

- [ ] **2a — extract + gate:** move the body of `Invoice._maybe_complete_job` into `JobService.maybe_complete_if_resolved(job)` (keep the `refresh_from_db`, the skip-if-completed/cancelled, the unresolved-invoices check, the loose-material release + history, and the walk to `completed`). ADD a new precondition: only complete if `DeliverableService.all_deliverables_shipped(job)` is True. Have `Invoice._maybe_complete_job` call `JobService.maybe_complete_if_resolved(self.job)`.
- [ ] **2b — manual gate:** in `JobService.update_job`, when the target status is `completed`, raise `ValidationError('All deliverables must be shipped before completing the job.')` if `not DeliverableService.all_deliverables_shipped(job)`. (`cancelled` is unaffected — it's not `completed`.)
- [ ] **2c — shipment trigger:** at the end of `ShipmentService.mark_picked_up`, call `JobService.maybe_complete_if_resolved(shipment.job)` so the final shipment completes a fully-paid job.
- [ ] **Tests:** a work_complete job with all invoices paid but deliverables unshipped does NOT auto-complete on payment (stays work_complete); marking the last shipment picked up THEN completes it; a fully-shipped + paid job completes via either trigger; manual `update_job(completed)` raises when unshipped; a cancelled job is never auto-completed (unchanged). Commit.

### Task 3: Reject `on_hold`/`cancelled` transition while an open Blep exists

**Files:** `apps/jobs/services.py` (`JobService.update_job` ~line 305 — guard before applying the status change); Test: `tests/test_job_on_hold.py` / a cancellation test module.

- [ ] In `JobService.update_job`, when the target status is `Job.STATUS_ON_HOLD` or `Job.STATUS_CANCELLED`, check for any open Blep (`end_time__isnull=True`) on the job's tasks; if found, raise `ValidationError('Cannot pause/cancel while a worker has an open time entry — have them stop first.')`. (This implements the spec's open-bleps-at-entry rule for both on_hold and cancel; closes the Plan-2 on_hold gap.)
- [ ] Test: moving an in_progress job with an open blep to on_hold raises; to cancelled raises; with no open blep both succeed. Commit.

### Task 4: Board "Unpaid" lane queries by invoice, not job status

**Files:** `apps/jobs/services.py` (`get_unpaid_data` ~line 1102 + `_serialize_unpaid_job` ~1242); Test: `tests/test_board_service.py`.

- [ ] Change `get_unpaid_data` to select jobs that have at least one **open, unpaid (non-cancelled) invoice**, regardless of the job's status (so a `cancelled` job with an outstanding invoice appears). Read the current query + the Invoice statuses to express "open & unpaid" correctly. In `_serialize_unpaid_job`, include the job's status so the card can badge `cancelled`/`completed`.
- [ ] Test: a cancelled job with an unpaid invoice appears in the unpaid lane with its status surfaced; a cancelled job with no invoice does not; existing work_complete-with-unpaid behavior still holds. Commit.

---

## Self-review checklist (run before execution)

- **Spec coverage:** cancelled billable + finalizable (T1, spec §3.1-3.2); all-shipped gate on completed with both triggers (T2, spec §6); reject-cancel-with-open-bleps (T3, spec §3.2); unpaid-by-invoice board (T4, spec §5); pre-impl audit (T1, spec §8). "Tasks untouched on cancellation" (spec §3.3) needs no code (cancellation already doesn't cascade to tasks) — covered by an assertion in a T1/T2 test if convenient, else a no-op. "Stays cancelled after payment" is already true (`_maybe_complete_job:116`) — confirmed, no task. ✓
- **Placeholders:** each task names exact files + line anchors + behavior + test intent; reads are called out where a current query/signature must be matched. ✓
- **Type consistency:** `JobService.maybe_complete_if_resolved(job)` and `DeliverableService.all_deliverables_shipped(job)` (Plan 1) used consistently. ✓
- **Ordering:** T1 (billable) → T2 (completion gate) → T3 (transition guard) → T4 (board). T2 depends on Plan 1's `all_deliverables_shipped` (already shipped).
