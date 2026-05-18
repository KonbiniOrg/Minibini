# Bugfix batch

Working plan for a batch of small-to-medium bug fixes. Each bug is
investigated and agreed individually; fixes are executed together as one
batch once the list is complete. Use TDD for every entry.

---

## Bug 1 — Auto-advance Job to IN_PROGRESS when work starts

**Desired behavior:** A Job sits in APPROVED while it waits to be detailed
enough to work on. Workers do not currently get blocked from starting work
on an APPROVED (or DRAFT) job, and that permissiveness is intentional. But
once work *does* start — a Blep begins, or a Task is marked complete — the
Job should automatically move to IN_PROGRESS.

**Root cause:** Work-start side effects live in
`TaskLifecycleService.start_work()` (`apps/jobs/services.py:573`): it
promotes the Task pending→in_progress, consumes materials, closes other
open Bleps, creates the Blep — but never touches the Job. `complete_task()`
calls `_check_job_work_complete()`, which only advances the Job when *all*
tasks are terminal, so completing one task of several leaves the Job in
APPROVED.

**Decisions:**
- Only auto-advance from APPROVED. `Job.VALID_TRANSITIONS` forbids a direct
  DRAFT/SUBMITTED→IN_PROGRESS jump, and skipping the submit/approve gates is
  wrong. For pre-APPROVED jobs the helper is a no-op (consistent with what
  `_check_job_work_complete` already does).
- Historical time counts. Logging a backfilled Blep via
  `BlepService.create_historical` on an APPROVED job also advances it.

**Changes — all in `apps/jobs/services.py`:**

1. Add `JobService.mark_work_started(job)` near `update_status` (~line 253):
   if `job.status == Job.STATUS_APPROVED`, call
   `JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)`. No-op
   otherwise. `update_status` re-fetches by pk and no-ops on equal status,
   so it composes safely with the existing `_check_job_work_complete` walk
   even when an in-memory `task.job` is stale.

2. `start_work()` — call `JobService.mark_work_started(task.job)` after the
   Blep is created, in both blep-creating branches (after the `_create` at
   ~line 607 and ~line 630). Not in the conflict-return path — no Blep is
   created there.

3. `complete_task()` — call `JobService.mark_work_started(task.job)` after
   the Task is set to COMPLETE, before `_check_job_work_complete(task)`
   (~line 482). Do **not** put it inside `_check_job_work_complete`, which
   `cancel_task` also calls — cancelling a task is not "doing work".

4. `BlepService.create_historical()` — call
   `JobService.mark_work_started(task.job)` after the `_create` (~line 141).

**Tests (TDD, in `tests/`):**
- `start_work` on an APPROVED job → Job becomes IN_PROGRESS.
- `mark_work_started` on a DRAFT/SUBMITTED job → no-op (unit-test the helper
  directly; `start_work` itself can no longer be called on those — see Bug 2).
- `complete_task` on one task of several, Job APPROVED → Job IN_PROGRESS.
- `create_historical` Blep on an APPROVED job → Job IN_PROGRESS.
- Work events on an already-IN_PROGRESS job → no error, status unchanged.
- `create_historical` on a WORK_COMPLETE job → Job stays WORK_COMPLETE
  (`mark_work_started` no-ops).

---

## Bug 2 — Reject starting a Blep when the Job status disallows it

**Desired behavior:** Defensively reject creating a Blep on a Task whose
Job is in a status where work shouldn't happen. The UI is believed to
already prevent this, but the service layer must enforce it regardless.

**Root cause:** `TaskLifecycleService.start_work()` and
`BlepService.create_historical()` validate the *Task* status but never
check the *Job* status, so a Blep can be created on a Task in a DRAFT or
SUBMITTED (etc.) Job.

**Decisions — the two flows have different allowed sets:**
- Live `start_work`: allowed Job statuses are APPROVED, IN_PROGRESS only.
  WORK_COMPLETE is excluded (work is done; the state machine has no path
  back to IN_PROGRESS); all terminal states excluded.
- Backfilled `create_historical`: allowed Job statuses are APPROVED,
  IN_PROGRESS, WORK_COMPLETE. Excluded: DRAFT, SUBMITTED, REJECTED,
  CANCELLED, COMPLETED. (You may need to log time after the fact against a
  job whose work was just marked complete.)
