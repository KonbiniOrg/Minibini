# Jobs, Tasks, and Work Atoms

Reference for the work-execution and fulfillment side of Minibini: how
Jobs, Tasks, Bleps, the Fee atom, Templates, Deliverables, and Shipments
fit together. For service-layer mechanics, mixin catalog, permission
atoms, history capture, and DELETE conventions, see
`docs/designs/architecture-and-conventions.md`. For RateScheme / billing
identity / estimate wizard / supersession, see
`docs/designs/estimates-and-prices.md`. For Material and
TemplateMaterialAssociation, see
`docs/designs/materials-inventory-and-purchasing.md`.

> **Job-owns-atoms model.** The Job owns its work atoms — **Task**,
> **Material**, **Fee** — directly, created at any status (including
> `draft`). The former **planning layer** (`EstWorksheet`, `PlanTask`,
> `PlanMaterial`, the worksheet API, worksheet→job carry-over) has been
> **removed**. Sections that described worksheets are kept as tombstones
> noting the removal. The `Estimate` and `Invoice` are *lenses* over the
> Job's atoms (see `estimates-and-prices.md` §7).

## 1. Overview

A Job is the central work-tracking entity. Each Job aggregates its work
**atoms** directly plus its customer-facing documents:

- 0+ **Tasks** (metered units of execution; `rate_scheme`, `est_qty`, `actual_qty`)
- 0+ **Materials** (inventory-backed or freeform; optionally linked to a Task)
- 0+ **Fees** (fixed charges: `quantity × unit_rate`; optionally linked to a Task)
- 0+ Estimates (customer-facing quotes — lens over the atoms)
- 0+ Invoices, Purchase Orders, Bills

Tasks are the only work-execution container the system has. The former
`WorkOrder` model is gone; `Task.job` is a direct FK. Bleps (time
entries) hang off Tasks.

All three atom types are created **directly on the Job** at any status
via `POST /api/jobs/{id}/tasks/`, `/materials/`, `/fees/`. There is no
separate planning container.

```
                         Job
                          │
        ┌─────────┬───────┼────────┬──────────────┐
        ▼         ▼       ▼        ▼              ▼
      Tasks   Materials  Fees   Estimates     Invoices
        │      (opt FK   (opt FK   (lens)      POs, Bills
        ▼      to Task)  to Task)
      Bleps
```

## 2. The Job and its atoms

`Job` (`apps/jobs/models.py`) extends `AbstractWorkContainer`
(`apps/core/models.py`), now a thin abstract base whose only behavior is a
`populate_from_template(template)` stub. (It was formerly shared with
`EstWorksheet`; with the worksheet model removed, `Job` is its only
concrete subclass.)

The Job's atoms are reverse relations from the child side:

| Atom | Relation | Optional task link |
|---|---|---|
| `Task` | `Task.job` (`related_name='tasks'`) | — (hierarchy via `parent_task`) |
| `Material` | `Material.job` | `Material.task` |
| `Fee` | `Fee.job` (`related_name='fees'`) | `Fee.task` (OneToOne) |

`populate_from_template` generates Tasks via
`WorkTemplate.generate_tasks_for_job`, then Materials via
`generate_materials_for_job(task_pairing=...)`. The `task_pairing` return
value from the task generator is the bridge that lets the material
generator attach each new material to the right task — critical for
multi-instance template fanout. The `WorkTemplate` is not stored on the
Job; only its generated children land there. Job has no parent.

## 3. Job

### 3.1 Status machine

`Job` is defined at `apps/jobs/models.py` (decorated with `@history`).

| Status | Meaning |
|---|---|
| `draft` | Just created; no estimate sent yet |
| `submitted` | Estimate has been sent (auto-fired by `estimate_status_changed_for_job`) |
| `approved` | Estimate accepted; not yet released to the floor |
| `in_progress` | Released to the floor; tasks may be in flight |
| `on_hold` | General pause during active work (CO negotiation, awaiting deposit, backordered material, customer gone quiet). Reachable only from `approved` / `in_progress`. |
| `work_complete` | All tasks terminal; invoicing/payment may still be open |
| `completed` | Fully closed (terminal). Gated on all deliverables shipped — see §3.3. |
| `rejected` | Terminal |
| `cancelled` | Terminal, but billable — `BILLABLE_JOB_STATUSES` includes it so a job stopped early can still be invoiced for work done (see `invoicing-and-expenses.md`) |

Valid transitions (`Job.clean()` at `apps/jobs/models.py`):

```
draft         → submitted, rejected
submitted     → approved, rejected, draft
approved      → in_progress, on_hold, cancelled
in_progress   → work_complete, on_hold, cancelled
on_hold       → approved, in_progress, cancelled
work_complete → completed, cancelled, in_progress
cancelled     → in_progress
rejected, completed → (terminal)
```

`STATUS_IN_PROGRESS` was added with the billing-atoms work; it sits
between `approved` (estimate accepted, awaiting prep) and `work_complete`
(all work done). Use the model constants (`Job.STATUS_IN_PROGRESS` etc.),
not string literals, per `CLAUDE.md`.

Estimate-driven transitions: sending an estimate fires `submitted`, and
accepting one fires `approved`. An **open** estimate going to `rejected`
(customer decline) or `expired` (the `mark_estimates_expired` sweep) drives
the Job to `rejected` — see `estimates-and-prices.md` §9.3 and §13 below.

`submitted → draft` is the **re-quote** transition: when a customer requests
changes via the portal (`estimates-and-prices.md` §15.1), the estimate
auto-revises and the Job drops back to `draft` so a draft job + draft
estimate keep it in the quoting pipeline. Such a job carries a derived
**"Revision"** badge on the board card (`BoardService.is_revision` — the live
estimate is a `draft` at `version > 1`), and the Job detail page banners the
customer's latest change-request comment (`JobSerializer.latest_change_request`).
Reverting to `draft` fires no job-status side effects.

`work_complete → in_progress` and `cancelled → in_progress` are
*reactivation* transitions — for moving a Job back into work after it was
marked complete prematurely or cancelled by accident. They are exposed on
the job-view status pill and gated by `can_manage_jobs` (the pill PATCHes
`/api/jobs/{id}/`, which already requires that atom).

#### `on_hold` semantics

`on_hold` is a general pause primitive — change orders are one consumer
of it, but not the only one. The Job carries a `hold_reason` text field
(free-form: "CO-2026-0007 in negotiation", "awaiting deposit") that the
board pill and job header surface; `Job.save()` clears it on exit to an
active status.

`on_hold` freezes and hides work **as a status query-filter** rather
than by mutating Tasks — no task is touched, so resume is instant and
lossless:

- **New bleps** are rejected (`BlepService`'s job-status guard permits
  work only on `approved` / `in_progress` / `work_complete`).
- **Task and material mutations** are blocked by `_assert_job_not_on_hold`
  in `JobService` (create/edit/delete tasks, change assignment,
  complete/block/unblock/cancel, edit materials).
- **The schedule** excludes on-hold jobs (`apps/schedule/services.py`
  filters both worker selection and the per-worker lane queries — see
  `docs/designs/schedule.md`).
- **Shipment creation** is rejected (`ShipmentService._assert_job_not_on_hold`).
- **The board** slots on-hold jobs into the Pipeline lane with an
  `on-hold` sub-status, so they stay findable but show no worker task
  columns.
- **Transition into `on_hold` is rejected while any open Blep exists**
  on the job's tasks (parallel to the cancel guard) — a manager finds
  the worker and has them stop first.
- **Exit guard**: a Job leaves `on_hold` only when no ChangeOrder on it
  is live (`draft`/`open`). The CO-accept auto-advance (`on_hold → approved`)
  is what normally clears the hold; a discarded draft CO also clears
  the guard.

### 3.1a Project manager

`Job.project_manager` is a nullable FK to `core.User`
(`on_delete=SET_NULL`, `related_name='managed_jobs'`). It is set/cleared on
the job edit page by anyone who can manage the job, and the picker draws
from all active users (`/api/auth/users/`).

**It grants access, scoped to that one job.** The PM gets
`can_manage_jobs`-equivalent rights over this job and its contained objects
(tasks, materials, fees, estimates, change orders, deliverables, and
their line items) without holding the global atom — via the
`CanManageJobOrPM` permission class and the per-object `can_manage` flag the
SPA gates on. It has **no status side effects** and grants **nothing** on
contacts/businesses or job creation. See
`docs/designs/users-and-permissions.md` → "Project-manager object access"
for the predicate, permission class, and mixins.

