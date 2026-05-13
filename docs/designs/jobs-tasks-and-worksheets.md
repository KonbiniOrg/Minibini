# Jobs, Tasks, and Worksheets

Reference for the work-execution side of Minibini: how Jobs, Tasks, Bleps,
EstWorksheets, PlanTasks, and Templates fit together. For service-layer
mechanics, mixin catalog, permission atoms, history capture, and DELETE
conventions, see `docs/designs/architecture-and-conventions.md`. For
RateScheme / billing identity / estimate wizard / supersession, see
`docs/designs/estimates-and-prices.md`. For Material, PlanMaterial, and
TemplateMaterialAssociation, see
`docs/designs/materials-inventory-and-purchasing.md`.

## 1. Overview

A Job is the central work-tracking entity. Each Job aggregates:

- 0+ EstWorksheets (planning artifacts)
- 0+ Estimates (customer-facing quotes)
- 0+ Tasks (units of execution; live directly on the Job)
- 0+ Materials (consumable / billable items; always belong to the Job, optionally linked to a Task)
- 0+ Invoices, Purchase Orders, Bills

Tasks are the only work-execution container the system has. The former
`WorkOrder` model is gone; `Task.job` is a direct FK. Bleps (time
entries) hang off Tasks.

EstWorksheets are the planning side: they hold PlanTasks and
PlanMaterials. PlanMaterials mirror Materials — they always belong to
the worksheet, and optionally link to a PlanTask. A worksheet is a
working document that produces an Estimate; once the worksheet is
finalized, it can be carried over to a Job as actual Tasks and
Materials.

```
                       Job
                        │
        ┌─────────┬─────┴───────┬──────────────┐
        ▼         ▼             ▼              ▼
      Tasks   Materials     Invoices      EstWorksheet
        │         │         POs, Bills         │
        ▼         │                  ┌─────────┴────────┐
      Bleps      (optional FK        ▼                  ▼
                 to a Task)      PlanTasks        PlanMaterials
                                                       │
                                                  (optional FK
                                                  to a PlanTask)
```

## 2. AbstractWorkContainer

`AbstractWorkContainer` in `apps/core/models.py` is shared by `Job` and
`EstWorksheet`. The abstract base itself owns very little:

- A nullable `template` FK to `WorkTemplate` (for traceability after
  populate-from-template).
- A `populate_from_template(template)` stub that subclasses implement.

The two subclasses extend this with their own task and material
relations. Tasks and materials are reverse relations from the child
side (Task / PlanTask / Material / PlanMaterial all FK back), but
populate-from-template handles **both** kinds in a single pass:

| Subclass | Task model | Material model | populate_from_template generates |
|---|---|---|---|
| `Job` | `Task` (`Task.job`) | `Material` (`Material.job`, optional `Material.task`) | Tasks via `WorkTemplate.generate_tasks_for_job`, then Materials via `generate_materials_for_job(task_pairing=...)` |
| `EstWorksheet` | `PlanTask` (`PlanTask.worksheet`) | `PlanMaterial` (`PlanMaterial.est_worksheet`, optional `PlanMaterial.plan_task`) | PlanTasks via `generate_tasks_for_worksheet`, then PlanMaterials via `generate_materials_for_worksheet(task_pairing=...)` |

The `task_pairing` return value from the task generator is the bridge
that lets the material generator attach each new material to the right
task — critical for multi-instance template fanout.

EstWorksheet also has its own `job` FK (so a worksheet is always
attached to a Job). Job has no parent.

## 3. Job

### 3.1 Status machine

`Job` is defined at `apps/jobs/models.py` (decorated with `@history`).

| Status | Meaning |
|---|---|
| `draft` | Just created; no estimate sent yet |
| `submitted` | Estimate has been sent (auto-fired by `estimate_status_changed_for_job`) |
| `approved` | Estimate accepted; not yet released to the floor |
| `in_progress` | Released to the floor; tasks may be in flight |
| `work_complete` | All tasks terminal; invoicing/payment may still be open |
| `completed` | Fully closed (terminal) |
| `rejected` | Terminal |
| `cancelled` | Terminal |

Valid transitions (`Job.clean()` at `apps/jobs/models.py`):

