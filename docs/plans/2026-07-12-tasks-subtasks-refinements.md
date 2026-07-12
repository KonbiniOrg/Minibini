# Tasks & Subtasks refinements — integrated plan

> **STATUS: IMPLEMENTED 2026-07-12** on `feature/tasks` (all of A1–A4,
> B1–B5, C1–C3; TDD throughout). Full suites green: backend 4211 tests
> (+60 new), frontend 1163 (+25 new). Durable docs updated in the same
> pass. Awaiting RM browser review; delete this plan once reviewed.

Combined list: Claude's 2026-07-12 code/doc read-through findings + RM's
notes, integrated after a second code pass. RM ruled on the Part B items
2026-07-12 (B1–B5 decided below; the blocked-task-visibility item was
reviewed and dropped — current state is acceptable). Three parts:

- **Part A — hygiene fixes.** No decisions needed; TDD and go.
- **Part B — decided refinements.** RM has ruled; each item carries its
  resolved plan.
- **Part C — behavior redesigns.** All decided 2026-07-12; C1–C3
  redefine one permission/lifecycle matrix and should be implemented
  together.

---

## Part A — hygiene fixes

### A1. Doc drift: Task IS `@history`-tracked — but lifecycle transitions bypass it

`docs/designs/jobs-tasks-and-worksheets.md` §4 says Task is **not**
`@history`-decorated; the code has `@history(exclude=['task_id'])` at
`apps/jobs/models.py:247`. But the doc's *underlying concern is still
real*: the tracker hooks `pre_save`/`post_save` (`apps/core/history.py`),
and `TaskLifecycleService` performs every status transition via
`Task.objects.filter(pk=...).update(...)` — block, unblock, complete,
cancel, the pending→in_progress promotion, worker-queue bumps. None of
those produce a HistoryEntry — including `blocked_reason`, which is
therefore missing from task History (verified). What IS captured today:
create, edit (`update_task` → `save()`), assign (`assign` → `save()`),
reorder (`ReorderService` swaps via `save()`).

**Fix (DECIDED 2026-07-12): zero lifecycle transitions skip history.**
Convert the lifecycle `update()` calls — block, unblock, complete,
cancel, the pending→in_progress promotion — to locked check + `save()`
so the tracker sees them as audit diffs (matching how Job status
changes already work). Prerequisites, in order:

1. **Lock the task row in `BlepService.create_historical`**
   (`select_for_update()`, like `start_work` already does). Today that
   path has no lock and relies on `_promote_pending_task`'s conditional
   UPDATE for race safety; once locked, the CAS is replaceable by a
   plain check-then-`save()` in both callers.
2. **Relocate the "assignee ⇒ est_worker_time" invariant out of
   `Task.clean()`** into the explicit assign gesture
   (`TaskService.assign`, which already enforces it via
   `TaskWorkerTimeRequired`). The model-level invariant is already
   false by design: auto-assign on start (`start_work` and
   `create_historical` both set `assignee` via `update()` when the
   first worker claims an unassigned task) deliberately skips the
   est-time requirement — so such tasks exist, and a lifecycle
   `save()` running `full_clean()` would 400 their completion with
   "An assigned task must have an estimated worker time." Regression
   test: an auto-assigned task with no est_worker_time can still be
   completed/blocked/cancelled. Update §4.4's claim that clean()
   enforces it; check the schedule tolerates assigned tasks with no
   est time while in there.
3. **Add `worker_queue` to `@history(exclude=...)`** — queue position
   is cosmetic (same class as `sort_order`); the bump-to-front on every
   clock-in must not spam the audit trail regardless of write
   mechanism.

**The one surviving `update()` — documented, no longer a history
skip:** `cancel_work`'s in_progress→pending revert (inside
`BlepService._cancel_blep`, service layer only — nothing at the
viewset). `in_progress → pending` stays OUT of `VALID_TRANSITIONS`
(legalizing it would let any future save demote a started task; the
table stays strict), so the revert keeps its clean()-bypassing
`update()` — but now **writes an explicit action-type HistoryEntry**
("accidental start cancelled — reverted to pending"). This is required
for trail truthfulness: once the promotion is history-visible, an
invisible revert would leave the trail showing in_progress with an
unexplained return to pending. (Considered and rejected 2026-07-12: a
deferred-start design that would eliminate the reversion entirely —
either needs timing infrastructure the project deliberately lacks, or
a lazy pending-with-active-blep hybrid state every surface must learn,
and it breaks the consume-at-start stock gate. The start-then-undo
model stands.)