`JobSerializer` exposes both `project_manager` (writable PK) and
`project_manager_name` (read-only, `get_full_name() or username`). The same
display name is added to the board and schedule job payloads
(`BoardService._serialize_job`, `ScheduleService` jobs_payload) so the chip
can render it. Where the PM surfaces:

- **Job detail header** (`JobHeader.svelte`) — a "Project manager:" line
  linking to that manager's filtered job list.
- **Board in-progress + schedule top-line chip** (`JobChipStrip.svelte`,
  shared by both) — the PM's **initials** (first + last word of the name,
  uppercased) top-right on the chip, in black opposite the grey job number.
- **Job list** (`JobList.svelte`) — a PM column; the name links to the
  filtered list.
- **Filtered list** — `#/jobs?pm=<id>` (`JobListPage` passes
  `?project_manager=<id>` to the jobs list endpoint and retitles to
  "Jobs managed by <Name>").

Deliberately **not** surfaced: cross-entity search, customer-facing /
print / PDF, and job-as-reference displays on estimates / invoices / POs /
tasks.

### 3.2 Auto-set dates

`Job.save()` at `apps/jobs/models.py`:

- On entry to `approved`: sets `start_date = now()` if unset.
- On entry to `completed`, `cancelled`, or `rejected`: sets
  `completed_date = now()` if unset.
- `created_date`, `start_date`, `completed_date` are immutable once set
  (clean() restores the old value if changed) — *except* `completed_date`
  is cleared back to `None` when a Job is reactivated to `in_progress`
  from `work_complete`/`cancelled` (an active Job carries no completion
  date).

### 3.3 Auto-advance on work activity

**To `in_progress`:** when work starts on an `approved` Job — a Blep is
opened (`start_work` or `create_historical`) or a Task is completed —
`JobService.mark_work_started(job)` advances it `approved → in_progress`.
It is a no-op for any other status (pre-`approved` jobs are left alone;
the state machine forbids a direct DRAFT/SUBMITTED jump).

**To `work_complete`:** when a Task transitions to `complete` or
`cancelled`, `TaskLifecycleService._check_job_work_complete`
(`apps/jobs/services.py`) fires. If every Task on the Job is terminal:

- If the Job is `approved`, it walks through `in_progress` first to
  respect the state machine.
- Then advances to `work_complete`.

If `JobService._loose_pending_materials(job)` finds task-less materials
in pending consumption state, the auto-advance silently fails (the task
status update itself succeeds; the Job stays one rung lower). The same
guard runs inside `JobService.update_job` whenever a Job is moved to
`work_complete` — it raises `ValidationError`.

Entry to `work_complete`, `cancelled`, or `rejected` triggers
`InventoryService.release_earmarks_for_job(job)` (see
`materials-inventory-and-purchasing.md`). There is no other side-effect on
those transitions.

**To `completed`:** `JobService.maybe_complete_if_resolved(job)` is the
single completion gate, called from both the invoice-paid path
(`Invoice._maybe_complete_job` delegates to it) and
`ShipmentService.mark_picked_up` — whichever lands last completes the
job. It requires **both** all invoices resolved (`paid` or `cancelled`)
**and** all deliverables shipped
(`DeliverableService.all_deliverables_shipped(job)` returns True only
when every Deliverable's `qty_picked_up == qty_ordered`; prepared-but-
not-picked-up does not count; zero deliverables is vacuously shipped).
Manual `JobService.update_job(status=completed)` enforces the same
all-shipped precondition and raises `ValidationError` otherwise.
`cancelled` is exempt because the state machine forbids
`cancelled → completed`.

**Open-Blep entry guard.** Transitions into `on_hold` or `cancelled`
are rejected by `JobService.update_job` if any Blep on the job's tasks
is open (`end_time__isnull=True`) — same "coordinate offline" rationale
as the `block_task` conflict.

### 3.4 Job creation paths

A new Job has no atoms. Work is created **directly on the Job** at any
status (including `draft`). Ways to populate it:

| Path | Trigger | Service | Notes |
|---|---|---|---|
| From WorkTemplate | `POST /api/jobs/{id}/populate-from-template` | `JobService.populate_from_template` | Generates Tasks + Materials from a `WorkTemplate`; creates earmarks |
| Adding a single template task | `POST /api/jobs/{id}/add-from-template` | `ServiceItem.generate_task` | One Task from a `ServiceItem`; available to any authenticated user (workers can self-serve) |
| Direct task creation | `POST /api/jobs/{id}/tasks/` | `TaskService.create_direct` | One Task at a time; freeform (requires `rate_scheme_id`) |
| Direct material creation | `POST /api/jobs/{id}/materials/` | `MaterialService.create_on_job` | One Material; inventory-backed or freeform |
| Direct fee creation | `POST /api/jobs/{id}/fees/` | `FeeService.create_on_job` | One Fee (fixed charge); also the crystallization target on estimate acceptance (see `estimates-and-prices.md` §9) |

The `populate_from_template` path does not store a back-reference to the
source template on the Job. The template's role ends once its child Tasks
and Materials have been generated.

> **Removed.** The worksheet-based creation paths
> (`POST /api/jobs/{id}/copy-from-worksheet`, `populate-from-estimate`,
> `JobService.copy_from_worksheet` / `materialize_worksheet_onto_job`) are
> gone with the planning layer. There is no worksheet to carry over from —
> work is authored directly on the Job.

### 3.5 Document numbering

Job numbers are auto-generated in `JobService.create_job` via
`NumberGenerationService.generate_next_number('job')`. See `CLAUDE.md`
for the pattern/counter mechanism.

### 3.6 Job duplication

