# Archived jobs — design

**Date:** 2026-10-20 · **Author:** RM with Claude · **Status:** approved by RM 2026-10-20 (labor rule and profit caveat revised the same day); implementation plan: `docs/plans/2026-10-20-archived-jobs.md`
**Branch:** `feature/archival-jobs`

## 1. Intent

Shops switching to konbini have a work history in their previous
system (or on paper). That history is worth having inside konbini even
when it can't be reconstructed into fully functional jobs: a user should
be able to open an old job, read what happened, see its documents and
dollars, and duplicate it into a real Job to start the next one.

This design adds an **archived** job: a job that exists purely as a
historical document set. It is released from the structural invariants
live jobs carry (deliverables before completion, invoices only on
approved jobs, every task terminal before work_complete, timeslips
behind actuals, and so on), it is **read-only in every domain**, and it
lives in the **existing tables** — no parallel schema.

This document covers how the archive state affects the current code and
defines the one service entry point that creates an archived job from a
plain payload. **The spreadsheet format and the upload UI are a
follow-on project** that will call that entry point; nothing here
depends on what that spreadsheet looks like.

## 2. Goals, non-goals, anti-goals

**Goals**

- An archived job can be opened, read, searched for, found from its
  customer's page, counted in the customer's dollar totals, and
  duplicated.
- Every part of an archived job beyond its number and customer is
  optional. A job with nothing but a header and a note is a valid
  archive.
- Archived jobs never appear anywhere that drives day-to-day work: the
  board, the schedule, the home lists, pickers that attach new work.
- The archive state is expressed with the existing models and tables.

**Non-goals**

- The import spreadsheet, its parser, and its upload screen (follow-on).
- Importing timeslips, a job-level hours figure, or labor dollars (RM
  2026-10-20). Labor arrives **per task**, as entered-quantity tasks in
  the hour unit (§3.6, §5.1); a source with only a job total puts it on
  one "Labor" task row in its spreadsheet — that is the preparer's data
  decision, never something the importer synthesizes.
- Reproducing the old system's numbering scheme or document formats.
- Editing an archived job after import. The fix for a bad import is
  delete and re-import.

**Anti-goals** (would make this a failure even if it technically works)

- Weakening a live-job invariant to accommodate archives. Archived jobs
  sit *outside* the invariants by status; no live rule gains an "unless
  archived" clause.
- An archived job that can be mutated through some side door (a PO
  line creating a material on it, a note, a timeslip backfill).
- Archived data silently polluting live views or live totals.

## 3. Decisions

### 3.1 A status, not a flag

`Job.STATUS_ARCHIVED = 'archived'` joins `JOB_STATUS_CHOICES` with
label **Archived**. It is terminal with **no inbound transitions from any
live status** and **no outbound transitions**: only the import service
ever sets it, at creation. `Job.clean`'s `VALID_TRANSITIONS` gains
`STATUS_ARCHIVED: []` and no live status lists it as a target. The jobs
API status actions (`complete`, `cancel`, …) therefore cannot reach it,
and a PATCH to `status='archived'` is refused by the model.