Then update the doc: fix §4's claim, rewrite the Unfinished Work entry
to whatever residue remains. TDD: block a task → assert a HistoryEntry
with the status + blocked_reason diff; same for unblock/complete/cancel;
cancel_work's revert produces the action row; hardening tests around
`cancel_work`'s three undo conditions (only-activity revert, join loses
only the blep, materials un-consume).

### A2. Subtask create bypasses the service layer

`TaskViewSet.subtasks` POST (`apps/api/tasks/views.py:154-173`) does
`serializer.save(parent_task=task, job=task.job)` directly. The sibling
path — `POST /api/jobs/{id}/tasks/` via `JobTaskMixin` — goes through
`TaskService.create_direct`. The bypass skips:

- `_assert_job_not_on_hold` (subtasks can be added to a held job),
- the superseded-rate-scheme rejection,
- `JobService.mark_work_reopened` (a new subtask on a `work_complete`
  job does not reopen it — contradicts the §3.1 invariant that
  `work_complete` means every task is terminal).

**Fix:** route the POST through `TaskService.create_direct(job=task.job,
..., parent_task_id=task.pk)`, keeping the serializer for input
validation only. TDD: on-hold 400, superseded scheme 400,
work_complete→in_progress reopen on subtask create. (B1's depth guard
lands in the same service method.)

### A3. Dead buttons on the task-detail subtask tree

`TaskDetailPage.svelte` passes no-op `onEditTask`/`onDeleteTask` to the
subtask `TaskTree` and leaves `onCancelTask` at its no-op default — but
`TaskTree` renders edit/del/cancel unconditionally when not readonly, so
those subtask-row buttons render and do nothing. It also passes an
`onDeleteMaterial` prop `TaskTree` doesn't declare (silently ignored).

**Fix:** extend `TaskTree`'s null-guard pattern (already used for the
material-op callbacks) to the task-op callbacks: default
`onEditTask`/`onDeleteTask`/`onCancelTask`/`onAddSubtask` to `null` and
render each button only when wired. Then decide per-surface: wire real
handlers on TaskDetailPage or drop the buttons there. Remove the stray
`onDeleteMaterial` prop. Update `TaskTree.test.js` /
`TaskDetailPage.test.js`.

*(Note: B3 adds subtask reorder arrows on this page, and C1–C3 change
who sees which buttons; do A3's null-guard mechanics first, then wire
per the matrix.)*

### A4. Stale permission comment in JobViewSet