A Job can be duplicated into a brand-new Job via the "Duplicate…" link
in the SPA Job detail header (gated on the job's `can_manage` — atom or
its PM). The link
navigates to an intermediate page (`#/jobs/:id/duplicate`,
`DuplicateJobPage.svelte`) where the user chooses a **Customer**
(pre-filled from the source job's contact, editable) and a **path**
(`approved` or `estimate`), then submits.

The Customer field is a searchable picker (`ContactPicker.svelte`, built on
`SearchPicker`), not a dropdown — the contacts table is large, so it queries
`/api/contacts/?search=` (which matches first/last name, business name,
email, or phone) rather than listing every contact. It pre-fills the
source job's contact and offers a Cancel-able "Change" action.

**API:** `POST /api/jobs/{id}/duplicate/` — body `{contact_id, path}` —
returns `{job_id}` at HTTP 201. Permission: `CanManageJobs`.

`JobService.duplicate_job(source_job, *, contact, path)` in
`apps/jobs/services.py` runs the entire operation inside one
`transaction.atomic()`.

#### Always-copied fields (both paths)

- **Job metadata**: `name`, `description`, the chosen `contact`.
- **Fresh values**: a new `job_number` (via `NumberGenerationService`),
  a new `created_date`, a fresh `accent_color` (least-used from the fixed
  palette, via `_pick_least_used_accent_color`).
- **Not copied**: `customer_po_number`, `due_date`, `hold_reason`.
- **Deliverables**: each source Deliverable's `description`,
  `qty_ordered`, `units`, and `sort_order` are carried over via
  `DeliverableService.create`.
- **Work source**: work is always sourced from the source Job's live
  `Task`s and `Material`s.
- **Tasks** are copied with billing fields intact but execution state
  fully reset: `status=pending`, no bleps, no assignee, `actual_qty=None`,
  `worker_queue=None`, `blocked_reason=''`. Carried: `name`, `description`,
  `sort_order`, `est_worker_time`, `est_qty`, `rate_scheme`,
  `active_modifiers` (via `copy_active_modifiers`).
- **Materials** carry `description`, `quantity`, `units`, `unit_cost`,
  `sell_price`, `inventory_item`, `accounting_category`, and their task
  attachment (task-less materials stay loose). Inventory state is fully
  reset: `consumption_state=pending`, `restocked_qty=0`,
  `po_line_item=None`.

#### Outcome A — `path='approved'`

The new Job is created at `draft`, then walked `draft → submitted →
approved` through two calls to `JobService.update_status`. Each hop
records a `HistoryEntry` of `entry_type='action'` — "Duplicated from
\<source job_number\>" — and, because `Job` is `@history`-tracked, also
auto-creates an `audit` field-diff entry per hop. The `approved`
transition sets `start_date` (per §3.2), mirroring the
estimate-acceptance precedent in `apps/estimates/signals.py`.

- Tasks and Materials land directly on the new Job. Subtask hierarchy
  (`parent_task`) is preserved via a two-pass remap so parent Tasks are
  created before their children.
- Earmarks are created via `InventoryService.create_earmarks_for_job`.
- No estimate is created. Deliverables remain editable (no estimate →
  editable per `DeliverableService.is_editable`) until they anchor on a
  Shipment.

#### Outcome B — `path='estimate'`

The new Job stays at `draft`, with the source's `Task`s and `Material`s
copied directly onto it (same `_copy_work_to_job` core as the approved
path, including subtask hierarchy). No worksheet and no earmarks are
created — the job sits in `draft` ready for re-estimation. The user then
runs the normal Start Estimate → send → accept flow; the estimate
projects the new Job's atoms (`estimates-and-prices.md` §7).

#### Never copied (either path)

Estimates, invoices, purchase orders, bills, shipments, change orders,
history entries, and bleps are never carried over to the new Job.

## 4. Task

`Task` is defined at `apps/jobs/models.py`. Tasks belong to a Job
via `Task.job = FK('jobs.Job', related_name='tasks')`. Hierarchy is via
`parent_task` (self-FK; subtasks emerge during work, not planning).

`Task` is **not** decorated with `@history` — see Unfinished Work.

### 4.0 Write permissions

Task work is worker-driven, so most task writes are open to **any
authenticated user**:

- **Add, edit, delete** a task (`POST /api/jobs/{id}/tasks/`,
  `PATCH`/`DELETE /api/jobs/{id}/tasks/{task_pk}/`) — `IsAuthenticated`.
  Delete is still refused by `TaskService.delete_task` when the task is
  `in_progress`/`complete` or has any Bleps (→ 400) — that guard applies to
  everyone.
- **Lifecycle** — complete / block / unblock / start-work / stop-work /
  cancel-work / actual-qty are `IsAuthenticated` (worker operations).

Manager-or-PM only (`CanManageJobOrPM` — `can_manage_jobs` atom **or** the
job's `project_manager`):

- **Cancel** a task (`POST /api/tasks/{id}/cancel/`), **reorder** tasks, and
  **mark all the job's work complete** (`POST /api/jobs/{id}/work-complete/`).
- **Assign** a task to a worker (the SPA "assign" affordance).

The SPA mirrors this: `TaskTree`/`TaskActions`/`TaskDetailPage` show
add/edit/delete/complete to everyone, and gate cancel/assign/reorder/
work-complete on the per-object `can_manage` flag. See
`docs/designs/users-and-permissions.md` for the full mapping.

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

`in_progress → pending` is **not** a forward transition (and `clean()`
rejects it). `TaskLifecycleService.cancel_work` (§4.5) performs it as a
deliberate *undo* via a bulk `update()` that bypasses `clean()`,
restoring an oops-started task to its pre-Start state.

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

`Task` carries billing identity directly via the `TaskBase` abstract:

| Field | Description |
|---|---|
| `rate_scheme` | FK to `RateScheme` (PROTECT). Required at the DB level on Task. Algorithms: `elapsed_time` / `entered_qty` / `percentage` (no `flat_fee` — fixed charges are the `Fee` atom, §4.7). |
| `active_modifiers` | JSON list of modifier keys (subset of the scheme's `modifiers`); always a list, never a dict |
| `est_qty` | Estimated billable quantity in the rate scheme's units. Nullable on Task. Drives `compute_estimate_amount` (the estimate lens). |
| `est_worker_time` | DurationField — estimated worker time for scheduling. Required (and non-zero) once the Task has an `assignee`: assigned work must be schedulable. Enforced by `Task.clean()` and re-checked by `TaskService.assign`. |
| `actual_qty` | Worker-entered quantity for `ENTERED_QTY` schemes; null for `ELAPSED_TIME` (derived from bleps). Drives `compute_amount` (the invoice lens). |

`Task.compute_amount()` resolves the actual quantity per scheme algorithm
and applies modifiers (the **invoice** view); `Task.compute_estimate_amount()`
bills `est_qty` instead (the **estimate** view). `Task.effective_rate()`
returns the modifier-adjusted rate. The full rules — scheme algorithms,
modifier arithmetic, supersession, `is_referenced()` checks, the
documents-as-lenses model — live in the estimates-and-prices doc.

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
| `start_work(task_pk, user, action=None, on_behalf_of=None)` | user, optional action, optional on_behalf_of | First-worker-on-pending: promotes to in_progress, auto-assigns if unassigned, consumes materials, opens a Blep. Worker-on-in-progress: opens a Blep, handling join/takeover via `action` param. With `on_behalf_of`, a `can_manage_time` manager opens the Blep for another worker (403 otherwise). |
| `stop_work(task_pk, user, on_behalf_of=None)` | user, optional on_behalf_of | Closes the user's open Blep on this task; raises if none. A sub-minimum Blep (`< blep_minimum_minutes` whole minutes) is cancelled with full undo instead of being persisted closed — see the close-primitive note below §5.5. With `on_behalf_of`, a `can_manage_time` manager closes another worker's Blep (403 otherwise). |
| `cancel_work(task_pk, user)` | user | The under-the-minimum "oops" undo. Deletes the user's open Blep on the task; if it was the first/only activity (the sole reason the task is `in_progress`), reverts the task to `pending` and un-consumes its materials (`MaterialService.unconsume`). Job status and assignee are left alone. Rejects if the session is already ≥ `blep_minimum_minutes` (stop instead) or there is no open Blep. Own-blep only — no `on_behalf_of`. (Internally delegates to `BlepService._cancel_blep`, which the close primitive also uses.) |

Material consumption happens exactly once: when the first worker calls
`start_work` on a `pending` task, `MaterialService.consume(material)`
fires for each task material. This is a side effect of the
pending→in_progress promotion, not of every clock-in.

`TaskService` (`apps/jobs/services.py`) handles structural CRUD —
`create_direct`, `create_from_template`, `update_task`, `delete_task`,
`reorder_tasks`. Deletion is rejected for `in_progress` / `complete`
tasks and for any task with at least one Blep — cancel instead.

#### Task freeze on `complete`

`complete` is a **terminal** state: once a task is complete, its work and
billing inputs are settled.

- **All fields are frozen** except `sort_order`. `TaskService.update_task`
  raises `ValidationError` if any field other than `sort_order` is included
  in an update for a complete task:

  ```
  "Cannot edit a complete task. Its work and billing are settled;
  corrections belong on the invoice."
  ```

- **No new Bleps**: `BlepService.create_historical` (and `start_work`)
  reject new time entries against a complete task:

  ```
  "Cannot log time on a complete task. Create a new task for additional work."
  ```

- **`sort_order` exemption**: list position is cosmetic. A complete task
  embedded in a mixed list can still be reordered without touching any
  billing data.

- **No reopen**: there is no `complete → pending/in_progress` transition.
  A task that needs more work after being marked complete gets a new
  sibling task.

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
active) or `action='takeover'`.

Takeover composes existing tested logic rather than special-casing state:
it RESOLVES each displaced Blep via the shared `_resolve_open_blep` (cancel
with full undo if sub-minute — an accidental start; close, end_time floored,
if it's real work), then restarts via the normal `start_work` path. If the
cancel reverted the task to pending (the displaced sub-minute Blep was the
task's only activity), the restart re-promotes it, re-consumes materials, and
reassigns to the taking-over worker; otherwise the restart just opens the new
Blep. The restart is `action=None` with no remaining other workers, so it
terminates after one level. There is no takeover-specific state handling.

`block_task` returns a similar conflict shape (`active_workers`, plural,
no options) when open Bleps exist — there's no override; the requester
must coordinate offline before retrying.

### 4.7 Fee — the fixed-charge atom

`Fee` (`apps/jobs/models.py`, `db_table='fees'`) is the Job's third
billable atom: a **fixed charge** — `quantity × unit_rate` — that is a
pure pricing decision, not a record of work. It has no lifecycle, no
bleps, and no actuals; it is **always billable**.

| Field | Type | Notes |
|---|---|---|
| `fee_id` | AutoField PK | |
| `job` | FK → Job (CASCADE, `related_name='fees'`) | |
| `task` | OneToOne → Task (SET_NULL, nullable) | optional link to the work behind the charge |
| `description` | CharField(255), blank | |
| `quantity` | Decimal(10,2), default `1.00` | |
| `unit_rate` | Decimal(10,2) | **required** |
| `accounting_category` | FK → AccountingCategory (PROTECT) | **required, NOT NULL** |
| `sort_order` | PositiveInteger, default 0 | |

`Fee.compute_amount() → (quantity × unit_rate).quantize('0.01')`;
`effective_accounting_category` returns its own `accounting_category`;
`units` is `'none'`. Writes go through `FeeService`
(`apps/jobs/services.py`) — `create_on_job` / `update` / `delete`, all
respecting the on-hold guard — and the API at
`POST /api/jobs/{id}/fees/` (+ `PATCH`/`DELETE` at
`/api/jobs/{id}/fees/{fee_pk}/`).

A Fee is created two ways: directly by the user (the Work surface's "Fee"
add-line, §9.5), or by **estimate acceptance**, which crystallizes each
hand-authored estimate line (a line with no atom source) into a Fee on
the job and links it back via a `fee` source row (see
`estimates-and-prices.md` §9). The `Fee` replaces the old `flat_fee`
RateScheme algorithm.

## 5. Blep (time tracking)

`Blep` (`apps/jobs/models.py`) is a single work session: `(task,
user, start_time, end_time)`. `end_time` is null while the session is
active. The FK to Task is `PROTECT` to preserve the audit trail.

### 5.1 Active vs historical

Two Bleps are conceptually distinct:

- **Active Blep**: `end_time IS NULL`. Created by `start_work`; closed
  by `stop_work`, by the task transitioning to a terminal state
  (complete, cancelled), or when the worker explicitly logs out (the
  logout endpoint clocks them out — see §5.3). A session merely *expiring*
  does not close bleps: Django has no server-side expiry hook, so the
  blep stays open until a deliberate logout or stop.
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

**Shift enclosure.** Every Blep must be fully enclosed by a `Shift` of the
same user (`shift.start <= blep.start and blep.end <= shift.end`). Shifts are
the worker's clock-in/clock-out attendance spans (`Shift` model in
`apps.core` — see `docs/designs/data-constraints.md` §1.2a). Consequences for
bleps:

- **Auto-clock-in.** Starting a live blep (`TaskLifecycleService.start_work`)
  calls `ShiftService.ensure_open_shift(target)` — if the worker has no open
  shift, one is opened at `now` so the new blep is enclosed. Workers normally
  clock in from the Home band, but starting work clocks them in implicitly.
- **Clock-out closes open bleps.** `ShiftService.clock_out` closes the
  worker's open bleps (`end_time = now`) *before* stamping the shift's
  `end_time`, so clocking out never leaves a blep unenclosed. The logout
  endpoint clocks the worker out (§5.3).
- **Enclosure guard on create/edit.** A blep create or edit (live or
  historical) is rejected if no shift of that user encloses the resulting
  span (`enclosing_shift_for_blep` in `apps/core/time_integrity.py`). A worker
  whose target time falls outside any shift, or outside their 30h self-edit
  window, files a `BlepChangeRequest` for a manager to approve.

The 30-hour rolling rule applies to direct user edits, not to
service-driven activity:

- A user can create / edit / delete their own Blep if its `start_time`
  is within the last 30 hours.
- Editing or deleting another user's Blep, or any Blep older than 30
  hours, requires the `can_manage_time` permission atom.
- Reassigning a Blep to a different user also requires `can_manage_time`.
- Starting or stopping another worker's live timer (`on_behalf_of` on
  `start_work` / `stop_work`) also requires `can_manage_time`.

These rules live in `BlepService` (`apps/jobs/services.py`), not in
the serializer — `BlepPermissionError` translates to HTTP 403 in the
viewset, `ValidationError` to HTTP 400.

### 5.3 BlepService

`BlepService` is the sole write path:

| Primitive (no validation) | Use |
|---|---|
| `_create(task, user, start_time=None, end_time=None)` | Create a Blep |
| `_close_open(user=None, task=None, now=None)` | Close all open Bleps matching the filters |
| `close_user_open_bleps(user)` | Public wrapper around `_close_open(user=...)`; called by `UserAdminService` on deactivation, by the logout endpoint (`/api/auth/logout/`) so an explicit logout clocks the worker out, and by `ShiftService.clock_out` so clocking out closes the worker's open bleps before the shift closes. Session expiry does not call it (no server-side hook). |

| Public method | Purpose |
|---|---|
| `create_historical(actor, task, start_time, end_time, target_user=None)` | Validated historical create; 30h window + `can_manage_time` rules |
| `update(blep, actor, **fields)` | Update `start_time`, `end_time`, optionally `user`; validates ownership, window, and overlap |
| `delete(blep, actor)` | Same authorization rules |

Validation rules enforced inside `BlepService`:

1. `end_time >= start_time`
2. No interval overlap per user (open bleps are treated as
   `[start, now)` for the comparison; two different users may overlap
   on the same task)
3. 30h rolling window for non-managers (create / update / delete)
4. **Job-status guard:** a Blep may only be created on a Task whose Job
   is in a status where work belongs. Live `start_work` allows `approved`
   and `in_progress` only; backfilled `create_historical` also allows
   `work_complete` (you may log time after work was marked done). Any
   other status — `draft`, `submitted`, `rejected`, `completed`,
   `cancelled` — is rejected with `ValidationError`. The UI is expected
   to prevent this; the guard is defensive.
5. **No future `end_time`:** a non-null `end_time` more than 30s ahead of
   `now` (`BlepService._CLOCK_SKEW_BUFFER`, tolerating mismatched device
   clocks) is rejected on create and update. You cannot have worked ahead
   of now.
6. **Shift enclosure:** the resulting blep span must be fully enclosed by a
   shift of the same user (`enclosing_shift_for_blep`). `start_work`
   auto-opens a shift so live timers always pass; historical creates/edits
   outside any shift are rejected (file a `BlepChangeRequest` instead). See
   §5.2 and `docs/designs/data-constraints.md` §1.2a.

### 5.4 API

`BlepViewSet` is registered at `/api/bleps/`. Filters: `?user=me|<id>`,
`?task=<id>`, `?since=<iso>` (combined with AND). Permissions:
`IsAuthenticated` for all endpoints; the service applies the ownership
and `can_manage_time` rules.

### 5.5 Minimum session, derived activity, change notification

- **Minimum session (`blep_minimum_minutes`, default 1).** Config is now in
  **whole minutes** (Blep/Shift times are minute-granular). While a worker's
  own open Blep is under this duration, the UI's Stop control becomes
  **Cancel** — `POST /api/tasks/{id}/cancel-work/` → `cancel_work` (§4.5). The
  premise: a session that short is an "oops, I didn't mean to start that," so
  it's discarded rather than saved. The threshold rides on the
  `/api/bleps/current/` (field `blep_minimum_minutes`) and task-detail payloads
  so the client can choose the label live (compared in whole minutes,
  `floor((now − start)/60s)`, to stay aligned with the backend).
- **Sub-minimum close = cancel, enforced for ALL close paths.** The rule is
  not just a frontend affordance: it lives in the backend close primitive
  `BlepService._close_open`. When any close path resolves an open Blep, a
  sub-minimum one (`< blep_minimum_minutes` whole minutes) is cancelled with
  full `cancel_work` undo (`_cancel_blep`: delete + first/only-activity revert
  to `pending` + material un-consume); an at-or-over-minimum one is closed
  (end floored to the minute). Because `stop_work`, `ShiftService.clock_out`,
  and logout/deactivation (`close_user_open_bleps`) all route through
  `_close_open`, they share the behavior — a sub-minimum blep is **never**
  persisted closed. Manager on-behalf stop is never a cancel of intent, but
  a genuinely sub-minimum blep it closes is still discarded by this rule.
  The per-blep decision (cancel-if-sub-minimum / else close) lives in the
  shared `_resolve_open_blep(blep, now)` helper; `_close_open` just loops over
  matching open bleps and calls it. `_close_open` wraps that loop in
  `transaction.atomic()` so it is self-atomic regardless of caller:
  `_cancel_blep` uses `select_for_update()`, and the logout / deactivate
  callers invoke it under autocommit (no enclosing transaction), where it would
  otherwise raise `TransactionManagementError` → 500.
  **Takeover RESOLVES the displaced blep, then restarts.** The
  `action='takeover'` branch of `start_work` calls `_resolve_open_blep` on each
  displaced worker's open blep — so a sub-minute one is **cancelled** (full
  undo: deleted, and if it was the task's only activity the task reverts to
  `pending` and materials un-consume) and a real one is **closed**. It then
  recurses into `start_work(task_pk, target)` (the normal tested path): if the
  cancel reverted the task to pending, that path re-promotes / re-consumes /
  reassigns; otherwise it just opens the new blep. No takeover-specific state
  handling — takeover is composed from cancel + start, not a special case.
- **Derived activity facets.** `TaskSerializer` and `BoardService` expose
  `has_active_blep`, `active_worker_count`, and `has_bleps` (computed from
  `blep_set`, prefetched to avoid N+1). The SPA collapses these + status
  into one label vocabulary via `lib/taskActivity.js` — **Working** (an
  open Blep right now) / **Ongoing** (`in_progress`, none open) /
  **Unstarted** (`pending`) / **Blocked** — surfaced identically on the
  board card, the job overview Tasks pillar, task detail, task tree, home,
  and schedule quick card.
  `pending` vs `in_progress` stays distinct in the model (it gates
  material consumption) but reads as plain "Unstarted" vs "Ongoing"; the
  only real-time signal that stands out is "Working."
- **Change notification (frontend).** Every blep mutation funnels through
  `notifyBlepChanged()` (`stores/blepActivity.js`), which refreshes the
  sticky `CurrentBlepBand` (so closing/cancelling a session clears it) and
  bumps a version that blep-dependent pages subscribe to and refetch — the
  page updates in place, no reload.

## 6. ~~EstWorksheet~~ (removed)

> **Removed — the planning layer is gone.** `EstWorksheet`, `PlanTask`,
> `PlanMaterial`, the worksheet API (`/api/est-worksheets/`,
> `/api/plan-tasks/`), `WorksheetService`, and worksheet→job carry-over
> (`materialize_worksheet_onto_job`, `AtomCarryOverService`) were all
> **deleted** in the job-owns-atoms refactor.
>
> What replaced each piece:
>
> - **Planning data** → the Job's own `Task` / `Material` / `Fee` atoms,
>   authored directly on the Job at any status (including `draft`). There
>   is no separate planning container and no `PlanTask`/`PlanMaterial`
>   mirror.
> - **`PlanTask` vs `Task` split** → gone. `Task` (and the `TaskBase`
>   abstract) is the single work-and-billing model; hierarchy
>   (`parent_task`) lives only on the Job side, as before.
> - **Estimate generation from a worksheet** → the estimate is a **lens**
>   that projects the Job's atoms (`est_qty` via
>   `Task.compute_estimate_amount`). Full wizard mechanics — atom claims,
>   line-item recompute on sync, claim state — live in
>   `docs/designs/estimates-and-prices.md` §§6–8.
> - **Carry-over on accept** → `EstimateAcceptanceService.on_accept`
>   crystallizes hand-lines into `Fee` atoms and earmarks the job; the
>   work was already on the Job, so nothing is copied
>   (`estimates-and-prices.md` §9).