- Rejection is a `ValidationError` with a message naming the current
  status and the allowed set.

**Changes — all in `apps/jobs/services.py`:**

1. Add a module-level helper alongside the existing `_existing_overlaps` /
   `_within_edit_window` helpers, e.g.
   `_assert_job_status_allows_blep(job, allowed_statuses, verb)` — raises
   `ValidationError` if `job.status` is not in `allowed_statuses`.

2. `start_work()` — after fetching the Task (inside the `transaction.atomic`
   block, ~line 584), before the existing task-status check, assert
   `task.job.status` is in `(APPROVED, IN_PROGRESS)`.

3. `create_historical()` — after the task is in hand (~line 130), assert
   `task.job.status` is in `(APPROVED, IN_PROGRESS, WORK_COMPLETE)`.

**Ordering vs. Bug 1:** both bugs touch `start_work` and `create_historical`.
Bug 2's job-status guard goes near the top of each method; Bug 1's
`mark_work_started` call goes after Blep creation. No conflict — the guard
runs first, so a rejected job never reaches the auto-advance.

**Tests (TDD, in `tests/`):**
- `start_work` on a Task whose Job is DRAFT → `ValidationError`.
- `start_work` on a SUBMITTED Job → `ValidationError`.
- `start_work` on APPROVED and on IN_PROGRESS Jobs → succeeds.
- `start_work` on a WORK_COMPLETE Job → `ValidationError`.
- `create_historical` on DRAFT / SUBMITTED Jobs → `ValidationError`.
- `create_historical` on APPROVED / IN_PROGRESS / WORK_COMPLETE → succeeds.
- `create_historical` on COMPLETED / REJECTED / CANCELLED → `ValidationError`.

---

## Bug 3 — Rejected jobs missing from the board's Closed section

**Desired behavior:** The board's Closed section shows jobs that reached a
final stage within the configurable retention window. It currently shows
completed and cancelled jobs but not rejected ones; rejected jobs should
appear too.

**Root cause:** *Not* the board's status filter — both closed-section
queries (`apps/jobs/services.py:724` and `:870`) already include
`'rejected'` in `status__in=['completed', 'rejected', 'cancelled']`. The
real cause is `Job.save()` (`apps/jobs/models.py:107`): it only sets
`completed_date` for `STATUS_COMPLETED` and `STATUS_CANCELLED`. Rejected
jobs keep `completed_date = NULL`, and the board's retention filter
`completed_date__gte=cutoff` excludes NULL — so rejected jobs are dropped
regardless of the status filter. (Completed/cancelled get `completed_date`
here, confirming why they display correctly.)

**Decision:** Fix forward only — no data migration. Existing rejected jobs
keep `completed_date = NULL` and stay hidden; acceptable given the app is
pre-production and the retention window is short (~14 days default).

**Change:** `apps/jobs/models.py:107` — add `Job.STATUS_REJECTED` to the
terminal-states list:

```python
if self.status in [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED,
                    Job.STATUS_REJECTED] and not self.completed_date:
    self.completed_date = timezone.now()
```

No board/service changes needed.

**Tests (TDD, in `tests/`):**
- Transitioning a Job to REJECTED sets `completed_date`.
- A Job rejected within the retention window appears in the board Closed
  section (`BoardService.get_closed_data` / `get_board_data`).
- Regression guard: COMPLETED and CANCELLED transitions still set
  `completed_date`.

---

## Task — Update design docs

After the code fixes land, review the `docs/designs/` docs and update any
that describe behavior changed by this batch. Apply only where the doc
actually covers the affected behavior ("if applicable").

Likely touch points:
- `jobs-tasks-and-worksheets.md` — Job lifecycle: work-start (Blep begin or
  task completion) now auto-advances an APPROVED Job to IN_PROGRESS
  (Bug 1); starting a Blep is now rejected unless the Job status allows it
  (Bug 2). Note the Blep-start side-effect list and the allowed-status
  rules for live vs. historical Bleps.