Why a status rather than an `is_archived` flag: nearly every structural
invariant in the codebase is keyed on status (completed ⇒ all invoices
paid and all deliverables shipped; work_complete ⇒ every task terminal;
invoices only on approved-or-later; the validator's two dozen checks).
A job at `archived` matches none of those rules, so nothing needs an
exemption. A flagged job would carry a real status like `completed` and
every rule would need an "unless archived" clause — exactly the kind of
invariant erosion the Engineering Principles forbid.

The cost of the original outcome (was it completed or cancelled in the
old system?) is accepted: it is recorded as an imported history row /
note, not as a field (§5.7).

### 3.2 Named status groupings

The status-set review (2026-10-20) found three recurring groupings with
identical membership at every site, plus a handful of deliberately
bespoke sets. The recurring ones get names; the bespoke ones stay
bespoke.

On `Job` (class attributes, mirroring `Invoice.UNPAID_STATUSES`):

| Attribute | Membership | Replaces |
|---|---|---|
| `PRE_APPROVAL_STATUSES` | draft, submitted | 8 backend sites (inventory ×3, estimates, schedule, jobs ×2, validator) |
| `CLOSED_STATUSES` | completed, rejected, cancelled, **archived** | 6 backend sites: `?open=true` list filter, `compute_customer_financials` open-jobs count, email-retention finality, task-delete guard, board Closed lane ×2 |
| `WORK_FROZEN_STATUSES` | `CLOSED_STATUSES` + work_complete | 2 validator sites |

Frontend twin: `frontend/src/lib/jobStatus.js` exporting the same three
sets (as `Set`s) plus `isClosedJob(status)` etc., replacing the private
constant lists in `customerActivity.js` (`CLOSED_JOB`),
`jobOverview.js` (`PRE_APPROVAL_JOB_STATUSES`, `WORK_DONE_JOB_STATUSES`,
`WORK_FROZEN_JOB_STATUSES`, `TERMINAL_JOB_STATUSES`),
`JobHeader.svelte` (`isTerminal`) and `TasksPanel.svelte` (`jobLocked`).

`archived` joins the **closed** group. That is what makes it disappear
from pickers, sort under "show N closed" on the customer page, freeze
the overview blocks, hide Edit on the header, and count as final for
email retention — in one Python line and one JS line.

**Bespoke sets that must NOT be grouped** (each encodes a domain rule;
all are allow-lists, so `archived` is excluded automatically and
correctly): schedule's work-active set, the board's pipeline /
in-progress / unpaid lane queries, timeslip-logging allowed statuses
(includes cancelled), `BILLABLE_JOB_STATUSES` (includes cancelled, not
draft), hold-allowed statuses, auto-complete/auto-advance gates,
`_EARMARK_RELEASING_STATUSES`, the accent-colour active set.

Consequences for archived jobs with no further code: no timeslips, no
invoices created through the service, no holds, no schedule bars, no
board lanes, no new estimates, no earmarks, no auto-advance.

One site needs an explicit addition rather than a grouping: the board's
**Closed lane** queries `CLOSED_STATUSES` within
`board_closed_retention_days` by `completed_date`. An archived job whose
imported `completed_date` falls inside the window therefore appears in
the Closed lane. RM accepted this (2026-10-20): harmless, possibly useful
for a freshly migrated shop. The `ClosedCard` needs an `archived`
label/colour branch (§6.3).

### 3.3 Read-only: the frozen-job guard grows a second reason

`_assert_job_not_frozen(job, action)` in `apps/jobs/services.py` is the
single chokepoint every user-driven mutator in every domain already
calls (jobs, tasks, timeslips, materials, estimates, change orders,
deliverables, shipments, invoices, notes, the wizard funnel — see
`jobs-and-tasks.md` §3.7 for the full call-site list). A new sibling
helper carries the archived check:

```python
def _assert_job_not_archived(job, action):
    if job.status == Job.STATUS_ARCHIVED:
        raise ValidationError(
            f"Cannot {action}: this job is archived. Archived jobs are a "
            f"historical record and cannot be changed."
        )
```

and `_assert_job_not_frozen` calls it **first**, before the
inactive-contact check. Everything that is frozen for an inactive
contact is frozen for an archived job, with its own message.
`JobService.assert_mutable` (the public wrapper) inherits it. The
helper also exists on its own for the one live path that is *not* in
the frozen set but would change an archived job's numbers: **expense
attribution** (§3.4a). The
same-business contact-swap carve-out in `update_job` does **not** apply
to archived jobs (the archived check fires first, before the swap
logic). System transitions (`system_transition=True`) never call the
guard; no system transition ever targets an archived job, so this is
moot, but the expiry commands must not touch archived jobs' documents
either — they only select `open` estimates/COs, which archives never
carry (§5.4).

**Explicitly refused on an archived job** (all via the guard, no new
code): edit header, hold/release, notes, add/edit/delete/reorder tasks,
complete/block/cancel tasks, log/edit/delete timeslips, add/edit/restock
materials, create/revise/send/accept estimates and change orders,
deliverables and shipments, invoice create/edit/line/send, the wizard.

**Explicitly allowed:**

- **Read**, everywhere a live job is readable (detail, overview,
  history, tasks, materials, documents, linked POs).
- **Duplicate** (`JobService.duplicate_job`) — unchanged. It copies
  live tasks, materials and deliverables and never copies estimates,
  invoices, shipments, history or timeslips, which is exactly right for
  an archive. The source job's status is not checked today and must
  stay unchecked. `_assert_party_active` still applies to the chosen
  *new* contact.
- **Delete** (§3.5).
- **PO line → task links** (§3.4).
- **Email associations** (RM 2026-10-20, explicit). Linking an email to
  an archived job, and unlinking it, is allowed: the association is
  `EmailRecord.job` — a reference held by the email, not a change to
  the job — and someone researching old history will want to attach a
  found email to the job it concerned. `link_to_job` / `unlink_from_job`
  (`CanManageJobs`) check nothing about the job's state today and must
  stay that way; `EmailLinkModal.svelte`'s picker uses the default job
  query (not `openOnly`) and keeps doing so, so archived jobs are
  offered. The archived job's page lists linked emails as any job's
  does. Create-job-from-email is unaffected (it creates a live job).
- **Contact deactivation.** `ContactService`'s deactivation blockers use
  an allow-list of open job statuses; archived is not in it, so a
  customer with only archived jobs can be deactivated. The archived
  job's page then shows the archived treatment (§6.2), not the
  inactive-contact banner (the archived guard fires first and the
  banner is driven by status).

### 3.4 Purchase-order links

A PO links to a job **per line**, two ways: `PurchaseOrderLineItem.task`
(cost→sell attribution, PO-side only) or a `Material` on the job that
references the PO line (`Material.po_line_item`, created/claimed on the
job by the PO↔Material resolver).

- The **task path is allowed** on archived jobs at the API/model level:
  it is a PO-side write, the job row and its children do not change,
  and the linked PO then surfaces on the archived job's page through
  `_linked_po_variances` like any other. Adding or removing such a link
  is a PO edit, gated by PO permissions, not a job mutation. **In this
  project it is not reachable from the UI** (Claude's call, after the
  builder check): the PO line's task picker (`TaskLinkPicker.svelte`)
  queries `?open=true`, which by §3.2 excludes archived jobs, and it
  must keep excluding them — that picker also serves work that must
  never attach to an archive. A picker variant that offers archived
  tasks is a `LATER.md` entry, to be taken up with the spreadsheet
  importer when a migrated shop's needs are concrete.
- The **material path is refused** by the existing guard
  (`MaterialService.create_on_job` → `_assert_job_not_frozen`): it would
  create a Material on the archived job. No new code; the design
  records the asymmetry so nobody "fixes" it.
- So in this project, PO↔archive links arise **only from the importer**:
  an archived **material** may carry a `po_line_item` reference to an
  existing PO line (optional, §5.3), which is how a migrated shop that
  has also imported its POs links them.

### 3.4a Other live side doors

The builder check found two live paths that can reference an archived
job without going through the frozen guard. Rulings (Claude's calls):

- **Expenses.** `ExpenseService.create(job=…)` and job reassignment on
  edit never call the guard, and an expense attributed to an archived
  job would change its `spent`/`profit` and the customer's windowed
  totals — the §2 anti-goal. Both paths call
  `_assert_job_not_archived(job, 'attribute an expense to this job')`
  (the narrow helper, **not** the full frozen guard — late receipts
  against a *completed* or inactive-contact job are deliberate today and
  stay allowed). `ExpenseForm.svelte`'s `JobPicker` passes a new
  `excludeArchived` prop → `?exclude_archived=true` on `/api/jobs/`
  (a new list param; `?open=true` is too broad for this form because it
  also drops completed jobs). `EmailLinkModal.svelte`'s picker is left
  alone: linking an email to an archived job is explicitly allowed
  (§3.3, "Email associations").

### 3.5 Deletion

Archived jobs are deletable by anyone who can manage jobs
(`CanManageJobs` atom; a PM reference alone is not enough — PM scope is
for running a job, not for destroying an import). RM's reasoning
(2026-10-20): a bulk import of old jobs can't reasonably be inspected
row by row before acceptance, so a bad import must be removable
afterwards; delete-and-reimport is the only fix path.

`JobService.assert_job_deletable` currently refuses any job with
timeslips, invoices, or sent estimates/COs ("cancel it instead"). Those
checks protect *real* work history that the cascade would destroy. For
an archived job the history is imported and reproducible, so the
service **short-circuits on `STATUS_ARCHIVED`**: the frozen guard is
skipped (delete is the one allowed mutation) and the four history
checks are skipped. The cascade then removes tasks, materials,
deliverables, shipments, estimates, invoices and their line items via
the parent FKs (`CASCADE`). `Blep` is `PROTECT`-linked to Task but
archived jobs never have bleps.

**What exists today, per the builder check:** job delete is API-only
(`JobViewSet.destroy` is single-phase, no impact round-trip, permission
`CanManageJobOrPM`) and the SPA has **no job-delete control anywhere**.
History rows (`JobHistory`, keyed by plain `object_type`/`object_id`
integers, no FK) are **not** removed when a job is deleted today. So
this project builds job delete, scoped as follows (Claude's calls; RM
to veto):

- **Two-phase** via `ConfirmDeleteMixin` on `JobViewSet` for every job
  delete (it is irreversible, so the UI Decisions rule says confirm).
  `get_deletion_impact` returns counts of tasks, materials,
  deliverables, shipments, estimates, invoices and history rows.
  Live-job delete behaviour is otherwise unchanged (still refused for
  anything with history; drafts still delete) — it just gains the
  confirm round-trip, which only the API sees today.
- **SPA Delete button on archived jobs only.** Live draft jobs have no
  delete UI today and this project does not add one; that is a
  separate decision. The button opens an in-modal confirm showing the
  impact counts, then re-issues with `?confirm=true`, then navigates to
  the job's customer page.
- **Permission is status-conditional.** `destroy` keeps
  `CanManageJobOrPM` for live jobs (a PM may delete a draft they
  manage). For an archived job the view additionally requires the
  `can_manage_jobs` atom (or superuser): an archived job may carry a
  `project_manager` (§4 payload), and PM scope is for running a job,
  not for destroying an import. The SPA gates the button on the atom
  (`canManageJobs` store), not on the serializer's `can_manage`.
- **History purge, archived only.** Before the cascade, the service
  collects `(object_type, pk)` for the job and every tracked child
  (tasks, materials, estimates, invoices, deliverables, shipments) and
  deletes the matching `JobHistory` rows after the cascade; the fix
  path is bulk delete-and-reimport, which would otherwise leave a full
  orphaned set per cycle. Live-job deletes keep today's behaviour
  (orphans are rare and harmless there, and changing it is out of
  scope).

### 3.6 Labor on archived jobs: hour-unit task actuals

Archived jobs have no timeslips, and on live jobs labor hours come
*only* from timeslips (`_blep_hours`): a task's `actual_qty` is its
billing quantity (square feet, pieces, machine minutes), never labor.
Three ways of giving an archived job a labor figure were rejected on
2026-10-20 — a Job field that exists only for archives, a synthetic
Labor task or Expense minted by the importer, and a job-level number
with nowhere honest to live. What survived (RM 2026-10-20, "I think I
do want to retain it") is the one shape the system already has:

**An archived job's labor hours are the sum of `actual_qty` over its
tasks whose `unit_label` is `HOUR_UNIT`.** This is not a heuristic:
the hour unit is already the key the codebase branches on
(`hours_pair_fill`, the task service's hour handling), the entered-
quantity-in-a-time-unit shape already exists in the seeds (769 minute
tasks in nealseed), and an archived job has no timeslips by
construction, so there is nothing to double count. Live jobs are
untouched: a live entered-quantity hour task (none exist today) still
contributes nothing, because its workers would also be timeslipping.

Mechanics:

- `apps/jobs/financials.py` gains `_labor_hours(job)`:
  `_blep_hours(job)` for every job, **plus**, when `job.status ==
  Job.STATUS_ARCHIVED`, `sum(task.actual_qty or 0 for task in
  job.task_set if task.unit_label == HOUR_UNIT)` — every status, as
  `_blep_hours` counts cancelled-task bleps (the hours were worked).
  `spend_breakdown` reads `_labor_hours` for both its `labor` and
  `labor_hours` terms; `labor = labor_hours × average_labor_cost` is
  unchanged (today's rate, the same approximation live jobs make).
- No model change. No importer input beyond the task rows (§5.1).
- The archived job page shows the full P&L grid (Estimate / Spent /
  Invoiced / Profit) like any closed job. The overview spend block's
  Labor row sub-label reads **"N hours (imported)"** on an archived job
  (Claude's call) so the number's provenance is on the page; the
  lifecycle block's frozen "N tasks · Hh logged" text is left alone.
- An archived job whose source had no hours reports zero labor and a
  flattering profit. That is accepted: the customer banner carries a
  caveat whenever archives are in its figures (§3.7), and the rolling
  window ages them out.

### 3.7 Customer totals: a rolling window

`compute_customer_financials` currently sums `invoiced` and `profit`
over every job the customer ever had. RM's direction (2026-10-20):
replace lifetime with a **rolling window**, default 12 months,
user-configurable, because (a) archived data may be inaccurate and
should age out, and (b) a trailing figure answers "how active is this
customer", which is the more useful banner fact. Lifetime can be
computed by hand if ever needed.

- New Configuration key `customer_financials_window_months`, default
  `12`, integer ≥ 1. Added to the settings endpoint's PATCH validation
  (`apps/api/templates_config/views.py`, alongside
  `activity_recent_days`), to `GeneralSettings.svelte` under
  **Defaults**, to `data-constraints.md` §1.1, to test `setUp()`s and
  fixtures that seed Configuration. Missing/invalid key ⇒ 12.
- **Window rule — by job, not by invoice** (Claude's call; RM to veto):
  a job is *in the window* if it is **not closed** (any status outside
  `CLOSED_STATUSES`), or it is closed and `completed_date ≥ now −
  window`. `invoiced` and `profit` both sum `compute_job_financials`
  over in-window jobs, **archived included** (RM 2026-10-20: archived
  labor comes from imported hour tasks, §3.6, and the banner says so).
  Why job-level: `profit = invoiced − spent` and spend has no single
  date to window on (expenses, consumed materials, timeslips);
  windowing both figures by the job keeps them consistent
  with each other, and old archived jobs drop out naturally by their
  imported `completed_date`. A closed job with a null `completed_date`
  (possible for an archive with no dates) is **out** of the window.
- `open_jobs` and `outstanding` are "right now" facts and are
  **unchanged** (all jobs).
- `first_job_date` / `last_job_start` are unchanged (all jobs) — they
  are history facts, and archived jobs with dates extend them, which is
  the point.
- Banner labels become **Invoiced (12 mo)** / **Profit (12 mo)** with
  the number read from the config value (`/api/settings/` is
  config-gated, so the contact `financials` payload gains a
  `window_months` field for the label).
- **Archive caveat** (RM 2026-10-20; wording and gating Claude's
  call): the `financials` payload also gains `includes_archived`
  (bool — at least one in-window job is archived). When true,
  `CustomerHeader.svelte` renders one muted line under the figures:
  *"Includes archived jobs — imported labor may be incomplete."* When
  false, nothing; a customer with no archives never sees the caveat.

### 3.8 Dates

The importer supplies `created_date`, `start_date`, `completed_date`
(all optional; `created_date` defaults to now, as on the model).
`Job.clean`'s date-immutability rules only run on update, and
`Job.save`'s auto-stamping only fires on status *change*, so a create at
`archived` with explicit dates lands as given. `validate_data`'s
`check_jobs` date-consistency checks **skip archived jobs** (they
enumerate all other statuses explicitly; archived is simply omitted from
every set). `check_job_work_complete_gate`'s closed set gains
`STATUS_ARCHIVED` (an archived task must be terminal — the importer only
creates `complete`/`cancelled` tasks, and the validator should catch a
drift). `check_shipments`' "job has no accepted estimate" **warning**
skips archived jobs (an archived shipment needs no estimate).

### 3.9 Numbers

An archived job **keeps its original number** from the old system —
that is how people will look for it. `job_number` is `unique`; a
collision with an existing job (live or archived) is a `ValidationError
({'job_number': [...]})` from the import service, never a silent
renumber. The number is a free string (≤ 50 chars); no pattern is
enforced. The same pre-check and field-error shape applies to imported
`invoice_number` (unique; **required** on archived invoices, since
`Invoice.display_number` otherwise renders "Draft — JOB-…") and
`estimate_number` (`unique_together` with `version`; the importer sets
`version=1`, so the number is effectively unique DB-wide and a collision
is refused as `{'estimates[i].estimate_number': [...]}`, never an
IntegrityError). `NumberGenerationService` is **not** consulted and its
counters are untouched.

## 4. The import service

`apps/jobs/archive.py` (a new module — `services.py` is already 2 700
lines and this is a distinct concern; `__init__.py` stays empty):

```python
class ArchiveImportService:
    @staticmethod
    def create_archived_job(payload, *, user=None) -> Job
```

One call, one `transaction.atomic()`, one archived job with all its
children. `payload` is a plain dict (the follow-on spreadsheet importer
builds it; tests build it directly). Validation errors use the contract
shapes (`{'field': [...]}` / `{'detail': ...}`) with field paths like
`tasks[2].rate` so the follow-on importer can map them back to rows.

**Required:** `job_number` (str), `contact` (a `Contact` pk — resolving
old-system customer names to contacts is the importer's job, not this
service's). The contact may be inactive — a migrated customer may
already have been deactivated — so `_assert_party_active` is **not**
applied here (unlike `create_job`).

**Optional header:** `name`, `description`, `customer_po_number`,
`project_manager` (User pk), `created_date`, `start_date`, `due_date`,
`completed_date`, `outcome` (free text, e.g.
"completed", "cancelled 2023-04-02" — recorded in history, §5.7),
`notes` (list of `{text, timestamp?, user?}`).

**Optional children:** `tasks`, `materials`, `deliverables`,
`shipments`, `estimates`, `invoices` — shapes in §5. Everything is
written with ORM `create()` so model `save()` hooks run (history
`_created` audits, Material's `_populate_from_pli`, Estimate's portal
token), **not** through the domain services (whose guards and
status-coupled side effects are exactly what an archive must avoid).
Line items are created directly with explicit `line_number`s (1-based,
in payload order) — `LineItemService` is for live documents; the
"always renumber through the service" rule concerns *deletion* of live
lines and cascade delete of the parent is still fine.

**Side effects that must not fire, and why they don't:**

- Estimate acceptance crystallisation (`apps/estimates/signals.py`)
  fires on *status change* of an existing estimate; creating one at
  `accepted` is not a change.
- `Invoice._maybe_complete_job` and claim release fire on status
  change; creating at `paid` is not a change.
- `Job.save` auto-dates fire on status change only.
- Earmarks are created only by `InventoryService` paths the importer
  never calls.
- `Task.clean` transition check only runs when `pk` is set.

`accent_color` is auto-assigned by `Job.save` (harmless; the picker
counts only active statuses, so archives never skew it).

**Permission** (when the follow-on exposes it): `CanManageJobs`. There
is no API endpoint in this project; the service is exercised by unit
tests and by the e2e seed (§7).

## 5. What an archived job may carry

Every section is optional. Statuses are restricted to settled ones so no
archive ever shows up in a "needs attention" view.

### 5.1 Tasks

`name` (required), `description`, `sort_order`, `status` ∈
{`complete`, `cancelled`} (default `complete`), `unit_label` (default
`'none'`), `rate`, `est_qty`, `actual_qty`, `est_worker_time`,
`accounting_category` (pk), `service_item` (pk). `qty_source` is always
`entered_qty` (so `get_actual_qty` reads `actual_qty`; there are no
bleps to sum). A source that has per-task hours may import them as an
entered-quantity task with `unit_label` hours and the hours in
`actual_qty` — the same shape as a live task billed by entered hours.
On an archived job those hours **are the labor record**: `_labor_hours`
sums hour-unit task actuals for archived jobs (§3.6), so they reach
spend and profit; tasks in any other unit (pieces, minutes) are billing
quantities and do not. The task row is the only place labor enters the
import. `assignee`, `worker_queue`,
`source_scheme`, `descoped_by`, `active_modifiers` are left at
defaults.

### 5.2 Deliverables

`description` (required), `qty_ordered` (> 0), `units`, `sort_order`.
`source_line` null. These make the job duplicable with its deliverables
and give shipments something to reference.

### 5.3 Materials

`description`, `quantity`, `units`, `unit_cost`, `sell_price`,
`accounting_category`, `inventory_item` (pk, optional), `task` (index
into the payload's tasks, optional), `po_line_item` (pk, optional).
`consumption_state` is always `consumed` — that is what makes material
cost land in spend (`spend_breakdown` costs consumed materials with no
linked expense at `quantity × unit_cost`). `released_qty` 0. No
`Earmark` is created and no `InventoryItem.qty_on_hand` is touched:
imported consumption is history, not a stock movement.

**Cost provenance** (Claude's call, after the builder check):
`Material.cost_source` gains a sixth value, `COST_SOURCE_IMPORTED =
'imported'` ("Imported"), and every archived material carries it. A
`NULL` would read as provisional/unpriced in the materials panel, and
every other existing value asserts a provenance (PO, expense, catalog
entry, estimate placeholder) that is false for imported history.
`imported` is **non-minting**: `MaterialService.create_on_job`'s mint
gate mints a `LOT-` item only for `None`/`entered`, so **duplicating**
an archived job does not mint a phantom lot per priced, lot-less
material. On duplicate, `_copy_work_to_job` maps `imported` →
`estimated` for the copy (the new job's cost is a placeholder taken from
history, which is exactly what `estimated` means); every other
`cost_source` copies through as today.

### 5.4 Estimates

`estimate_number` (required), `status` ∈ {`accepted`, `rejected`,
`expired`} (never `draft`/`open` — those are live negotiations),
`created_date`, `sent_date`, `closed_date`, `expiration_date`, `lines`
(each: `description`, `qty`, `units`, `price`, `accounting_category`,
`is_comment`). `version=1`, `parent` null. At most one `accepted`
estimate per archived job (mirrors the live invariant the validator
checks). No `EstimateLineItemSource` rows: archived lines are not
claims on atoms.

`_estimated` branches on `start_date` alone: when it is set, the figure
is the composed agreement (0 with no accepted estimate); when null, the
highest-version estimate's total (0 with none). So an archived job with
a `start_date` and only rejected/expired estimates shows **Estimated
$0**. Accepted as-is (Claude's call): the importer does not validate
`start_date ⇒ accepted estimate` (a paper-record job with a known start
and no estimate at all is the common case, and null `start_date` would
cost the "started" history row), `_estimated` is not changed (it would
alter live hand-approved jobs), and the estimate's own total remains
visible on its document page and in the scope block's document list.

### 5.5 Invoices

`invoice_number` (**required**, unique — §3.9), `status` ∈ {`paid`,
`cancelled`} (never anything unpaid — RM 2026-10-20: *any job with an
open invoice needs to be live*), `created_date`, `sent_date`,
`closed_date` (defaults to `created_date` when `paid`), `lines` as for
estimates (a single summary line is fine). `qbo_*` fields null. No
`InvoiceLineItemSource` rows. `_invoiced` counts `paid` lines and
excludes `cancelled`, so a cancelled archived invoice is visible but
not counted.

Note the board's **Unpaid lane** selects by outstanding invoice
regardless of job status; restricting archived invoices to settled
statuses is what keeps archived jobs out of it. The validator gains a
check: an archived job must have no invoice outside {`paid`,
`cancelled`} (error).

### 5.6 Shipments

`sequence` (1-based, assigned by the service), `status` ∈
{`picked_up`} only, `picked_up_date` (required), `prepared_date`
(defaults to `picked_up_date`), `notes`, `items` (each: `deliverable`
index, `qty` > 0). Total shipped per deliverable ≤ `qty_ordered`
(the existing validator check). `ShipmentService.create`'s
accepted-estimate requirement is a *service* rule and is not applied.

### 5.7 History and notes

- The `@history` decorator writes a `_created` audit for the job and
  each tracked child **at import time**, attributed to `user`. That is
  true history ("imported on 2026-10-20 by R.M.") and is kept. Outside
  a request there is no `HistoryContext`, so the decorator would record
  `user=None`: the service opens a `HistoryContext(user=user)` for the
  duration of the transaction (and passes `user=` explicitly on its own
  `record_history` calls), the way `backfill_job_history` does.
- The service then writes **backdated `action` rows** on the job via
  `record_history(..., timestamp=...)` for the lifecycle facts it was
  given: created (at `created_date`), started (at `start_date`),
  outcome (at `completed_date`, text from `outcome`), plus one
  `imported` action at now with `_action = 'Imported from <source>'`
  where `source` is an optional payload string. Each `notes[]` entry
  becomes a `note` row at its `timestamp` (default now) by its `user`
  (default the importing user). Precedent: `backfill_job_history`'s
  date-anchored rows.
- Documents get no backdated lifecycle rows in this project (their
  `sent_date`/`closed_date` already tell the story on their own pages).

## 6. Frontend

### 6.1 Status plumbing

- `jobStatus.js` (§3.2) — the single home for the three groupings.
- `JobHeader.svelte`: `VALID_TRANSITIONS.archived = []`,
  `STATUS_LABELS.archived = 'Archived'`, `isTerminal` reads
  `isClosedJob`. With no next statuses, no hold, and no Edit, the header
  shows the pill, **Duplicate…**, and a new **Delete…** (archived jobs
  only; gated on the `canManageJobs` store, so hidden for PM-only
  `can_manage`) which opens the two-phase confirm of §3.5.
- `JobPicker.svelte`: new `excludeArchived` prop → `?exclude_archived=
  true` (§3.4a), used by `ExpenseForm.svelte`.
- `app.css`: `.status-archived` pill colour (muted grey — distinct from
  completed's blue and cancelled's treatment).
- `Search.svelte`: `JOB_STATUSES` gains `{ value: 'archived', label:
  'Archived' }`. The search service already matches jobs of any status.
- `ClosedCard.svelte` / `JobCard.svelte`: `archived` label and colour
  branches.

### 6.2 The archived job page

The job workspace renders as for any closed job, through the existing
**frozen** branches of the six lifecycle blocks (`jobOverview.js`),
which now key on the shared groupings. Additions:

- An **archived banner** at the top of the header, in the slot the
  frozen-party banner uses: *"Archived: this job was imported as a
  historical record and cannot be changed."* with the imported-on date
  from the job's `imported` history row (or the `_created` audit) if
  the serializer exposes it cheaply; otherwise no date. The banner is
  the only new component (`ArchivedJobBanner.svelte`, same visual
  weight as `FrozenPartyBanner`).
- Every section page (tasks, materials, documents, deliverables,
  shipments, history) renders read-only: action buttons are hidden by
  the same `isClosedJob` rule that already hides them for completed and
  cancelled jobs. Where a section today shows an add/edit control on a
  *completed* job (there should be none; the builder verifies), it is
  hidden for archived too.
- The **scope** block for an archived job with no estimate shows its
  dormant/frozen text as it would for a hand-approved job; no new copy.
- **Duplicate** works from the archived page exactly as from a
  completed one.

### 6.3 Customer page and banner

- The jobs section's open/closed split uses `isClosedJob`; archived jobs
  sort under "show N closed" with the status label **Archived** from
  `statusLabel()` (already generic).
- `CustomerHeader.svelte`: labels **Invoiced (N mo)** / **Profit (N
  mo)** from `financials.window_months`; the archive caveat line when
  `financials.includes_archived` (§3.7).
- `jobOverview.js` spend block: Labor sub-label "N hours (imported)"
  when the job is archived (§3.6). `JobHeader.svelte`'s P&L grid is
  unchanged.

### 6.4 Settings

`GeneralSettings.svelte` → Defaults: *"Customer totals window"* number
input (months, min 1) bound to `customer_financials_window_months`,
saved with the existing Defaults save.

## 7. Tests and Definition of Done

**Backend (TDD, targeted modules):**

- Model: `archived` in choices; no transition in or out; `Job.clean`
  refuses `completed → archived`, `draft → archived`, `archived → *`.
- Groupings: a test that asserts the membership of each `Job.*_STATUSES`
  set and that `archived ∈ CLOSED_STATUSES` (so a future status addition
  is a conscious decision).
- Guard: every public mutator listed in §3.3 raises the archived message
  on an archived job (parametrise over the existing frozen-job test
  list — the call sites are the same).
- Delete: archived job with invoices + sent estimate + shipments deletes
  cleanly and its history rows (job + children) are gone; the same job
  at `completed` is refused; first DELETE returns `confirm_required` +
  impact counts, `?confirm=true` deletes; PM-only user is refused on an
  archived job but can still delete a draft they manage; a live draft's
  history rows are left as today.
- Expenses: creating or re-attributing an expense to an archived job is
  refused; to a completed job still allowed.
- Email: link and unlink against an archived job succeed (the job row
  is unchanged; the email's `job` FK is); the job's email list shows it. `?exclude_archived=true`
  drops archived jobs and nothing else.
- Materials: archived materials carry `cost_source='imported'`;
  duplicating mints no lots and the copies carry `estimated`.
- Numbers: duplicate `estimate_number` / `invoice_number` refused with
  field errors; `invoice_number` required.
- Duplicate from archived: tasks/materials/deliverables carried,
  documents not, new job at `draft`/`approved` per path.
- `_labor_hours` / `spend_breakdown`: archived job with hour-unit
  tasks → their actuals × labor rate; archived job with minute- and
  piece-unit tasks only → zero labor; archived job mixing both → hour
  tasks only; cancelled hour task still counts; **live** job with an
  entered-quantity hour task and no bleps → zero labor (status gate);
  live job with bleps unchanged.
- `compute_customer_financials`: window rule (open job always in; closed
  inside/outside window; null `completed_date` out; config override;
  missing config ⇒ 12); an in-window archived job counts toward both
  `invoiced` and `profit`; `includes_archived` true only when an
  in-window job is archived (an archived job outside the window does
  not set it). `open_jobs`/`outstanding` unaffected.
- `ArchiveImportService`: minimal payload; full payload; each child
  type; every refusal (duplicate `job_number`, unpaid invoice status,
  `draft` estimate, `prepared` shipment, shipped > ordered, bad
  task index); no earmarks / no QOH change / no `*Source` rows; history
  rows at the backdated timestamps; `accepted` estimate limited to one.
- Validator: archived job skips date checks; archived + unpaid invoice
  is an error; archived + non-terminal task is an error.
- `?open=true` excludes archived; board pipeline/in-progress/unpaid
  lanes never include an archived job; Closed lane includes one inside
  retention.
- Settings PATCH validation for the new key.

**Vitest:** `jobStatus.js` groupings; `JobHeader` for an archived job
(pill text, no status select, no Edit, Duplicate present, Delete gated
on the jobs atom); `jobOverview.js` blocks frozen for archived and the
"(imported)" labor sub-label; `customerActivity.js` closes archived;
`CustomerHeader` window labels and the archive caveat shown/hidden on
`includes_archived`.

**E2E (required — user-reachable flow):** the Playwright seed
(`fixtures/playwright/seed.json`, hand-appended dumpdata rows per the
2026-07-23 email precedent) gains one archived job on an existing seeded
contact, with a couple of tasks, a paid invoice, a deliverable + shipment
and an outcome history row. Specs: open it from the customer page's
closed list and from search filtered to Archived; assert the banner, the
absence of every action control, the 12-month banner labels and the
archive caveat on the customer page; duplicate
it and land on a new draft job; link one of the seeded emails to it from
the email detail page and see it on the job; delete it (two-phase) as
the jobs-atom persona and confirm it is gone; confirm the PM-only
persona gets no Delete.

**Docs (same session):** `jobs-and-tasks.md` (new §3.8 "Archived
jobs", §3.6 note that archived is a valid source, §3.7 cross-ref),
`data-constraints.md` (§1.1 new key; Job status table; the archived
invariants in §2), `contacts-and-businesses.md` (banner window),
`architecture-and-conventions.md` (status groupings as a convention),
`frontend/README.md` if the banner pattern is new. Then delete this
plan.

## 8. Left to the builder

- Exact wording of the guard message, banner, and pill colour.
- Where in `JobSerializer` any `imported_at` convenience field lives,
  and whether `imported_at` is worth a query.
- Payload validation implementation (hand-rolled vs a DRF serializer
  used off-request) — contract-shaped errors are the requirement.
- Test-fixture plumbing for the new Configuration key.
- Whether `jobStatus.js` also absorbs `JobHeader`'s `STATUS_LABELS`.
- The delete confirm's exact copy and the impact-count layout.
- Migration ordering for the two model changes (`archived` choice on
  Job; `imported` choice on Material).

## 8a. Calls made after the builder check (RM to veto)

A fresh reviewer read the draft as a builder would. Its questions were
settled as follows; each is marked "Claude's call" where it appears.

1. **Job delete had to be built, not gated** — the SPA has no delete
   control and the API is single-phase. Scoped to: two-phase confirm on
   the viewset for all jobs; a Delete button on archived jobs only;
   status-conditional permission (atom for archived, PM-or-atom for
   live); history purge for archived deletes only (§3.5).
2. **History rows are not purged today** on any delete; archived
   deletes purge theirs (§3.5).
3. **Material cost provenance**: new `cost_source='imported'`,
   non-minting; duplicate maps it to `estimated` (§5.3).
4. **Expense attribution** was a live side door into archived spend:
   narrow archived-only guard in `ExpenseService`, `excludeArchived`
   picker for the expense form; email linking left alone (§3.4a).
5. **PO line → archived task** is UI-unreachable once archived is
   closed; accepted for this project, `LATER.md` entry (§3.4).
6. **`start_date` without an accepted estimate** shows Estimated $0;
   accepted, importer does not validate it (§5.4).
7. `estimate_number` is `unique_together` with `version` → pre-check and
   field error; `invoice_number` required (§3.9).
8. The import service opens a `HistoryContext` so `_created` audits
   carry the importing user (§5.7).

## 9. Open questions resolved in conversation (for the record)

| Question | Answer (RM, 2026-10-20) |
|---|---|
| Flag or status? | Status (Claude's recommendation, accepted). |
| Timeslips? | Never imported. |
| Labor hours? | Per task only, as entered-quantity hour tasks; on an archived job their actuals are the labor hours (§3.6). A Job field, a synthetic task and a synthetic expense were all rejected (RM 2026-10-20). |
| Archived jobs in customer profit? | Yes, in the window like any job; the banner shows a caveat line whenever an archived job is in the figures (§3.7). |
| Actuals for spend on all jobs? | No — actuals are billing basis, not hours on non-hour tasks. Archived is just different. |
| Where are archived jobs found? | Customer page and search. Not the board/home. |
| In customer dollar totals? | Yes, but totals become a rolling window (12 mo default, configurable); lifetime figure replaced. |
| Open invoices on archives? | Never — a job with an open invoice must be live. |
| Shipments, PO links, PM? | All allowed, all optional. |
| Email associations? | Explicitly allowed — the link lives on the email, not the job. |
| Required fields? | Job number and contact; the contact may be inactive. |
| Delete? | Allowed with the jobs atom (bulk imports can't be pre-inspected). |
| Closed lane shows recent archives? | Accepted. |