## 7. Templates

Templates power the populate-from-template paths, which create Tasks and
Materials directly on the Job.

### 7.1 Models

| Model | Path | Role |
|---|---|---|
| `WorkTemplate` | `apps/estimates/models.py` | Job-shaped template; carries optional `base_price` |
| `ServiceItem` | `apps/estimates/models.py` | A single reusable task template; carries `rate_scheme`, `default_active_modifiers` (a list of pre-checked modifier keys). |
| `TemplateTaskAssociation` | `apps/estimates/models.py` | M2M-with-extras between WorkTemplate and ServiceItem; carries `est_qty` and `sort_order` |
| `TemplateMaterialAssociation` | `apps/inventory` | Links materials to a WorkTemplate; covered in the Materials doc |

`ServiceItem.is_active` is the soft-delete flag for task templates.
`WorkTemplate.generate_tasks_for_job` and the ServiceItem picker UI all
filter on `service_item__is_active=True`. Soft-delete (not hard-delete)
is the intended path so historical references to a retired ServiceItem
are preserved.

`WorkTemplate` has no `is_active` field. Templates are hard-deleted —
nothing else in the system holds a back-reference to a WorkTemplate, so
a delete cascades cleanly through its TemplateTaskAssociation /
TemplateMaterialAssociation join rows without touching any Job,
Worksheet, Task, or Material.