```
draft         → submitted, rejected
submitted     → approved, rejected
approved      → in_progress, cancelled
in_progress   → work_complete, cancelled
work_complete → completed, cancelled
rejected, completed, cancelled → (terminal)
```

`STATUS_IN_PROGRESS` was added with the billing-atoms work; it sits
between `approved` (estimate accepted, awaiting prep) and `work_complete`
(all work done). Use the model constants (`Job.STATUS_IN_PROGRESS` etc.),
not string literals, per `CLAUDE.md`.

### 3.2 Auto-set dates

`Job.save()` at `apps/jobs/models.py`:

- On entry to `approved`: sets `start_date = now()` if unset.
- On entry to a terminal: sets `completed_date = now()` if unset.
- `created_date`, `start_date`, `completed_date` are immutable once set
  (clean() restores the old value if changed).

### 3.3 Auto-advance to work_complete

When a Task transitions to `complete` or `cancelled`,
`TaskLifecycleService._check_job_work_complete` (`apps/jobs/services.py`)
fires. If every Task on the Job is terminal:

- If the Job is `approved`, it walks through `in_progress` first to
  respect the state machine.
- Then advances to `work_complete`.

If `JobService._loose_pending_materials(job)` finds task-less materials
in pending consumption state, the auto-advance silently fails (the task
status update itself succeeds; the Job stays one rung lower). The same
guard is applied when `JobService.update_status` is called explicitly to
move a Job to `work_complete` — it raises `ValidationError`.

Entry to `work_complete` triggers
`InventoryService.release_earmarks_for_job(job)`. There is no other
side-effect on this transition.

### 3.4 Job creation paths

A new Job has no Tasks. There are four ways to populate it:

| Path | Trigger | Service | Notes |
|---|---|---|---|
| From WorkTemplate | `POST /api/jobs/{id}/populate-from-template` | `JobService.populate_from_template` | Generates Tasks + Materials from a `WorkTemplate`; sets `Job.template` FK; creates earmarks |
| From a worksheet | `POST /api/jobs/{id}/copy-from-worksheet` | `JobService.copy_from_worksheet` | Copies `PlanTask` rows to `Task` rows, including their `PlanMaterial` rows; if the worksheet has a template, links it onto the Job; creates earmarks |
| Adding a single template task | `POST /api/jobs/{id}/add-from-template` | `TaskTemplate.generate_task` | One task from a `TaskTemplate`; available to any authenticated user (workers can self-serve) |
| Direct task creation | `POST /api/jobs/{id}/tasks` | `TaskService.create_direct` | One task at a time; freeform |

A populate-from-estimate path is also exposed (`POST /api/jobs/{id}/populate-from-estimate`) but is currently a thin wrapper — most workflows go through copy-from-worksheet because the worksheet carries the planning data the estimate doesn't preserve.

`Job.template` is set as a side effect of populate-from-template /
copy-from-worksheet (when the worksheet has a template). It's purely for
traceability — nothing reads it back to drive behavior.

### 3.5 Document numbering

Job numbers are auto-generated in `JobService.create_job` via
`NumberGenerationService.generate_next_number('job')`. See `CLAUDE.md`
for the pattern/counter mechanism.

## 4. Task

`Task` is defined at `apps/jobs/models.py`. Tasks belong to a Job
via `Task.job = FK('jobs.Job', related_name='tasks')`. Hierarchy is via
`parent_task` (self-FK; subtasks emerge during work, not planning).

`Task` is **not** decorated with `@history` — see Unfinished Work.

### 4.1 Status machine

| Status | Meaning |
|---|---|
| `pending` | Default on creation; nobody has started yet |
| `in_progress` | At least one worker has clocked in (or the task was unblocked) |
| `blocked` | Work paused; carries a `blocked_reason` text field |
| `complete` | Terminal |
| `cancelled` | Terminal |

Valid transitions (`Task.VALID_TRANSITIONS` at
`apps/jobs/models.py`):

```
pending     → in_progress, blocked, complete, cancelled
in_progress → blocked, complete, cancelled
blocked     → in_progress, complete, cancelled
complete, cancelled → (terminal)
```

Note `blocked → in_progress` and `blocked → complete` and
`blocked → cancelled` — a blocked task can resume, finish, or be killed
without round-tripping through `in_progress`.

`Task.clean()` enforces transitions on save. `Task.save()` auto-assigns
`sort_order` to the next available slot for the Job if unset.