`apps/api/jobs/views.py:80-83` says "Editing/deleting a task (the
task_detail action) … stay manager-or-PM via the fall-through" — but
`task_detail` is in `authenticated_only_actions` (line 76), so
edit/delete are open to any authenticated user (which matches the docs
and B5's decision). Fix the comment — or fold into the C-matrix work,
which touches these permissions anyway.

---

## Part B — decided refinements

### B1. One level of subtasks — enforce it *(DECIDED)*

Nothing prevents a subtask of a subtask today — `POST
/api/tasks/{id}/subtasks/` on a task that is itself a child, or
job-nested create with `parent_task` pointing at a child. The UI's task
tree renders exactly two levels, so a grandchild exists but is invisible
there; the one UI surface that *offers* creating one is a subtask's own
detail page (Add Subtask renders on any non-terminal task).

**Decision: two levels is the product rule.** Fix:

- Service guard in `TaskService.create_direct`: reject a `parent_task`
  that itself has a `parent_task` (covers both endpoints once A2 lands).
  Same guard anywhere reparenting could occur (`update_task` doesn't
  accept `parent_task` today — keep it that way or guard it).
- UI: hide "Add Subtask" on a subtask's detail page
  (`task.parent_task` set).
- TDD: grandchild create 400s via both endpoints; subtask detail page
  hides the affordance.

### B2. On-hold: suppress the plan-edit affordances that would 400 *(DECIDED)*

**The venue rule, stated precisely (the earlier phrasing was
ambiguous):** while a job is held, *plan* edits are frozen but
*procurement reality* stays allowed. Frozen: task add/edit/delete,
assignment, lifecycle actions, material pricing edits (Set pricing /
edit), restock/release. Allowed: Order, Attach expense, Mark
on-hand / Mark received — recording purchases and arrivals that happen
regardless of the hold. The material buttons in `TaskTree` already
implement this split via the `jobOnHold` prop; the gap is that the
**task-op** buttons ignore it.

**Decision: suppress the buttons that would 400.** Fix:

- `TaskTree`: gate edit/del/cancel/+sub/+mat (and the assign affordance)
  on `!jobOnHold`, exactly like the pricing actions.
- `TasksPanel`: hide "Add Work" while held (server blocks all three
  routes); keep "Add Expense" (procurement reality — expense create is
  not held-blocked).
- `canMarkWorkComplete()` (`frontend/src/lib/jobActions.js`): take the
  job (or an `onHold` arg), return false while held — its own comment
  already claims this but the code only checks status.
- `TaskDetailPage`: mirror — hide Edit Task / Add Subtask / Add
  Material / lifecycle buttons while the job is held (page already
  loads the job object).
- Tests: held job renders no plan-edit affordances; Order/Attach/Mark
  received still render.

### B3. Peer-scoped reordering; subtask reorder moves to the parent's detail page *(DECIDED)*

**Findings (kept for context):** reorder permissions are consistent
(server `CanManageJobOrPM` ↔ arrows on `can_manage`). But
`TaskService.reorder_tasks` hands ALL of the job's tasks — parents and
subtasks interleaved by their shared per-job `sort_order` sequence — to
`ReorderService`, which swaps adjacent items in that flat order. The
tree displays two levels, so clicking ▼ can swap with an invisible
neighbor (a subtask): the click "does nothing" visually, or silently
reorders another task's subtasks. Arrow disabled-state is computed
against the top-level array while the swap is flat. Subtask rows have no
arrows anywhere.

**Decision: tasks swap only with peer tasks.** Part of a broader
make-subtasks-visually-clearer push (RM has more items coming):
reordering happens per peer group, and subtask reordering lives on the
**parent task's detail page**, not the job task list.

Fix:

- **Backend:** scope the reorder queryset by peer group — derive it
  from the task itself: `parent_task__isnull=True` for a top-level
  task, `parent_task=task.parent_task` for a subtask. No API change:
  `POST /api/jobs/{id}/reorder-tasks/` already takes `task_id` +
  `direction`, and the peer group falls out of the task. One queryset
  change in `TaskService.reorder_tasks`.
- **Job task list page:** arrows stay top-level-only (already true);
  with the backend peer-scoped, the existing top-level-index
  disabled-state logic becomes *correct*. No subtask arrows here —
  deliberately.
- **Parent task detail page:** add ▲▼ arrows to the subtask tree
  (gated on `can_manage`, same as the list page) wired to the same
  endpoint — the subtasks are all peers, so the backend just works.
  (`TaskTree` needs its reorder affordance to work for subtask rows
  when wired — ties into A3's null-guard rework: the arrows render
  where `onReorder` is wired.)
- Decide during implementation whether sibling-group `sort_order`
  gets renumbered per group (currently one per-job sequence);
  peer-scoped swapping works either way, so prefer no data migration.
- TDD: top-level swap skips subtasks; sibling swap stays within the
  parent; cross-group swap impossible; arrows on the detail page
  reorder siblings.

### B4. "Check Complete": hand-marking work-complete requires everything final *(DECIDED — direction changed)*

**Findings (kept for context):** auto-advance works (all tasks terminal
→ `work_complete`), except a loose pending material makes it *silently*
skip. The hand-mark endpoint (`POST /api/jobs/{id}/work-complete/`,
manager/PM, the Tasks-page button) checks ONLY loose task-less pending
materials — open tasks and task-attached pending materials sail through,
leaving a `work_complete` job with live tasks (violates the documented
invariant).

**Decision:** hand-marking never resolves leftovers itself and never
succeeds while any exist. Instead of suppressing the button, keep the
affordance as a *finder*: users on a large job can click it to get the
list of what still needs attention.

Design:

- **Server:** the endpoint gains an authoritative guard — when the job
  has any non-terminal task OR any pending material (task-attached or
  loose), it mutates nothing and returns the blocker list, e.g.
  `{'blockers': {'tasks': [{task_id, name, status}...],
  'materials': [{material_id, description, task_id|null}...]}}` (the
  no-mutation + structured-response shape follows the settle-first
  conflict precedent). With no blockers it advances as today.
- **SPA (TasksPanel):** the button reads **"Mark Work Complete"** when
  the already-loaded tree data shows no blockers, and **"Check
  Complete"** when it does — signalling it will *do a thing* (produce
  the list) but not mark. Click always POSTs; a blocker response opens
  a modal listing the unfinished tasks and unconsumed materials with a
  "resolve these first" note (rows link to the task / material).
  Server-side truth wins over the client-side label (another user may
  have changed things — the POST just comes back with blockers).