### 7.2 generate_task

`ServiceItem.generate_task(container, est_qty, ...)`
(`apps/estimates/models.py`) creates a `Task` on a `Job`. The container
must be a `Job` — it raises `ValueError` for anything else (the
worksheet/PlanTask branch was removed).

It refuses to fire if the template's `rate_scheme` has been superseded
(raises `SchemeSupersededError`, which the API translates to HTTP 409).
See estimates-and-prices for the supersession story.

Optional overrides: `name`, `description`, `active_modifiers`,
`est_worker_time`, `assignee`, `sort_order`. Falls back to the
template's defaults when not provided.

### 7.3 Job-level generation

`WorkTemplate` exposes:

- `generate_tasks_for_job(job, quantity=1)` — iterates associations and
  calls `generate_task` for each, optionally multi-instance (returns
  `[(association, instance_index, task), ...]`).
- `generate_materials_for_job(...)` — uses the task pairing returned
  above to attach materials to the right tasks.

The `task_pairing` argument is how the materials side knows which Task
each generated Material belongs to — critical for multi-instance template
fanout.

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

- `needs-scoping` — no estimate yet
- `estimating` — a draft estimate exists
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

- `POST /api/tasks/{id}/assign/` — set assignee + worker_queue, optionally
  `est_worker_time`. Assigning a Task that has no estimate (and none
  supplied) returns `{needs_worker_time: true}` instead of assigning, so
  the UI can prompt: the board drag-and-drop pops an interrupting duration
  modal (`WorkerTimePromptModal`), and the Assign modal shows a required
  duration field. Unassigning never requires a duration.
- `POST /api/tasks/reorder/` — bulk update worker_queue from a list

### 8.5 Card composition

| Card | Component | Shows |
|---|---|---|
| Job chip (Pipeline / Approved / Unpaid) | `JobCard.svelte`, `UnpaidCard.svelte` | Job number, name, customer, deadline, sub-status pill, accent stripe (8-color palette, recycled by index) |
| Closed card | `ClosedCard.svelte` | Same plus profitability (billed / spent / profit, computed in `BoardService._compute_profitability`) |
| Task card | `TaskCard.svelte` | Task name, activity label + dot (Working / Ongoing / Unstarted / Blocked — see §5.5), assignee, blocked_reason if blocked |

## 9. UI: Job Detail page

Route: `#/jobs/:id` → `JobDetailPage.svelte`.

### 9.1 Layout

Top-down:

1. **JobHeader** (`components/jobs/JobHeader.svelte`) — title `JOB
   #N: Name`, subtitle (contact / business), a "Project manager:" line
   (when set; links to `#/jobs?pm=<id>`), status pill (interactive
   `<select>` for users with `can_manage_jobs`), key dates,
   customer_po_number.
2. **Description + History** in a flex row. `HistoryPanel`
   (`components/HistoryPanel.svelte`) shows status changes, notes, and
   inline email previews.
3. **Horizontal accordion pillars** for Estimate, Tasks & Materials,
   Invoice, Purchase Orders. One pillar is expanded; the others render
   as vertical labels with counts. Clicking a pillar swaps the active
   one. The Estimate pillar carries a **Plan / Client View** toggle (the
   Plan side is the Work surface — see §9.5; the Client View renders the
   estimate/agreement projection). There is no Worksheet pillar (the
   planning layer was removed).

### 9.2 Components

| Component | Role |
|---|---|
| `JobDetail.svelte` | Composes the page; owns accordion + Plan/Client-View state, fetches related data |
| `JobHeader.svelte` | Header + status dropdown |
| `HistoryPanel.svelte` | Notes + history timeline + email entries |
| `Accordion.svelte` | Reusable expand/collapse used elsewhere |
| `WorkItemForm.svelte` | Add/edit a Task (Service) on the job |
| `MaterialModal.svelte` | Add/edit a Material on the job |
| `FeeModal.svelte` | Add/edit a Fee on the job |

The Estimate pillar's **Plan** view is the Work surface (job atoms with a
grand-total footer); its **Client View** shows the estimate/agreement
line items with grand total. Tasks & Materials shows the active Task tree
(materials nested under tasks); Invoice / PO pillars are summary tables.

### 9.3 Header financial rollups