- `data-constraints.md` — `completed_date` is now also set on transition to
  REJECTED, not just COMPLETED/CANCELLED (Bug 3), and is *cleared* when a
  Job is reactivated to IN_PROGRESS from WORK_COMPLETE/CANCELLED (Bug 4).
  New cross-model invariant: a Blep may only be created on a Task whose Job
  is APPROVED or IN_PROGRESS (live `start_work`), or
  APPROVED/IN_PROGRESS/WORK_COMPLETE (historical `create_historical`).
  Updated Job state machine: WORK_COMPLETE→IN_PROGRESS and
  CANCELLED→IN_PROGRESS are now valid transitions (Bug 4).
- `materials-inventory-and-purchasing.md` — earmarks are now released on
  entry to CANCELLED and REJECTED, not just WORK_COMPLETE (Bug 5).
- `architecture-and-conventions.md` — if it documents the JobService
  status-change methods: `update_job` is now the base update method that
  owns status-transition side effects; `update_status` is a thin wrapper
  (Bug 5). All Job status changes — including estimate- and invoice-driven
  ones — now route through `update_job` (Bug 6).
- `invoicing-and-expenses.md` — the all-invoices-paid job-completion handler
  now releases any loose pending materials (as restocked, not consumed) and
  records a HistoryEntry before completing the job (Bug 6).

Verify against the actual doc contents during execution; add/adjust only
the sections that genuinely describe this behavior.

---

## Bug 4 — Allow reactivating a Job from WORK_COMPLETE / CANCELLED

**Desired behavior:** A `can_manage_jobs` user can move a Job back to
IN_PROGRESS from WORK_COMPLETE (work marked done prematurely) and from
CANCELLED (undo an accidental cancellation). Exposed via the status pill on
the job view. Those are the only two new transitions.

**How status changes work:** The pill (`JobHeader.svelte`) does
`PATCH /api/jobs/{id}/` with `{status}` → `JobViewSet.perform_update` →
`JobService.update_job` → `Job.save()` → `Job.clean()`, which validates
against `VALID_TRANSITIONS`. PATCH on `JobViewSet` already resolves to
`[IsAuthenticated, CanManageJobs]`, so permission gating is automatic. The
pill keeps its own `VALID_TRANSITIONS` map — intentionally a *subset* of
the model's (it already omits work_complete's →completed/→cancelled).

**Decisions:**
- `completed_date` is cleared on reactivation — an active job must not carry
  a completed date. CANCELLED sets `completed_date`; WORK_COMPLETE does not.
  `clean()` currently protects `completed_date` as immutable
  (`models.py:72-73`), so a carve-out is needed.
- Earmarks are left untouched. The PATCH→`update_job` path never invoked
  earmark logic; `create_earmarks_for_job` would over-count consumed
  materials. Real resumed work means new tasks/materials, which earmark
  themselves.
- No reason required — consistent with the pill, which does reason-less
  PATCH for every transition including cancel.

**Changes:**

1. `apps/jobs/models.py` — `VALID_TRANSITIONS` in `clean()`:
   - `Job.STATUS_WORK_COMPLETE`: add `Job.STATUS_IN_PROGRESS`
     (→ `[COMPLETED, CANCELLED, IN_PROGRESS]`).
   - `Job.STATUS_CANCELLED`: `[Job.STATUS_IN_PROGRESS]` (was `[]`).

2. `apps/jobs/models.py` — `clean()` `completed_date` protection block
   (~lines 72-73): when `old_status in (WORK_COMPLETE, CANCELLED)` and
   `self.status == IN_PROGRESS`, set `self.completed_date = None`; otherwise
   keep the existing immutability protection. (Handled entirely in `clean()`;
   no `save()` change needed.)

3. `frontend/src/components/jobs/JobHeader.svelte` — `VALID_TRANSITIONS`
   map (lines 16-25): `work_complete: ['in_progress']`,
   `cancelled: ['in_progress']`. Update the "Mirrors Job model" comment —
   it is the subset of transitions the pill offers, not a strict mirror.

**Tests (TDD, in `tests/`):**
- Job WORK_COMPLETE → IN_PROGRESS is allowed; status updates.
- Job CANCELLED → IN_PROGRESS is allowed; status updates and
  `completed_date` is cleared to `None`.
