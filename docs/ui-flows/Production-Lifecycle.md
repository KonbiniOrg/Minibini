# Production Lifecycle — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the core state
machine: what actually happens when work runs — job status transitions and
their gates, task start → earmark/shortfall/consumption, timeslips accruing
into actuals, the completion cascade, and material states
(pending → consumed / released) across all of it. This is the seam between
three domains; the neighboring docs own their angles and are cross-linked:
`Expenses.md` §5–6 (stock receipts, cost-at-consumption, the top-up),
`Inventory.md` (catalog ops, write-off, merge), `Deletion-and-Retirement.md`
(what delete/cancel leave behind).

Authoritative behavior: `docs/designs/jobs-and-tasks.md` §3–5,
`docs/designs/materials-inventory-and-purchasing.md` §3–5.

## Personas

- **Worker** — no atoms. Starts/stops work, completes tasks, enters
  quantities. Cannot cancel tasks, change job status, or hold/release.
- **Jobs manager** — `can_manage_jobs` (or the job's `project_manager`,
  scoped to that job). Status pill, hold/release, reorder, Mark Work
  Complete. (Task *cancel* is a worker operation — opened 2026-07-12,
  sharing delete's principal set.)
- **Time manager** — `can_manage_time`. Can start/stop a timeslip *for
  another worker* (`on behalf of`), and edit/delete others' timeslips.

## Dev notes

- User-visible text says **timeslip**; the model/API says Blep.
- The consumption flows below interact with the two parked Expenses
  drift findings (`e2e/specs/expenses/creating-expenses.spec.js`
  fixmes): every catalog-item expense purchase is currently a stock
  receipt, and MaterialPicker still shows cost-item fields for them.
  Consumption itself (task-start side) is unaffected.
- `blep_minimum_minutes` (Configuration) controls the sub-minimum undo
  in §5; the e2e seed sets it to 1.

## Prerequisites (test-data setup)

- [ ] An **`approved` job** with pending Tasks, one carrying an
  **in-stock** item-backed Material (QOH ≥ quantity) — the happy
  consumption path (§2).
- [ ] A pending Task whose item-backed Material's **quantity exceeds
  QOH** — the shortfall block (§3).
- [ ] One Task on an **`elapsed_time`** rate scheme and one on
  **`entered_qty`** — the two actuals models (§4–5).
- [ ] A **`draft` job** with a Task + in-stock Material — pre-approval
  work (§8).
- [ ] A job with a **loose (task-less) pending Material** — the
  work-complete gate (§6).
- [ ] A **`work_complete` job** — reactivation (§7).
- [ ] Two workers — join/takeover and on-behalf-of need a second body.

---

## 1. Start Work — first clock-in promotes, consumes, advances

Entry points: **Start Work** on the task detail page
(`#/jobs/{jobId}/tasks/{taskId}`) and the task list; the Home assigned-task
list.

- [ ] **Promotion:** Start Work on a `pending` task → task `in_progress`;
  the timeslip band (top of every page) shows the running session.
- [ ] **Auto-assign:** if the task had no assignee, the starting worker
  becomes the assignee.
- [ ] **Job auto-advance:** the `approved` job advances to `in_progress`
  the moment work starts. (Status pill on the job page reflects it without
  a reload of context.)
- [ ] **Materials consume exactly once:** each of the task's pending
  materials → `consumed`; the item's **QOH drops** by the quantity and the
  job's **earmark drops** by the same amount (Catalog page / earmarks tab).
  The material cost lands in the job header's **Spent** at this moment —
  cost-at-consumption (`Expenses.md` §5).
- [ ] **Join doesn't re-consume:** a second worker starting the now
  `in_progress` task gets a join/takeover choice; QOH, earmarks, and Spent
  do not move again.
- [ ] **Guard — held job:** Start Work on any task of a held job →
  blocked, "the job is on hold."
- [ ] **Guard — terminal task:** no Start Work on a `complete`/`cancelled`
  task; logging time against a complete task is rejected ("Create a new
  task for additional work").

## 2. The shortfall block (start refused, atomically)

- [ ] Start Work on a task whose item-backed material exceeds on-hand
  stock → **hard-blocked**; the error coaches *"only N on hand — reduce
  this material to N and add a second task/material for the remainder
  while it is procured."*
- [ ] **Nothing half-happens:** the task stays `pending`, no timeslip
  opens, no other material on the task is consumed (the start is atomic).
- [ ] **Workaround works:** reduce the material to on-hand quantity →
  Start Work succeeds; procure the remainder (stock-receipt expense —
  `Expenses.md` §5 — or PO) and run it as the second task/material.
- [ ] **Provisional material blocks too:** a lot-less material (no
  pricing/receipt yet) refuses consumption — "set its pricing and receive
  it before work can consume it" — never a silent flip.

## 3. Stop Work — settle-first for counted work

- [ ] **Plain stop (elapsed_time):** Stop Work closes the session; the
  task stays `in_progress`; the timeslip appears in the task's history and
  Recent Time.
- [ ] **Settle-first (entered_qty):** Stop Work on a counted task prompts
  "how many?" **before anything closes** — the session keeps running until
  the prompt resolves; entering a quantity increments the task's actual
  count and closes the timeslip in one step.
- [ ] **Settle-first on switch:** starting a *different* task while
  holding an open session on a counted task prompts to settle that session
  first; nothing mutates until resolved.
- [ ] **On-behalf-of (Time manager):** a `can_manage_time` user can stop
  (and start) another worker's session; a plain worker gets 403 trying.

## 4. Actuals — where the billable numbers come from

- [ ] **elapsed_time:** the task's actual quantity is derived from its
  timeslips — there is no manual quantity entry anywhere on the task.
- [ ] **entered_qty:** the count accrues by increments (settle prompts,
  completion settle-up). Session prompts take positive counts (or empty =
  skip); a **negative** increment is the completion settle-up's
  last-moment correction. The settled total must end positive.
- [ ] **Estimate vs. actual:** `est_qty` drives the estimate lens;
  accrued actuals drive the invoice lens — visible as the task's amounts
  on estimate vs. invoice surfaces (`Add-Line-and-Work-Authoring.md`,
  `Invoice-Seeding-and-Send.md`).

## 5. The oops-undo (sub-minimum sessions)

- [ ] Stopping a session **shorter than `blep_minimum_minutes`** cancels
  it with **full undo** instead of persisting it: the timeslip is deleted;
  if it was the sole reason the task was `in_progress`, the task reverts
  to `pending` and its materials **un-consume** (QOH and earmark restored,
  state back to `pending`).
- [ ] A session at/over the minimum cannot be cancelled — only stopped
  (the undo path rejects it).
- [ ] Job status and assignee are untouched by the undo (an
  auto-advanced job stays `in_progress`).

## 6. Complete — the cascade and the gate

- [ ] **Complete a task** (any authenticated user): open timeslips on it
  close; `blocked_reason` clears; the task freezes (§7 guards).
- [ ] **Completion settle-up (entered_qty):** Complete prompts "any more
  to add?" before closing anything; zero = nothing more; the settled total
  must be > 0.
- [ ] **Completion needs real time (elapsed_time):** completing an
  elapsed task with no logged time prompts to log a historical entry
  first — a billed task can't stand on zero time.
- [ ] **Cascade:** when the last non-terminal task completes (or
  cancels), the job advances to `work_complete` — from `approved` it walks
  through `in_progress` to respect the machine.
- [ ] **The gate:** a **loose pending material** (task-less, quantity
  still committed) blocks entry to `work_complete`. The auto-advance
  silently no-ops (task completes; job stays put).
- [ ] **Mark Work Complete / Check Complete** (Jobs manager, tasks page):
  with no blockers the button reads **"Mark Work Complete"** (confirm +
  advance); with blockers it reads **"Check Complete"** and returns the
  offending tasks/materials as a "resolve these first" list — nothing is
  bulk-resolved; each material settles via its own Consume-or-Restock
  decision.
- [ ] **Earmark sweep:** entering `work_complete` (or `cancelled` /
  `rejected`) releases the job's remaining earmarks — a finished job holds
  no reservation (earmarks tab empties for that job).

## 7. Terminal freeze, cancel-task, and reactivation

- [ ] **Terminal task freeze:** a `complete`/`cancelled` task rejects
  every edit except list reordering — "its work and billing are settled;
  corrections belong on the invoice." No new time, no reopen; more work
  means a new sibling task.
- [ ] **Cancel task** (any authenticated user): closes open timeslips;
  its *pending* materials **detach to the job as loose rows** (earmark
  kept — release by hand if unwanted); consumed rows stay attached as
  history; fires the same completion check.
- [ ] **Reactivation:** `work_complete → in_progress` via the status pill
  (Jobs manager). Adding a new task to a `work_complete` job reopens it
  **automatically** — `work_complete` means all tasks terminal, and a
  fresh open task contradicts that.
- [ ] **`completed` is out of scope here** — it additionally requires all
  invoices resolved and all deliverables shipped (`Job-Overview.md` §6).

## 8. Pre-approval work (draft/submitted jobs)

- [ ] Start Work on a `draft`/`submitted` job's task is **allowed**: the
  task advances, the **job status does not move** (auto-advance only fires
  from `approved`).
- [ ] Consumption still runs — QOH draws down — but **no earmark exists
  pre-approval** (earmarks are created for committed jobs only).
- [ ] An out-of-stock material blocks the start exactly as §2 — the
  effective pre-approval gate.
- [ ] On estimate acceptance, earmarks are created for the job's
  materials **excluding already-consumed ones** (no phantom reservation
  of stock already used).

## 9. Hold — the pause freeze

- [ ] **Hold** (Jobs manager, job page): requires a reason; **rejected
  while any timeslip on the job is open** (find the worker; stop first).
- [ ] While held: **no new timeslips** ("the job is on hold"); task /
  material / fee mutation affordances are **hidden** (task-tree edit/
  cancel/add, Add Work, the work-complete button, task-detail action
  band); status changes are blocked **except cancellation**.
- [ ] **Procurement reality stays:** Order, Attach expense, Mark
  on-hand/received, and Add Expense remain available on a held job —
  plan edits freeze, deliveries don't.
- [ ] The board keeps the held job in its true column with an ON HOLD
  banner (reason on hover); the underlying status is unchanged, so
  release resumes exactly where it was.
- [ ] **Release** is blocked while a live change order exists on the job
  (`Change-Orders.md`); CO acceptance clears the hold itself.

## 10. Guards & permissions (most-missed)

- [ ] **Worker cannot:** change the status pill, hold/release, Mark Work
  Complete, stop someone else's session (403s / hidden affordances).
  (Cancelling a task is *not* on this list — worker op since 2026-07-12.)
- [ ] **Open-timeslip guards:** hold and cancel-a-job are rejected while
  any timeslip on the job is open; block-a-task returns a conflict naming
  the active workers.
- [ ] **Invalid pill transitions rejected** — e.g. `in_progress →
  approved`, anything out of `completed`/`rejected`.
- [ ] **The status pill enforces the work-complete gate** too: PATCHing
  to `work_complete` with a loose pending material fails with the
  blocker list, same as the button path.

## 11. Approval & the status pill (2026-07-19 batch)

The header pill is value-controlled and act-labeled: one selection = one
transition, and after a transition the pill displays the job's *real*
current status — never the option that happened to sit at the clicked
index. Direct approval is gated on estimate-lessness.

- [ ] **Submitted job WITH an estimate: no direct Approved.** The pill's
  option list omits Approved — approval flows from accepting the
  estimate (the backend rejects a direct PATCH to `approved` too).
- [ ] **Submitted job with NO estimate (dead ones count): Approved is
  offered** and selecting it lands the job `approved`.
- [ ] **Release to floor.** On an `approved` job the pill names the act
  ("Release to floor"), not the status; choosing it advances the job to
  `in_progress` and the pill then DISPLAYS "In Progress" — regression:
  an uncontrolled select kept the clicked index and showed "Work
  Complete".
- [ ] **In-flight guard:** while the transition PATCH is running the
  pill is disabled — a double-click can't chain two transitions.
  *(Millisecond window; primarily a unit-test check —
  `frontend/tests/components/jobs/JobHeader.test.js`.)*
- [ ] **Estimate acceptance refreshes the header in place.** Accepting
  an open estimate via its status pill on the estimate page updates the
  job header above to Approved without a page reload.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Job transitions | approved→in_progress (auto) · →work_complete (cascade · button · pill) · gate-blocked · work_complete→in_progress (pill · auto-reopen) · hold/release (flag, not status) · cancel with open-timeslip guard |
| Task transitions | pending→in_progress (start) · →blocked(reason)→in_progress · →complete (worker) · →cancelled (manager) · in_progress→pending (oops-undo only) · terminal freeze |
| Materials | consume on first start (once) · shortfall refusal (atomic) · provisional refusal · unconsume on oops-undo · detach-to-loose on cancel-task · loose pending blocks work_complete |
| Earmarks | created on add (committed jobs) · decrement on consume · none pre-approval · acceptance excludes consumed · swept on work_complete/cancelled/rejected |
| Actuals | elapsed (derived, no entry) · entered_qty increments (settle-first on stop/switch/complete · negative correction · floor at zero · total > 0) |
| Sessions | open/close · join vs takeover · on-behalf-of (time manager) · sub-minimum undo |
| Personas | worker (start/stop/complete only) · jobs manager / PM (pill, hold, cancel, mark-complete) · time manager (others' sessions) |
| Guards | held job (timeslips + mutations + status) · terminal task · pre-approval consume w/o earmark · open-timeslip conflicts · invalid transitions |
| Status pill | value-controlled truthful display · act labels (Release to floor) · direct-Approved gating on has_estimates · in-flight disable · in-place header refresh on estimate accept (§11) |