`JobHeader` shows four figures: **Estimate | Spent | Invoiced | Profit**. They
are the single source of truth in `apps/jobs/financials.py`
(`compute_job_financials(job)` → `{estimated, spent, invoiced, profit}`, all
Decimal, quantized to cents), surfaced as detail-only serializer fields
`estimated_amount` / `spent_amount` / `invoiced_amount` / `profit_amount` on
`JobSerializer`. Like `latest_change_request`, they are computed once per detail
render (memoized) and returned as `null` in list context, so the board list
payload stays cheap; the header falls back to `$—` when a value is `null`.

- **Estimate** — `compose_agreement(job).grand_total` when the job was ever
  approved (keyed off the immutable `Job.start_date`; see data-constraints §1.8);
  otherwise the highest-version estimate's `Σ qty×price` (0 if none).
- **Spent** — all non-rejected expenses attributed to the job (`Expense.job` —
  the direct cost anchor, covering both material-linked and material-less
  expenses; overhead `job=null` is excluded) + consumed materials with **no**
  linked expense at cost (`Σ quantity×unit_cost`; materials acquired via an
  expense are represented by that expense, avoiding double-count) + labor (`Σ blep hours on the job ×
  Configuration['average_labor_cost']`; every logged hour costs the same,
  regardless of the task's RateScheme — labor cost is about hours worked, not how
  the work is billed; a running blep counts its time so far).
- **Invoiced** — `Σ qty×price` of the job's invoice line items, excluding
  `draft` / `cancelled` / `superseded` invoices.
- **Profit** — `invoiced − spent`. Intentionally negative for work done but not
  yet billed (if it is never billed, the shop is genuinely out that cost).

The job-board Unpaid and Closed cards consume the same module via
`BoardService._compute_profitability` (a thin adapter returning `billed` =
invoiced, `spent`, `profit`), so the board and header can never drift. The cards
label the figure "Invoiced".

**Deferred — Billable.** A fifth figure (value of work earned, at selling price,
optionally plus estimate for not-yet-actualed lines) is intentionally not built;
its definition is unsettled. When chosen it slots into `compute_job_financials`
as one more function and one header column (between Spent and Invoiced) with no
rework to the other four.

### 9.4 Expenses on the Job UI

Expenses attached to a job (`Expense.job`) surface in two places, fed by
`/api/expenses/?job=<id>`:

- **Job overview** (`JobDetail`): the **Materials** pillar becomes "Materials &
  Expenses". Material-less expenses render as their own rows (description,
  category, amount); a material-linked expense annotates its material's row
  ("paid $X") rather than getting a duplicate row — keeping the visual count
  honest. The pillar count includes material-less expenses.
- **Full task list** (`JobTaskListPage`): material-less expenses render in an
  "Expenses (no material)" section below the task tree, mirroring how taskless
  materials surface.

An expense can be **created in place** from the full task list toolbar: an "Add
Expense" button (next to "Add Material", shown when the job isn't locked) opens
`ExpenseModal` (a thin overlay around `ExpenseForm`) pre-anchored to the job via
the form's `initialJob` prop; on save the list reloads so the new expense
surfaces. Expense create is open to any authenticated user.

### 9.5 The Work surface

The Estimate pillar's **Plan** view is the **Work surface** — the single
place to author the Job's own work atoms, visible regardless of estimate
state (so pre-approval / released effort shows here too). It renders a
read-only atom table (Tasks, Materials, Fees with a grand-total footer)
plus, for managers, an **Add line** row:

| Add-line button | Modal | Creates | Endpoint |
|---|---|---|---|
| **+ Service** | `WorkItemForm` | `Task` | `POST /api/jobs/{id}/tasks/` |
| **+ Material** | `MaterialModal` | `Material` | `POST /api/jobs/{id}/materials/` |
| **+ Fee** | `FeeModal` | `Fee` | `POST /api/jobs/{id}/fees/` |

The Estimate pillar's toolbar also carries **Start Estimate** (creates a
draft estimate directly on the job — `POST /api/estimates/` with `{job}`)
and, while the job is `on_hold`, **+ New change order**. The Client View
toggle then renders the estimate (or accepted-agreement) projection over
these same atoms. This is the surface that replaced the deleted Worksheet
detail page.

## 10. UI: Task Detail page

Route: `#/jobs/:jobId/tasks/:taskId` → `TaskDetailPage.svelte`.

Fetches `GET /api/tasks/{id}/` and `GET /api/bleps/?task={id}` on
mount.

### 10.1 Components

| Component | Role |
|---|---|
| `TaskActions.svelte` | Renders the status-appropriate button row (Start Work, Stop Work, Complete, Block, Unblock, Cancel) gated by status + permissions. While the user's own session is under `blep_minimum_minutes` (whole minutes), **Stop Work** reads **Cancel** (delete + undo; §4.5/§5.5) |
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

While the active session is under `blep_minimum_minutes` (compared in whole
minutes), the "Stop Work" button instead reads "Cancel" and deletes the
just-started Blep (undoing the Start) rather than closing it — see §5.5. The
backend enforces the same rule on every close path, so even a Stop on a
sub-minimum session is converted to a cancel server-side. This is distinct
from the manager-only task **Cancel** above.

### 10.3 Recent Time list (home page)

`components/home/RecentTimeList.svelte` (home **Time** tab) fetches
`GET /api/bleps/?user=me&since=<7d ago>` — the signed-in user's own recent
sessions. Each row offers **Edit** when the blep is editable (within the 30h
rolling window, or any blep for a `can_manage_time` manager); otherwise a
**Request Edit** button — currently a stub that alerts "Not yet implemented"
(see Unfinished Work).

It renders the shared **`components/time/BlepLogTable.svelte`**, which owns the
session-row presentation: Task · Job · Start · End · Duration. Times show as a
weekday abbreviation + 12-hour clock rounded to the minute (`Mon 3:45 PM`);
Duration is minute-granularity (`1h 25m`); open sessions show a green **active**
tag and a duration that ticks up every 30s (client clock only — no refetch); the
job name truncates at 20 chars. `BlepLogTable` props: `bleps`, `showWorker` (adds
a Worker column), and an optional per-row `actions` snippet (RecentTimeList
passes the Edit / Request-Edit buttons).

### 10.4 Activity page (all-users work log)

Route `/activity` → `routes/ActivityPage.svelte`, linked in the sidebar for all
authenticated users (consistent with the Schedule page). A flat, newest-first log
of **every** worker's sessions over the last 2 days: it fetches
`GET /api/bleps/?since=<2d ago>&page_size=100` with no `user` filter (the list
endpoint returns all users for any authenticated user — §5.4). It renders
`BlepLogTable` with `showWorker=true` and no `actions` (read-only). Open sessions
sort to the top and carry the **active** tag, so "who's working now" falls out of
the chronological order.

It refreshes on this client's own blep changes (`blepActivityVersion`) and the
30s duration tick; it does **not** poll for other workers' clock-ins/outs — a
general cross-client repolling mechanism is deferred (see Unfinished Work).

## 11. ~~UI: Worksheet Detail page~~ (removed)

> **Removed.** The Worksheet detail page (`WorksheetDetailPage.svelte`),
> the PlanTask detail page (`PlanTaskDetailPage.svelte`), and the
> worksheet/plan-task API endpoints (`/api/est-worksheets/…`,
> `/api/plan-tasks/…`) are gone with the planning layer.
>
> Where the work-authoring UI lives now:
>
> - **Authoring the Job's work atoms** → the **Work surface** on the Job
>   overview's Estimate pillar (Plan view) — see §9.5. `WorkItemForm`
>   creates a `Task` (`POST /api/jobs/{id}/tasks/`), `MaterialModal` a
>   `Material` (`/materials/`), `FeeModal` a `Fee` (`/fees/`).
> - **`InventoryItemPicker.svelte`** (type-ahead `InventoryItem` picker,
>   built on `SearchPicker`) survives — reused by `MaterialModal` and the
>   PO line-item form.
> - **Task detail / CRUD** → `/api/tasks/…` and the job-nested
>   `/api/jobs/{id}/tasks/{task_pk}/` (see §4, §10).

## 12. Deliverables and Shipments

The fulfillment side of a Job. Four models live in `apps/deliverables/`:
`Deliverable`, `Shipment`, `ShipmentItem`, and `DeliverableSnapshot`
(the write-once per-document scope record introduced with change orders;
see §12.2 and §12.9).

### 12.1 Concepts