- Regression: WORK_COMPLETE → COMPLETED / CANCELLED still valid;
  CANCELLED → any status other than IN_PROGRESS still rejected; COMPLETED
  and REJECTED remain fully terminal.
- Regression: `completed_date` immutability still holds for
  non-reactivation saves.
- Frontend has no unit tests — manually verify the pill offers "in_progress"
  from a work_complete and a cancelled job, and hides it without
  `can_manage_jobs`.

---

## Bug 5 — Release earmarks on cancel/reject; consolidate status-change side effects

**Desired behavior:** Cancelling a Job releases (deletes) its earmarks — a
dead job shouldn't hold inventory reservations. Same for REJECTED. Earmarks
are *not* restored on un-cancellation (Bug 4); once deleted they're gone.

**Root cause / current state:** `InventoryService.release_earmarks_for_job`
has exactly one caller — `JobService.update_status` (`services.py:278`),
firing only on entry to WORK_COMPLETE. There are two status-change paths:
`update_status` (has side effects) and `update_job` (none). The status pill
changes status via `PATCH → update_job`, so cancelling — and even marking
work_complete — through the pill skips earmark release entirely; only the
separate `work-complete` action (via `update_status`) releases them.

**Decision (per user): consolidate.** `update_job` becomes the base "update"
method owning both field updates and status-transition side effects;
`update_status` collapses to a thin wrapper. Earmark release then fires on
entry to WORK_COMPLETE, CANCELLED, or REJECTED regardless of caller path.

**Changes — `apps/jobs/services.py`:**

1. `update_job(pk, **kwargs)` — make it the base method:
   - Capture `old_status` before applying kwargs; after the setattr loop
     compute `new_status` / `status_changed`.
   - Pre-save: if `status_changed and new_status == WORK_COMPLETE`, run the
     loose-pending-materials check (moved verbatim from `update_status`) and
     raise `ValidationError` if offenders exist.
   - `full_clean()` + `save()` as today.
   - Post-save: if `status_changed and new_status in
     (WORK_COMPLETE, CANCELLED, REJECTED)`, call
     `InventoryService.release_earmarks_for_job(job)` (lazy import).
2. `update_status(pk, new_status)` — collapse to a thin wrapper:
   `return JobService.update_job(pk, status=new_status)`. Keep the name as a
   named entry point.
3. Add an earmark-releasing status set, e.g. a `JobService` constant
   `_EARMARK_RELEASING_STATUSES = (WORK_COMPLETE, CANCELLED, REJECTED)`.

**Naming:** `update_job` stays as the base method name (it already has the
generic `**kwargs` signature). Not renamed to `update()` — that would churn
all call sites for no functional gain. `update_status` is the one specific
wrapper.

**Caller blast radius (verified):**
- `update_job`: `api/jobs/views.py` (complete/cancel/reopen action lambdas,
  `perform_update`), `apps/jobs/views.py:216` (deprecated HTML view). All
  keep working; status-changing calls now correctly dispatch side effects.
- `update_status`: `api/jobs/views.py:160-161` (work-complete action),
  `services.py:503-504` (`_check_job_work_complete`). Keep working via the
  wrapper.
- Estimate-driven (`apps/estimates/signals.py`) and invoice-driven
  (`apps/invoicing/models.py`) job status changes mutate `job.status`
  directly, bypassing `update_job`. Folding those into the consolidation is
  Bug 6 (depends on this bug).

**Interactions:**
- Bug 1's `mark_work_started` calls `update_status` → routes through the
  consolidated `update_job`. No change in effect.
- Bug 4: cancel now deletes earmarks; un-cancel (CANCELLED→IN_PROGRESS)
  leaves them deleted — consistent with Bug 4's "earmarks left untouched."
- WORK_COMPLETE earmark release moves from `update_status` into `update_job`,
  so it now also fires for work_complete set via the pill PATCH (closes the
  latent gap).

**Tests (TDD, in `tests/`):**
- Cancelling a Job (`update_job(status=CANCELLED)`) deletes its Earmarks.
- Rejecting a Job deletes its Earmarks.
- A Job set to WORK_COMPLETE via `update_job` (the pill path) releases
  earmarks — not only via `update_status`.