### 4.2 blocked_reason

`Task.blocked_reason` is a `TextField` capturing the current reason for
the block. It is current-state, not history. The lifecycle service:

- Sets `blocked_reason` on `block_task(reason='...')`.
- Clears it on `unblock_task`, `complete_task`, `cancel_task`.

The board's TaskCard surfaces `blocked_reason` when the task is blocked.
Block/unblock events themselves don't appear in the HistoryPanel — that
requires `@history` on Task.

### 4.3 worker_queue

`Task.worker_queue` is a nullable `PositiveIntegerField` representing
the task's position in the assignee's column on the Job Board. It's
independent of `sort_order` (which is the position within the Job's
task list). Set by drag-and-drop on the board; nulled when assignee
clears.

### 4.4 Billing fields

`Task` carries billing identity directly (declared on `Task`, mirrored
on `PlanTask` via the `TaskBase` abstract):

| Field | Description |
|---|---|
| `rate_scheme` | FK to `RateScheme` (PROTECT). Required at the DB level on Task. |
| `active_modifiers` | JSON list of modifier keys (subset of the scheme's `modifiers`) |
| `est_qty` | Estimated billable quantity in the rate scheme's units. Nullable on Task; required on PlanTask. |
| `est_worker_time` | DurationField — estimated worker time for scheduling |
| `actual_qty` | Worker-entered quantity for `ENTERED_QTY` schemes; null for `ELAPSED_TIME` (derived from bleps) and `FLAT_FEE` |

`Task.compute_amount()` resolves the actual quantity per scheme
algorithm and applies modifiers. `Task.effective_rate()` returns the
modifier-adjusted rate. The full rules — scheme algorithms, modifier
arithmetic, supersession, `is_referenced()` checks — live in the
estimates-and-prices doc.

### 4.5 Lifecycle service

`TaskLifecycleService` (`apps/jobs/services.py`) is the only
sanctioned path to transition a Task. All methods wrap in
`transaction.atomic()` and use `select_for_update()` on the Task row.

| Method | Inputs | Behavior |
|---|---|---|
| `complete_task(task_pk)` | — | pending/in_progress/blocked → complete; closes any open Bleps on the task; clears `blocked_reason`; fires job-completion check |
| `block_task(task_pk, reason='')` | reason | pending/in_progress → blocked; rejects with `{conflict, workers}` dict if open Bleps exist (caller coordinates offline) |
| `unblock_task(task_pk)` | — | blocked → in_progress; clears `blocked_reason` |
| `cancel_task(task_pk)` | — | pending/in_progress/blocked → cancelled; closes any open Bleps (no opt-out); fires job-completion check |
| `start_work(task_pk, user, action=None)` | user, optional action | First-worker-on-pending: promotes to in_progress, auto-assigns if unassigned, consumes materials, opens a Blep. Worker-on-in-progress: opens a Blep, handling join/takeover via `action` param. |
| `stop_work(task_pk, user)` | user | Closes the user's open Blep on this task; raises if none |

Material consumption happens exactly once: when the first worker calls
`start_work` on a `pending` task, `MaterialService.consume(material)`
fires for each task material. This is a side effect of the
pending→in_progress promotion, not of every clock-in.

`TaskService` (`apps/jobs/services.py`) handles structural CRUD —
`create_direct`, `create_from_template`, `update_task`, `delete_task`,
`reorder_tasks`. Deletion is rejected for `in_progress` / `complete`
tasks and for any task with at least one Blep — cancel instead.

### 4.6 Conflict resolution: join vs takeover

When `start_work` is called on a Task that's already `in_progress` and
another worker has an open Blep, the service returns a conflict
descriptor instead of opening a new Blep:

```python
{
    'conflict': 'active_worker',
    'worker': {'user_id': N, 'name': '...'},
    'blep_id': N,
    'started_at': datetime,
    'options': ['join', 'takeover'],
}
```

The client (`StartWorkConflictModal.svelte`) presents the choice. Re-call
`start_work` with `action='join'` (creates a parallel Blep — both workers
active) or `action='takeover'` (closes the other worker's Blep first,
then opens a new one).

`block_task` returns a similar conflict shape (`active_workers`, plural,
no options) when open Bleps exist — there's no override; the requester
must coordinate offline before retrying.

## 5. Blep (time tracking)

`Blep` (`apps/jobs/models.py`) is a single work session: `(task,
user, start_time, end_time)`. `end_time` is null while the session is
active. The FK to Task is `PROTECT` to preserve the audit trail.

### 5.1 Active vs historical

Two Bleps are conceptually distinct:

- **Active Blep**: `end_time IS NULL`. Created by `start_work`; closed
  by `stop_work` or by the task transitioning to a terminal state
  (complete, cancelled).
- **Historical Blep**: both timestamps set. Created via the API
  (`POST /api/bleps/`) for retroactive entry, or any Blep that has
  been closed.

`Blep.elapsed` returns a `timedelta` (uses `now()` for active bleps).
`Blep.elapsed_display` is the `Nh Mm` string the UI shows.

### 5.2 Per-user invariants

A user can have at most one active Blep across all tasks at any moment.
Any path that would create a second active Blep first calls
`BlepService._close_open(user=user)` to close the previous one.
Multiple users can have active Bleps on the same task (the "join"
case).

The 24-hour rolling rule applies to direct user edits, not to
service-driven activity:

- A user can create / edit / delete their own Blep if its `start_time`
  is within the last 24 hours.
- Editing or deleting another user's Blep, or any Blep older than 24
  hours, requires the `can_manage_time` permission atom.
- Reassigning a Blep to a different user also requires `can_manage_time`.

These rules live in `BlepService` (`apps/jobs/services.py`), not in
the serializer — `BlepPermissionError` translates to HTTP 403 in the
viewset, `ValidationError` to HTTP 400.

### 5.3 BlepService

`BlepService` is the sole write path:

| Primitive (no validation) | Use |
|---|---|
| `_create(task, user, start_time=None, end_time=None)` | Create a Blep |
| `_close_open(user=None, task=None, now=None)` | Close all open Bleps matching the filters |
| `close_user_open_bleps(user)` | Public wrapper around `_close_open(user=...)`; called by `UserAdminService` on deactivation |

| Public method | Purpose |
|---|---|
| `create_historical(actor, task, start_time, end_time, target_user=None)` | Validated historical create; 24h window + `can_manage_time` rules |
| `update(blep, actor, **fields)` | Update `start_time`, `end_time`, optionally `user`; validates ownership, window, and overlap |
| `delete(blep, actor)` | Same authorization rules |

Validation rules enforced inside `BlepService`:

1. `end_time >= start_time`
2. No interval overlap per user (open bleps are treated as
   `[start, now)` for the comparison; two different users may overlap
   on the same task)
3. 24h rolling window for non-managers (create / update / delete)

### 5.4 API

`BlepViewSet` is registered at `/api/bleps/`. Filters: `?user=me|<id>`,
`?task=<id>`, `?since=<iso>` (combined with AND). Permissions:
`IsAuthenticated` for all endpoints; the service applies the ownership
and `can_manage_time` rules.

## 6. EstWorksheet

`EstWorksheet` (`apps/estimates/models.py`, decorated with
`@history`) is the planning-side container. It belongs to a Job (FK
declared directly on EstWorksheet) and may produce an Estimate.

### 6.1 Status machine

| Status | Meaning |
|---|---|
| `draft` | Editable; tasks/materials can be added/removed |
| `final` | Locked; an Estimate has been sent (auto-set when the linked Estimate transitions to open/accepted/rejected) |
| `superseded` | Replaced by a new revision (terminal) |

Status transitions are driven externally — not by the worksheet itself
but by signals from the linked Estimate (see §11). A worksheet's status
is set automatically:

- On creation, mirrors the linked Estimate's status (draft → draft;
  open/accepted/rejected → final; superseded → superseded).