- **Deliverable**: a single item the customer is buying on a Job —
  description, qty_ordered, units. No price. Distinct from estimate /
  invoice line items (which include billable inputs like setup, jigs,
  consumed materials). One Job has 0+ Deliverables. Listed on the Job
  detail page (always visible, sub-header column) and on every customer-
  facing packing list.
- **Shipment**: a single fulfillment event for a Job. Holds 1+
  `ShipmentItem` rows that each reference one Deliverable + a qty.
  Multiple Shipments per Job support phased delivery / backorders.
- **Packing list**: not a model — it's the printable rendering of one
  Shipment, with each Deliverable's qty_ordered, this shipment's qty,
  qty previously picked up in other shipments, and qty remaining after
  this shipment.

**Permissions — deliberate asymmetry.** Editing the **Deliverables** list
requires `can_manage_jobs` **or** being the job's `project_manager`
(`CanManageJobOrPM`; the UI gates the Edit affordance on the per-object
`can_manage` flag — see §12.8) because it defines the agreed scope, but
**Shipments**
are `IsAuthenticated` for all operations (`ShipmentViewSet` has no per-action
atom). This is intentional, not an oversight: fulfillment is shop-floor work —
any authenticated user must be able to create a shipment, add items, and mark
it picked up — so shipment management is purposely *not* parallel to deliverable
management. (The frontend's Shipments page is correspondingly ungated; flagged
and confirmed-intentional in `docs/plans/2026-06-06-gating-parity-audit.md`.)

### 12.2 Editability of the Deliverables list

Deliverables editability is computed from the Job's estimate / change-
order state, not stored. The live `Deliverable` list is the single
editing surface throughout — pre-send, mid-CO, and post-acceptance:

| Situation | D-list state | UI affordance |
|---|---|---|
| No estimate, or latest active estimate is `draft` | Editable | Edit link |
| Latest active estimate is `open` (sent) | Read-only | "(estimate sent)" pill |
| Estimate `accepted`, no live ChangeOrder | Read-only | "(estimate accepted)" pill |
| A ChangeOrder on the Job is `draft` | Editable (unanchored rows only) | Edit link, while CO is draft |
| A ChangeOrder on the Job is `open` (sent) | Read-only | "(change order sent)" pill |
| Any time | **Anchored** rows (have ≥ 1 `ShipmentItem`) are never editable | Locked indicator |

"Latest active" means: most recent estimate not in `superseded` /
`rejected` / `expired`. There is at most one such row.

**Anchoring** (`DeliverableService.update`/`delete` reject when
`shipment_items.exists()` is true): once any of a Deliverable's quantity
has been picked up, the row is frozen at its `qty_ordered` for the life
of the job. A CO can't edit or remove an anchored row — if a change to
an already-delivered item is genuinely needed, the escape hatch is to
finalize the job (`cancelled` + invoice for work done — see
`invoicing-and-expenses.md`) and start a new one.

Editability keys on **CO state**, not on `on_hold` alone — a non-CO
pause (deposit, backorder) leaves the agreed scope frozen.

Rationale: while the customer is reviewing a `sent` estimate or CO, the
Deliverables they were shown must not drift from what the database
holds. While a CO is `draft`, the live list holds the *proposal* (the
prior agreed scope is preserved on a `DeliverableSnapshot` — see §12.9
and the per-document snapshot model in `data-constraints.md`).

### 12.3 Estimate-send guard

`EstimateService.mark_open` rejects with `ValidationError` if the Job has
zero Deliverables. The customer cannot receive an estimate that doesn't
say what they're buying.

This is the single cross-app modification this feature made; see also
`data-constraints.md` §2.12.

### 12.4 Shipment lifecycle

```
                ┌─ "+ Add shipment" (UI only)
                ▼
         local draft (never on server)
                │
                ▼  Save changes (if ≥1 qty > 0)
        ┌────────────────┐
        │   prepared     │  status_picked_up_date is null
        └────────┬───────┘
                │  mark_picked_up
                ▼
        ┌────────────────┐
        │   picked_up    │  picked_up_date set; terminal
        └────────────────┘
```

- A Shipment can only be created server-side once the Job has an accepted
  estimate. Enforced in `ShipmentService.create`; raises before any
  database write.
- **Shipments are frozen while the Job is `on_hold`.**
  `ShipmentService._assert_job_not_on_hold` rejects creation — otherwise
  someone could ship against a proposed-but-unagreed deliverable scope
  during CO negotiation, and the resulting row would anchor mid-flight.
- The SPA's Job Shipments page creates Shipments **locally first** (draft
  column with prefilled qtys). The server-side `POST /api/jobs/{id}/shipments/`
  fires only on Save, and only if the draft has at least one non-zero qty.
  Drafts with no qty are silently discarded — this is how the UI keeps
  the "every shipment has at least one line" invariant without a database
  constraint.
- An existing prepared Shipment whose final item count would be zero
  after Save also gets deleted — same invariant maintained.
- A `picked_up` Shipment is read-only: no edits, no item changes, no
  deletion. There is no reverse transition.

### 12.5 ShipmentItem invariants

- `qty > 0` (validated by service; not a DB constraint).
- For each Deliverable, the sum of qty across all ShipmentItem rows
  pointing at it must not exceed `Deliverable.qty_ordered`. Validated in
  `ShipmentService.add_item` and `update_item` via
  `_validate_qty_bounds(deliverable, …)`. The bound counts items across
  every Shipment regardless of status.
- `unique_together = [('shipment', 'deliverable')]` — one row per
  (Shipment, Deliverable) pair. Shipping the same Deliverable a second
  time means creating a new Shipment.
- `deliverable` FK is PROTECT, defense-in-depth against a future change
  order that tries to remove a still-referenced Deliverable. The
  Deliverable editability rule already prevents this in normal flows.

### 12.6 Services

`apps/deliverables/services.py`:

| Class | Public methods |
|---|---|
| `DeliverableService` | `create`, `update`, `delete` (with sibling renumber), `reorder`, `is_editable`, `editability_reason`, `compute_fulfillment`, `all_deliverables_shipped`, `snapshot_document`, `restore_live_to_snapshot` |
| `ShipmentService` | `create`, `update` (notes only), `delete` (only if prepared + empty), `mark_picked_up` (calls `JobService.maybe_complete_if_resolved` so the last shipment can complete a fully-paid job), `add_item`, `update_item`, `remove_item`, `packing_list_payload` |

All write paths run inside `transaction.atomic()`. Quantity-bound checks
use `select_for_update()` on the parent Deliverable to keep concurrent
edits from each passing the bound check independently.

`compute_fulfillment(deliverable) -> dict` returns the running totals
(`qty_ordered`, `qty_picked_up`, `qty_prepped`, `qty_remaining`) used by
the API serializer.

`packing_list_payload(shipment) -> dict` returns the JSON shape the
printable view consumes — see §12.8.

### 12.7 API surface

| Method + path | Permission | Purpose |
|---|---|---|
| `GET /api/jobs/{id}/deliverables/` | `IsAuthenticated` | List |
| `POST /api/jobs/{id}/deliverables/` | `CanManageJobs` | Create |
| `PATCH /api/jobs/{id}/deliverables/{did}/` | `CanManageJobs` | Update |
| `DELETE /api/jobs/{id}/deliverables/{did}/` | `CanManageJobs` | 200 + JSON |
| `POST /api/jobs/{id}/deliverables/reorder/` | `CanManageJobs` | Bulk reorder |
| `GET /api/jobs/{id}/deliverables/editability/` | `IsAuthenticated` | `{editable, reason}` |
| `GET /api/shipments/?job={id}` | `IsAuthenticated` | List, filterable |
| `POST /api/jobs/{id}/shipments/` | `IsAuthenticated` | Create |
| `PATCH /api/shipments/{sid}/` | `IsAuthenticated` | Notes only (status uses pick-up) |
| `DELETE /api/shipments/{sid}/` | `IsAuthenticated` | 200 + JSON. Allowed when `prepared` + no items. |
| `POST /api/shipments/{sid}/pick-up/` | `IsAuthenticated` | `prepared → picked_up` |
| `GET/POST /api/shipments/{sid}/items/` | `IsAuthenticated` | List / add |
| `PATCH/DELETE /api/shipments/{sid}/items/{iid}/` | `IsAuthenticated` | Update / remove |
| `GET /api/shipments/{sid}/packing-list/` | `IsAuthenticated` | Rendering payload |