- `update_status(pk, WORK_COMPLETE)` still releases earmarks and still
  blocks on loose pending materials (regression — the validation moved).
- A non-status `update_job` call (e.g. name change) releases nothing.
- CANCELLED→IN_PROGRESS (Bug 4) does not recreate earmarks.

---

## Bug 6 — Route estimate- and invoice-driven status changes through `update_job`

**Depends on Bug 5** (the consolidated `update_job` base method must exist).

**Desired behavior:** Every Job status mutation flows through
`JobService.update_job`, so side-effect dispatch is uniform. Two paths still
mutate `job.status` directly:
- `apps/estimates/signals.py:update_job_status` — direct assignment (the
  draft→submitted→approved walk plus a single-transition branch).
- `apps/invoicing/models.py` — the "complete the job once all invoices are
  paid" handler walks APPROVED→IN_PROGRESS→WORK_COMPLETE→COMPLETED by direct
  save.

**Findings:**
- History-neutral: `Job` carries the `@history` decorator, which auto-captures
  field diffs on *every* `job.save()` regardless of caller. The handlers'
  explicit `HistoryEntry.objects.create(...)` action entries are separate and
  stay.
- The invoice path passes through WORK_COMPLETE. Today (direct save) it
  bypasses both earmark release and the loose-pending-materials check.
- Loose-materials handling on the invoice path: the handler fires on
  "invoice marked paid" — anticipated to be an automated (QBO) path with no
  user to resolve anything. So rather than block, it proactively *releases*
  any loose pending materials before the status walk (decision: released,
  not consumed). Once released they no longer match
  `_loose_pending_materials`, so the WORK_COMPLETE check passes naturally —
  no exemption carve-out needed.

**Changes:**

A. `apps/estimates/signals.py` `update_job_status` — replace each
   `job.status = X; job.save()` with `JobService.update_job(job.pk, status=X)`
   (lazy import). Keep all guards and the explicit action HistoryEntries. The
   draft→submitted→approved walk becomes two sequential `update_job` calls;
   the second re-fetches by pk so it sees `submitted` — fine.

B. `apps/inventory/services.py` (or `JobService`) — add a
   `JobService.release_loose_materials(job)` helper: find task-less PENDING
   materials with qty>0 (reuse `_loose_pending_materials`), capture their
   name/qty for the audit record, then `MaterialService.restock(material,
   material.quantity)` each (full restock — earmark contribution unwound,
   quantity→0, row deleted unless expense-bound). Return the captured list.
   `restock` is always valid here (qty>0 and PENDING are guaranteed by the
   `_loose_pending_materials` filter).

C. `apps/invoicing/models.py` (the all-invoices-paid handler):
   - Before the status walk: call `JobService.release_loose_materials(job)`.
     If anything was released, create a HistoryEntry on the job recording the
     automatic release (material names/quantities) — audit trail for an
     inventory mutation triggered by payment.
   - Replace the three `job.status = X; job.save()` walk steps with
     `job = JobService.update_job(job.pk, status=X)` — **capture the return**,
     because the walk's subsequent `if job.status == ...` checks read the
     local instance, which `update_job` does not mutate in place.
   - Ordering: release loose materials first (mutates earmarks), then the
     status walk (the WORK_COMPLETE step deletes any remaining earmarks).

**Tests (TDD, in `tests/`):**
- Estimate sent (draft→open) routes the job draft→submitted via `update_job`;
  estimate accepted routes it →approved including the draft→submitted→approved
  walk. Status correct; action HistoryEntries still created.
- Invoice path: all invoices paid → job walks to COMPLETED via `update_job`;
  earmarks released (regression vs. the old direct-save path).
- Invoice path with loose pending materials present: the materials are
  released (restocked), a HistoryEntry records it, the job completes, and no
  `ValidationError` is raised.
- `release_loose_materials`: a loose PENDING material's earmark contribution
  is unwound and the row removed (quantity 0 / deleted unless expense-bound).
- Regression: estimate/invoice guards still hold (completed/cancelled jobs
  untouched; no status downgrade).