- The old bulk-resolution wrinkles (ENTERED_QTY settle-up quantities,
  zero-time completes) disappear — each task/material is resolved
  through its normal flow.
- This also softens the silent auto-advance skip: when auto-advance
  didn't fire because of a loose pending material, the button reads
  "Check Complete" and clicking it names the material.
- TDD: endpoint blocker shapes (open task / pending task-material /
  loose material / combinations; no mutation), clean path advances;
  frontend label choice + modal render + link targets.
- Doc updates: §3.3 (manual work-complete now guarded), §9.5 (button
  behavior).

### B5. Task deletion rules *(DECIDED)*

**Findings (kept for context):** delete is currently open to any
authenticated user, guarded by: status not `in_progress`/`complete`, no
bleps, not claimed by a non-draft estimate/CO, not on a live invoice,
job not held. Materials are NOT checked — `Material.task` is
`SET_NULL`, so a deleted task's materials silently detach to the job as
loose rows. Move/disassociate exists
(`POST /api/materials/{id}/assign-task/`; the tree's radio-target
"Move" + "detach" buttons).

**Decision: any logged-in worker may delete — when the remaining
requirements allow.** The full guard set:

- Any authenticated user (unchanged; no manager/PM gate).
- Job not held (existing) and not terminal — add the terminal-job check
  server-side (today it's only the UI's `jobLocked`).
- Status not `in_progress`/`complete` (existing).
- No bleps (existing).
- Not claimed by a non-draft estimate/CO; not on a live invoice
  (existing).
- **NEW: no *consumed* materials.** A task with a consumed material
  can't be deleted (consumption is inventory history that must keep its
  anchor). Rare in practice — it means someone consumed by hand on a
  still-pending task, since the no-bleps/status guards already exclude
  worked tasks. Pending materials do NOT block: they detach to the job
  as loose rows (current `SET_NULL` behavior, same destination as
  cancel's detach — earmarks unaffected). Note in passing: `released`
  tombstone rows also go loose on delete; acceptable, they carry their
  own history.
- TDD: consumed-material 400, terminal-job 400, pending-material
  detach-to-loose, all existing guards still hold.

---

## Part C — behavior redesigns (spec together: one permission/lifecycle matrix)

C1–C3 jointly redefine who may do what to a task at each status. Current
doctrine (docs §4.0): most task writes open to any authenticated user;
cancel/assign/reorder manager-or-PM; complete is terminal with no
reopen. **All three decided 2026-07-12** — implement as one coherent
matrix (permission checks, serializer flags, UI gating, and the §4.0 /
`users-and-permissions.md` doc updates land together).

### C1. Editability by status + the assignee's new powers

RM's rule (reopening was considered and **rejected** 2026-07-12 — the
complete-is-terminal freeze doctrine stands unchanged; a task needing
more work after completion gets a new sibling task, per docs §4.5):

- **pending** — editable by anyone (qty, rate scheme, description —
  everything). *[= current behavior]*