- On Estimate status change, the
  `estimate_status_changed_for_worksheet` receiver bulk-updates all
  worksheets pointing at that Estimate.
- `EstimateService.mark_open` also explicitly finalizes a draft worksheet.

### 6.2 Versioning (revision)

`EstWorksheet.create_new_version()` (or
`WorksheetService.revise_worksheet(pk)`):

1. Marks `self` as superseded.
2. Creates a new EstWorksheet with `parent=self`, `version=self.version+1`,
   `estimate=None`, status `draft`.
3. Copies all `PlanTask` rows (and their `PlanMaterial` rows) into the
   new worksheet.

Old versions stay in the database for reference. The new worksheet
starts fresh and may eventually carry its own Estimate.

### 6.3 Deletion guard

`WorksheetService.delete_worksheet` refuses to delete a worksheet that
has a linked Estimate — the Estimate must be deleted first so its line
items and source rows don't outlive the PlanTasks/PlanMaterials they
reference.

### 6.4 PlanTask vs Task

PlanTask (`apps/jobs/models.py`) is **planning** data: name,
description, billing fields (`rate_scheme`, `active_modifiers`,
`est_qty`, `est_worker_time`), `sort_order`. It has no lifecycle, no
hierarchy, no assignee, no Bleps, no materials of type `Material`.
PlanTask materials are `PlanMaterial`.