Deliverables are read-open / write-managed (consistent with planning
artifacts). Shipments are read-write open to any authenticated user
(consistent with `Blep` and other operational work — any employee can
pick, pack, and mark goods picked up without elevated permissions).

### 12.8 UI

**Job detail page**: a third column appears in the existing Description
| ... | History flex row. Renders as a `<DeliverablesSection>` panel
matching the chrome of its neighbors. The list shows simple
`qty units description` lines (no headers, no computed columns). An
"Edit" link in the panel head opens `<DeliverablesEditModal>` when the
list is editable.

**Two mount points, one component.** The same `<DeliverablesSection>`
is mounted on the **Job detail** page and the **Estimate detail** page
(bottom of each), so the scope can be edited wherever the user happens to
be pre-acceptance. It takes `jobId` plus a `canManage` prop, which each
parent feeds from its own already-fetched per-object `can_manage` flag
(`job.can_manage`, `estimate.can_manage` — both from
`JobScopedCanManageMixin` / `JobService.user_can_manage`). The "Edit"
affordance shows only when `canManage && editability.editable`, so the
button appears exactly when the server would accept the write (atom
holder **or** the job's PM, and the list not yet locked by a sent/
accepted estimate or open change order — see §12.2). The component is
only ever mounted on Job-related pages, so `jobId` is always resolvable.

A read-only **Shipments pillar** sits between the Invoices and Purchase
Orders pillars in the accordion. It renders the same matrix table as
the editor page (one row per Deliverable, one column per Shipment with
status + date in the header) and a "Manage shipments →" link to the
editor.

**Job Shipments page** at `#/jobs/:jobId/shipments`: the editable
matrix. Adds + Discard (local for drafts, server for persisted),
in-place cell editing with explicit Save (per the CLAUDE.md
no-blur-only rule), per-shipment Mark picked up / Print / Discard
actions, and a column total footer that includes pending edits.

**Printable packing list** at `#/shipments/:sid/print`: From / To
header (From is currently placeholder text pending a company-info
Configuration source; To draws from the job's contact / business),
shipment + job header, line item table with previous / this-shipment /
remaining columns, a signature row (Pickup by + Pickup date). Print
via the browser; no server-side PDF generator yet.

### 12.9 Change orders and deliverable versioning

A **ChangeOrder** is the sanctioned amendment instrument after the
Estimate is accepted: an estimate-shaped, customer-approved (or
-rejected) document that alters the agreement. The model and lifecycle
live in `apps/estimates/` (alongside `Estimate`); see
`docs/designs/estimates-and-prices.md` for the full reference. The
deliverable-side mechanics are owned by this doc:

- **One editing surface.** The CO's proposed deliverables *are* the
  job's live `Deliverable` list, edited in place via the same
  `DeliverablesEditModal` while the CO is `draft`. There is no separate
  CO-owned deliverables table — see §12.2.
- **`DeliverableSnapshot`** (`apps/deliverables/models.py`) is the
  immutable, write-once per-document scope record. Each row attaches
  to *either* an Estimate or a ChangeOrder (enforced by `clean()`) and
  copies the live Deliverable's `description` / `qty_ordered` / `units`
  / `sort_order` plus a `source_deliverable` FK (SET_NULL) for
  traceability. A document has at most one snapshot set.
- **Three write triggers** (`DeliverableService.snapshot_document`):
  1. **On estimate supersession** (`EstimateService.revise_estimate`) —
     snapshot the live list onto the estimate being superseded, freezing
     the scope the customer saw while it was the live proposal. The list
     was read-only while the estimate was `open`
     (`DeliverableService.is_editable`), so the live list at supersession
     time is exactly what was shown. This is the pre-acceptance / estimate-
     revision counterpart to the CO triggers below.
  2. **On CO creation** (`ChangeOrderService.create`) — snapshot the
     prior agreement onto the document being amended (the accepted
     Estimate, or the latest accepted CO on the same estimate). That
     snapshot is both the amended document's permanent agreed record
     **and** the rollback target if this CO dies.
  3. **On CO `→ rejected` / `→ expired`** — snapshot the live list
     (this CO's final proposal) onto the rejected CO, preserving the
     proposal.
- **Portal read rule.** The customer portal
  (`apps/api/portal/views.py::build_estimate_payload`) renders an
  estimate's `deliverable_snapshots` when present, falling back to the
  job's live deliverables otherwise. A current `draft`/`open` estimate
  has no snapshot → live list; a superseded estimate (trigger 1) or an
  accepted estimate later amended by a CO (trigger 2) renders its frozen
  snapshot, so an out-of-date estimate never shows scope that has since
  drifted.
- **Anchoring (Option A):** an unshipped row is freely editable in the
  live list; once any `ShipmentItem` references it, the row is frozen
  at `qty_ordered` — never editable or removable. Fulfillment never
  fragments because shipments stay attached to the live row across
  versions. See §12.2.
- **Reject → resume.** `DeliverableService.restore_live_to_snapshot`
  reconciles the live list's *unanchored* rows back to a prior
  snapshot — re-adds removed rows, restores edited qty, deletes added
  rows; anchored rows are untouched. Exposed as the "Restore last
  agreed deliverables" action on a rejected CO.
- **On CO acceptance.** No reconcile step: the live list already *is*
  the new agreed set (it was edited in place during the CO draft).
  Only Tasks/Materials are hand-applied by the user — the CO never
  mutates them automatically.

---

## 13. Signals

`apps/jobs/signals.py` is **empty (0 lines)**. All Job-side state
changes flow through services. This is the same inconsistency the
architecture doc flags — see `architecture-and-conventions.md` §2.3.

`apps/estimates/signals.py` defines two custom signals and their
receivers (the former `estimate_status_changed_for_worksheet` was removed
with the worksheet layer):

| Signal | Sender | Receiver | Effect |
|---|---|---|---|
| `estimate_status_changed_for_job` | `Estimate.save()` | `update_job_status` | Walks the Job through the right status (draft → submitted → approved on send/accept; **open → rejected** drives the Job to `rejected`); creates a `HistoryEntry` action row attributed to the `system` user; refuses to downgrade or to touch completed/cancelled jobs |
| `estimate_accepted` | `Estimate.save()` (when transitioning to accepted) | acceptance receiver | Calls `EstimateAcceptanceService.on_accept(estimate)` — crystallizes each hand-line into a `Fee` on the Job and earmarks the job's inventoried materials (`estimates-and-prices.md` §9) |

`Estimate.save()` (`apps/estimates/models.py`) is what fires these.
The receivers do not currently mark estimates superseded automatically —
that happens through explicit `EstimateService.revise_estimate` calls,
which set the parent's status to superseded directly. `accepted` is
terminal; an accepted estimate cannot be superseded
(`Estimate.clean()` rejects it; `tests/test_estimate_job_status_sync.py`
covers this).

**ChangeOrder uses no signals.** `ChangeOrderService.update_status`
handles acceptance/rejection side-effects directly: on `→ accepted` it
advances the Job `on_hold → approved` via `JobService.update_job` and
writes a `HistoryEntry`; on `→ rejected`/`→ expired` it calls
`DeliverableService.snapshot_document(change_order=co)` (Trigger 2). No
Task or Material is mutated by either path — the human applies the
agreed changes by hand while the job sits in `approved`.

## 14. Unfinished work

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
- **Workflow routing soft warnings.** `populate-from-template` doesn't
  warn when the Job already has atoms. Hard prerequisite gates exist;
  soft steering does not.
- **"Request Edit" button stub.** `RecentTimeList.svelte` shows an
  alert; there's no backend wiring or UI for the request-and-approve
  flow.
- **Push-notification infrastructure.** The blep-takeover flow has no
  way to notify the worker whose Blep was just closed. No notification
  system exists yet anywhere in the codebase.
- **Cross-client live refresh (general repolling).** Pages that show other
  users' state — the Activity log (§10.4), the Job Board, the Schedule, the
  home lists — only refresh on this client's own blep changes plus local
  interval ticks; another worker's clock-in/out doesn't appear until reload.
  A shared repolling mechanism (deciding which pages need it and how to do it
  once) is deferred.
- **Multi-instance template generation needs UI.**
  `WorkTemplate.generate_tasks_for_*` and `generate_materials_for_*`
  accept `quantity=N` but every current caller passes 1.
- **Default-worker rate-scheme + worker quick-add task flow.** Pending
  the broader billing-identity work tracked in
  `docs/designs/estimates-and-prices.md`.