- **in_progress / blocked** — editable by `can_manage_jobs` (or PM)
  **or the task's assignee**, even when the assignee has no other
  permission. *[TIGHTENS current behavior — today any authenticated
  user may edit these; and INTRODUCES assignee as a permission
  principal, which exists nowhere else in the permission system.]*
- **complete / cancelled** — not editable, no reopen. *[= current]*

Spec points:

- **Assignee-as-principal:** implement as a service-level check in
  `TaskService.update_task` (needs the acting user passed in — today it
  takes none); expose a per-task `can_edit` computed flag on the
  serializer for the SPA (alongside the existing `can_manage`).
  Follows the `CanManageJobOrPM` precedent of object-scoped grants.
- **Doc updates:** §4.0's "worker-driven, most writes open" doctrine
  changes for in_progress/blocked; the action-visibility table and
  `users-and-permissions.md` need the new rule.

### C2. Cancellation permissions *(DECIDED)*

A task that isn't deletable must be cancellable, **with the same
permissions as delete** — per B5, that means **any authenticated
user**. Cancel is the worker's exit from a task they can no longer
delete (bleps exist); the existing settle-first prompt (own ENTERED_QTY
session) and pending-material detach behavior already handle the worker
case safely, and cancellation never destroys recorded time.

Fix:

- Drop the `CanManageJobOrPM` branch for `action == 'cancel'` in
  `TaskViewSet.get_permissions` (`apps/api/tasks/views.py:48-51`) —
  plain `IsAuthenticated`, like the other lifecycle actions.
- SPA: stop gating the cancel affordances on `can_manage` —
  `TaskTree`'s `canCancel(task) && canManage` and `TaskActions`' /
  `TaskDetailPage`'s manager-only Cancel both open up. (B2's on-hold
  suppression still applies.)
- Docs: §4.0 and §10.2's action-visibility table move Cancel from the
  "Manager additionally sees" column to the worker column;
  `users-and-permissions.md` §3 updates; fix the A4 comment in the
  same change.
- TDD: non-manager cancel succeeds (API + service); prompt/conflict
  flows unchanged for the worker case.

### C3. Cancelled tasks' actuals are billable — terminal, not complete, is the billability line *(DECIDED)*

RM's rule: a cancelled task's recorded actuals still count as billable
(whether or not they end up billed). Cancelled remains a terminal state
(reopening was rejected in C1), so the correct predicate is: **only
terminal tasks are billable** — the current "only `complete`" check is
simply wrong by one status.

**Current behavior contradicts this in two places**
(`apps/invoicing/services.py`):

- the invoice source pool **excludes cancelled tasks entirely**
  (`.exclude(status=Task.STATUS_CANCELLED)`, line 618), and
- the billability predicate marks any non-`complete` task
  `not_billable` (`task_incomplete`, line 604).

`Task.compute_amount()` itself works fine on a cancelled task (sums
bleps / actual_qty), and the system already has the doctrine precedent:
`BILLABLE_JOB_STATUSES` includes *cancelled jobs* precisely so work done
before a stop can be invoiced. Fix:

- **Invoice pool:** drop the `.exclude(status=CANCELLED)` — cancelled
  tasks appear in the pool.
- **Billability:** not-terminal → `not_billable` (`task_incomplete` as
  today); terminal (`complete` OR `cancelled`) → billable. Label
  cancelled rows distinctly in the wizard pool (e.g. "cancelled — work
  done") so the biller makes a conscious choice. A cancelled task with
  zero actuals is still billable-terminal; its amount is just $0 — no
  special case needed.
- **Estimate pool: cancelled tasks stay OUT.** Estimates project
  planned work (`est_qty`); a cancelled task is not planned work.
  Verify the estimate-side pool's current filtering and add the
  exclusion if missing — the situation (estimating a job that already
  has a cancelled task) should be vanishingly rare, but the rule should
  hold.
- Tests: invoice pool contents + billability for cancelled-with-bleps,
  cancelled-without-actuals ($0, billable), cancelled entered_qty with
  actual_qty; estimate pool excludes cancelled.

---

## Incoming (from RM's other list)

_(append here)_