Task is the **execution** mirror: same billing fields plus `status`,
`assignee`, `parent_task`, `worker_queue`, `actual_qty`, `blocked_reason`,
plus a back-pointer `source_plan_task` for carry-over idempotency.

Both inherit from `TaskBase` (abstract). The split was introduced when
the WorkOrder model was removed: a single dual-purpose Task forced
container-branching across ~30 sites and allowed semantically invalid
states (worksheet tasks with hierarchy, etc.). After the split,
PlanTask has only the fields that make sense at planning time, and
hierarchy can only emerge during work. PlanTask is **estimable** (it
goes through the estimate wizard) but not billable on its own — billing
flows through actual Tasks.

Carry-over from worksheet to job is via `JobService.copy_from_worksheet`
(see §3.4). The carry-over preserves billing fields but always sets
`parent_task=None` — hierarchy emerges later. `Task.source_plan_task` is
a `OneToOneField` so the same PlanTask cannot be carried over twice.

### 6.5 Estimate generation

The estimate wizard reads PlanTasks and PlanMaterials as "atoms" and
groups them into EstimateLineItems via `EstimateLineItemSource` rows.
Full mechanics (atom claims, send-all-atoms, line-item recompute on
sync, plan-side claim semantics) live in
`docs/designs/estimates-and-prices.md`.

## 7. Templates

Templates power the populate-from-template paths. They feed both
worksheets (creating PlanTasks) and Jobs directly (creating Tasks).

### 7.1 Models

| Model | Path | Role |
|---|---|---|
| `WorkTemplate` | `apps/estimates/models.py` | Worksheet- or Job-shaped template; carries optional `base_price` |
| `TaskTemplate` | `apps/estimates/models.py` | A single reusable task template; carries `rate_scheme`, `default_active_modifiers`, `default_billable_qty` |
| `TemplateTaskAssociation` | `apps/estimates/models.py` | M2M-with-extras between WorkTemplate and TaskTemplate; carries `est_qty` and `sort_order` |
| `TemplateMaterialAssociation` | `apps/inventory` | Links materials to a WorkTemplate; covered in the Materials doc |

`TaskTemplate.is_active` is the soft-delete flag for task templates.
`WorkTemplate.generate_tasks_for_worksheet`,
`generate_tasks_for_job`, and the TaskTemplate picker UI all filter on
`task_template__is_active=True`. Hard-deleting a TaskTemplate would
SET_NULL the `source_template` FK on every `Task` and
`EstimateLineItem` that originated from it (losing the catalog
reference), so soft-delete is the intended path.

`WorkTemplate.is_active` exists on the model but is not currently
filtered anywhere. The model comment at `apps/estimates/models.py`
saying TaskTemplate.is_active is unused is stale.

### 7.2 generate_task

`TaskTemplate.generate_task(container, est_qty, ...)`
(`apps/estimates/models.py`) is the polymorphic creator. It reads
the container's type and creates the right kind of task:

- `EstWorksheet` → PlanTask
- `Job` → Task

It refuses to fire if the template's `rate_scheme` has been superseded
(raises `SchemeSupersededError`, which the API translates to HTTP 409).
See estimates-and-prices for the supersession story.

Optional overrides: `name`, `description`, `active_modifiers`,
`est_worker_time`, `assignee`, `sort_order`. Falls back to the
template's defaults when not provided.

### 7.3 Worksheet/Job-level generation

`WorkTemplate` exposes:

- `generate_tasks_for_worksheet(worksheet, quantity=1)` — iterates
  associations and calls `generate_task` for each, optionally
  multi-instance (returns `[(association, instance_index, plan_task), ...]`).
- `generate_tasks_for_job(job, quantity=1)` — same, for Jobs.
- `generate_materials_for_worksheet(...)` and
  `generate_materials_for_job(...)` — use the task pairing returned
  above to attach materials to the right tasks.

The `task_pairing` argument is how the materials side knows which
PlanTask / Task each generated PlanMaterial / Material belongs to —
critical for multi-instance template fanout.

## 8. Job Board

`/jobs/board` (`frontend/src/routes/jobs/JobBoardPage.svelte`) is a
kanban-style overview of all current and recently-closed jobs. All data
comes from `BoardService` (`apps/jobs/services.py`).

### 8.1 Columns

| Column | Status filter | Endpoint | Purpose |
|---|---|---|---|
| Pipeline | `draft`, `submitted`, `approved` | `GET /api/jobs/board/pipeline/` | Jobs being scoped/estimated/awaiting customer |
| In Progress (URL slug `approved`) | `in_progress` | `GET /api/jobs/board/approved/` | Active work with worker columns + unassigned pool |
| Unpaid | `work_complete` | `GET /api/jobs/board/unpaid/` | Work done; invoicing/payment outstanding |
| Closed | `completed`, `rejected`, `cancelled` (within retention) | `GET /api/jobs/board/closed/` | Terminal jobs |
| Combined | all | `GET /api/jobs/board/` | Single-fetch full board |

The legacy `approved`/`in_progress` slug mismatch is acknowledged — the
endpoint name was kept for URL stability after the column was renamed
when `STATUS_IN_PROGRESS` was added.

### 8.2 Sub-status derivation

Sub-statuses are computed (`BoardService.compute_sub_status`), not
stored. Examples (full list in `apps/jobs/services.py`):

- `needs-scoping` — no worksheet
- `estimating` — worksheet draft
- `awaiting-response` — estimate is open
- `awaiting-prep` — estimate accepted (Job in `approved`)
- `needs-tasks` — Job in `in_progress` with no tasks
- `work-ready` — all tasks pending
- `in-progress` — at least one task in progress
- `blocked` — at least one task blocked (takes priority)
- `needs-invoice` / `invoice-prepped` / `invoice-sent` — for
  `work_complete` jobs based on Invoice state

### 8.3 Configuration

`board_closed_retention_days` (Configuration key; default 14) controls
how long terminal jobs appear in the Closed column. Defined in
`fixtures/unit_test_data.json` and `nealseed.json`.

### 8.4 Worker columns

Worker columns are derived from `Task.assignee`. A column appears for
each user who has at least one active task, plus any user manually
added via the "+" button. Tasks within a column are sorted by
`worker_queue`. Drag-and-drop assigns / reorders / unassigns:

- `PATCH /api/tasks/{id}/assign/` — set assignee + worker_queue
- `POST /api/tasks/reorder/` — bulk update worker_queue from a list

### 8.5 Card composition

| Card | Component | Shows |
|---|---|---|
| Job chip (Pipeline / Approved / Unpaid) | `JobCard.svelte`, `UnpaidCard.svelte` | Job number, name, customer, deadline, sub-status pill, accent stripe (8-color palette, recycled by index) |
| Closed card | `ClosedCard.svelte` | Same plus profitability (billed / spent / profit, computed in `BoardService._compute_profitability`) |
| Task card | `TaskCard.svelte` | Task name, status dot, assignee, blocked_reason if blocked |

## 9. UI: Job Detail page

Route: `#/jobs/:id` → `JobDetailPage.svelte`.

### 9.1 Layout

Top-down:

1. **JobHeader** (`components/jobs/JobHeader.svelte`) — title `JOB
   #N: Name`, subtitle (contact / business), status pill (interactive
   `<select>` for users with `can_manage_jobs`), key dates,
   customer_po_number.
2. **Description + History** in a flex row. `HistoryPanel`
   (`components/HistoryPanel.svelte`) shows status changes, notes, and
   inline email previews.
3. **Horizontal accordion pillars** for Worksheet, Estimate, Tasks,
   Invoice, Purchase Orders. One pillar is expanded; the others render
   as vertical labels with counts. Clicking a pillar swaps the active
   one. The default open pillar follows the "furthest along" rule
   (Job complete → Invoice; has work → Tasks; has estimate → Estimate;
   else Worksheet).

### 9.2 Components

| Component | Role |
|---|---|
| `JobDetail.svelte` | Composes the page; owns accordion state, fetches related data |
| `JobHeader.svelte` | Header + status dropdown |
| `HistoryPanel.svelte` | Notes + history timeline + email entries |
| `Accordion.svelte` | Reusable expand/collapse used elsewhere |

The Worksheet pillar shows the displayed worksheet's read-only task
table (with materials nested under tasks); Estimate shows line items
with grand total; Tasks shows the active Task list; Invoice / PO
pillars are summary tables.

## 10. UI: Task Detail page

Route: `#/jobs/:jobId/tasks/:taskId` → `TaskDetailPage.svelte`.

Fetches `GET /api/tasks/{id}/` and `GET /api/bleps/?task={id}` on
mount.

### 10.1 Components

| Component | Role |
|---|---|
| `TaskActions.svelte` | Renders the status-appropriate button row (Start Work, Stop Work, Complete, Block, Unblock, Cancel) gated by status + permissions |
| `BlepList.svelte` | Table of bleps with edit / delete buttons gated by `isBlepEditable(blep, user, perms)` |
| `BlepEditModal.svelte` | Create or edit a Blep — `start_time` / `end_time` always; `user` dropdown only when actor has `can_manage_time` |
| `StartWorkConflictModal.svelte` | Shown when `start-work` returns a `conflict` payload; offers Join / Take over / Cancel |

### 10.2 Action visibility

Worker = any authenticated user. Manager = user with `can_manage_jobs`.

| Status | Worker sees | Manager additionally sees |
|---|---|---|
| pending | Start Work, Complete, Block | Cancel |
| in_progress, user is active worker | Stop Work, Complete, Block | Cancel |
| in_progress, user is not active worker | Start Work, Complete, Block | Cancel |
| blocked | Unblock | Cancel |
| complete | (read-only) | (read-only) |
| cancelled | (read-only) | (read-only) |

Worker access to Complete/Block/Unblock is intentional — workers are
the ones who discover these conditions. Cancel stays manager-only.

### 10.3 Recent Time list (home page)

`components/home/RecentTimeList.svelte` fetches
`GET /api/bleps/?user=me&since=<7d ago>`. Each row offers Edit / Delete
when the blep is within the 24h rolling window; otherwise a "Request
Edit" button — currently a stub that alerts "Not yet implemented" (see
Unfinished Work).

## 11. UI: Worksheet Detail page

Route: `#/worksheets/:id` → `WorksheetDetailPage.svelte`.

### 11.1 Components

| Component | Role |
|---|---|
| `WorksheetDetailPage.svelte` | Page shell; fetches `GET /api/est-worksheets/{id}/`; owns modal state |
| `WorksheetTaskTable.svelte` | Main table — PlanTasks with PlanMaterials nested as sub-rows; grand total footer |
| `WorkItemForm.svelte` | Modal for creating / editing PlanTasks (freeform or from template). The single modal that replaced the old PlanTaskModal / TaskModal / SubtaskModal — same component is reused on the Job/Task side for subtasks |
| `PlanMaterialModal.svelte` | Modal for creating / editing PlanMaterials; auto-fills and disables price fields when a PriceListItem is picked |
| `PriceListItemPicker.svelte` | Reusable searchable dropdown for picking a `PriceListItem`. Filters the dropdown client-side on each keystroke; reused on the Materials side. (A code comment notes server-side `?search=` filtering is a future option once the catalog grows.) |

Editing is gated to `draft` worksheets and `can_manage_jobs`. Reordering
is via up/down arrows (no drag-and-drop).

### 11.2 PlanTask detail page

Route: `#/worksheets/:wsId/plan-tasks/:planTaskId` →
`PlanTaskDetailPage.svelte`. Standalone view for a PlanTask with full
materials context. Reads `GET /api/plan-tasks/{id}/` (the standalone
endpoint that includes nested materials, worksheet, job).

PlanTask CRUD lives at the worksheet-nested endpoints:

- `GET/POST /api/est-worksheets/{id}/tasks/`
- `PATCH/DELETE /api/est-worksheets/{id}/tasks/{task_id}/`

Materials CRUD on the standalone endpoint:

- `GET/POST /api/plan-tasks/{id}/materials/`
- `PATCH/DELETE /api/plan-tasks/{id}/materials/{mid}/`

## 12. Signals

`apps/jobs/signals.py` is **empty (0 lines)**. All Job-side state
changes flow through services. This is the same inconsistency the
architecture doc flags — see `architecture-and-conventions.md` §2.3.

`apps/estimates/signals.py` (123 lines) defines three custom signals
and three receivers:

| Signal | Sender | Receiver | Effect |
|---|---|---|---|
| `estimate_status_changed_for_worksheet` | `Estimate.save()` | `update_estworksheet_status` | Bulk-updates all `EstWorksheet` rows linked to the Estimate to the mapped worksheet status (draft → draft; open/accepted/rejected → final; superseded → superseded) |
| `estimate_status_changed_for_job` | `Estimate.save()` | `update_job_status` | Walks the Job through the right status (draft → submitted → approved); creates a `HistoryEntry` action row attributed to the `system` user; refuses to downgrade or to touch completed/cancelled jobs |
| `estimate_accepted` | `Estimate.save()` (when transitioning to accepted) | `trigger_atom_carry_over` | Calls `AtomCarryOverService.carry_over_for_estimate(estimate)` to copy plan-side atoms to the Job |

`Estimate.save()` (`apps/estimates/models.py`) is what fires these.
The receivers do not currently mark estimates superseded automatically —
that happens through explicit `EstimateService.revise_estimate` calls,
which set the parent's status to superseded directly. `accepted` is
terminal; an accepted estimate cannot be superseded
(`Estimate.clean()` rejects it; `tests/test_estimate_job_status_sync.py`
covers this).

## 13. Unfinished work

- **Auto-advance Job from `approved` → `in_progress` when a task moves
  out of `pending`.** Job → `in_progress` is normally a manual user
  action (status pill on the Job detail page). The auto-advance is a
  safety net: if a worker starts work before anyone bumps the Job, the
  Job should flip to `in_progress` the moment any task transitions out
  of `pending` (via `start_work`, `complete_task`, or `cancel_task`).
  Today, no auto-advance fires until every task is terminal, at which
  point `TaskLifecycleService._check_job_work_complete` walks the Job
  through `in_progress → work_complete` in one step. Hook into the
  relevant `TaskLifecycleService` transitions.

- **`@history` decorator on `Task`.** Block, unblock, complete, cancel,
  and assignment changes don't surface in the Job HistoryPanel. Adding
  it requires converting the `Task.objects.filter(pk=...).update(...)`
  calls in `TaskLifecycleService` to `task.save()` so the change-tracker
  can capture old/new values.
- **Workflow routing soft warnings.** `populate-from-template` and
  `populate-from-estimate` don't warn when the Job has a worksheet
  (where `copy-from-worksheet` would be preferred), or when the Job
  already has tasks. Hard prerequisite gates exist; soft steering does
  not.
- **"Request Edit" button stub.** `RecentTimeList.svelte` shows an
  alert; there's no backend wiring or UI for the request-and-approve
  flow.
- **Push-notification infrastructure.** The blep-takeover flow has no
  way to notify the worker whose Blep was just closed. No notification
  system exists yet anywhere in the codebase.
- **Stale WorkOrder comment** in `apps/api/mixins.py` — the `JobTaskMixin`
  docstring references "WorkOrder removal" by name. Cosmetic; the mixin
  works.
- **Multi-instance template generation needs UI.**
  `WorkTemplate.generate_tasks_for_*` and `generate_materials_for_*`
  accept `quantity=N` but every current caller passes 1.
- **Decide on `WorkTemplate.is_active`.** Unlike `TaskTemplate.is_active`
  (which is read in three places as the soft-delete flag), the
  WorkTemplate equivalent is not filtered anywhere. Either wire up the
  same soft-delete behaviour or drop the field. Also update the stale
  "is_active no longer used" comments at `apps/estimates/models.py` —
  the one on TaskTemplate is wrong.
- **Default-worker rate-scheme + worker quick-add task flow.** Pending
  the broader billing-identity work tracked in
  `docs/designs/estimates-and-prices.md`.
