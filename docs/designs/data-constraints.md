# Data Constraints

Business invariants that the database schema cannot enforce. These constraints are
enforced by model `clean()`/`save()` methods, services, and signals — all of which
are bypassed when loading fixture data directly.

This document answers: **what must be true about each object for it to be
indistinguishable from one created by the running application?**

Consumers: the data validator (`validate_data.py`), the translation script
(`convert_neals_data.py`), anyone creating test fixtures.

This doc owns cross-model invariants and field-by-field constraints. The
seven topic docs (`architecture-and-conventions.md`,
`jobs-tasks-and-worksheets.md`, `estimates-and-prices.md`,
`materials-inventory-and-purchasing.md`, `invoicing-and-expenses.md`,
`quickbooks-integration.md`, `users-and-permissions.md`) own the workflows;
relevant sections cross-reference them.

---

## Section 1: Model Constraints

Models are ordered by dependency depth (least constrained first). When creating
data, work top to bottom — everything a model needs is defined above it.

---

### 1.1 Configuration and AppState

Two key-value stores, deliberately split by who writes them. No FK dependencies.
Both have **key** as primary key (unique, max 100 chars) and a string **value**.

- **`Configuration`** (`config` table) — **user-settable settings**. Backs the
  Settings UI; the `/api/settings/` PATCH endpoint writes arbitrary keys here.
- **`AppState`** (`appstate` table) — **machine-managed state**, written by the
  app and never by a human. Kept separate so the settings editor can't touch it.

**Document numbering** splits across both: the *pattern* is a user-settable
`Configuration` key; the *counter* is `AppState`:

| Configuration (pattern) | AppState (counter) |
|---|---|
| `job_number_sequence` | `job_counter` |
| `invoice_number_sequence` | `invoice_counter` | _(retired 2026-07-21 — QBO assigns invoice numbers; rows are harmless leftovers)_ |
| `po_number_sequence` | `po_counter` |

Per-tenant email account (2026-07-23, Settings → Email; Configuration-first
with env-settings fallback via `apps/core/email_account.py`):
`email_imap_server`, `email_address`, `email_password`, `email_smtp_host`,
`email_smtp_port` — the two server hosts and port are **seeded gmail
defaults** (migration 0027; tenant supplies address+password).
`email_configured()` (imap+address+password) gates the
Email area; `POST /api/settings/email-verify/` live-tests both directions.

The live pattern rows, both AppState counters, and `units_list` are **seeded
by data migration** (`core/0027_seed_setup_defaults`, idempotent, never
overwrites) — a migrate-only fresh database can create Jobs/POs without
fixtures (2026-07-23; previously fixture-only, a fresh-tenant trap).

Sequence values use Python format placeholders: `{year}`, `{month:02d}`,
`{day:02d}`, `{counter:04d}`. Counter values are string-encoded integers.
Estimates are **not** numbered via `NumberGenerationService` — they derive
`{job_number}-{version}` — so there is no estimate sequence/counter key (the dead
`estimate_number_sequence` / `estimate_counter` were removed).

**AppState (machine state):** the three counters above, plus `latest_email_date`
(IMAP fetch cursor).

**Configuration (other user-settable keys):** `email_retention_days`,
`email_display_limit`, `est_expire_days` (also governs ChangeOrder expiry),
`board_closed_retention_days`, `our_domain`, `our_public_url`, `business_email`
(shop notification address for customer accept/reject/request-changes events on
both estimates and change orders; if unset, notifications are silently skipped),
`units_list`, `qbo_payment_accounts`. Optional outbound-document templates
(each falls back to a hard-coded default if unset): `estimate_email_subject_template`
/ `estimate_email_body_template`, `change_order_email_subject_template` /
`change_order_email_body_template`. **Taxation is handled by QuickBooks** —
there are no app-side tax keys (`default_tax_rate` / `org_tax_multiplier` were
removed).

Schedule view: `schedule_week_envelope` (JSON; the shop's default work week —
`{"mon": [["08:00","17:00"]], …, "sat": [], "sun": []}`: exactly the seven keys
`mon`…`sun`, each an ordered list of `["HH:MM","HH:MM"]` intervals — zero-padded
`HH:MM`, start < end, strictly increasing across the day, non-overlapping,
non-touching; gaps are breaks, an empty list is a day off; validated by
`apps.schedule.calendar_arithmetic.validate_week_envelope`),
`schedule_task_buffer_minutes` (`10`), `schedule_horizon_days` (`3`).
(`schedule_workday_start` / `schedule_workday_end` were retired — the weekly
envelope replaces them.)

Activity page: `activity_recent_days` (`5`) — integer ≥ 1; the backward
"recent" look-back window (in days) governing the whole Activity dashboard
(completed bleps, job/PO/invoice events) **and the Home page's recent lists**
(the Work tab's session list and the Shifts tab's My Shifts list — delivered
to the SPA as `recent_days` on the `/api/home/` payload). Distinct from the
*forward* `schedule_horizon_days`. Missing or unparseable falls back to `5`;
the settings API (`PATCH /api/settings/`) rejects non-int and `< 1` values.
See `schedule.md` §7.

Job financials: `average_labor_cost` (`0`) — approximate labor cost in dollars
per hour, applied to every logged blep hour when computing a job's **Spent**
rollup (`apps/jobs/financials.py`). A stand-in until per-worker pay/cost rates
exist; missing or blank is treated as `0`, so labor contributes nothing until an
operator sets it. Editable in **Settings → Setup → Defaults**; the settings API
(`PATCH /api/settings/`) validates it as a non-negative number (blank allowed).
See `jobs-tasks-and-worksheets.md` §9.3.

Time tracking: `blep_minimum_minutes` (`1`) — below this elapsed duration
(whole minutes; times are minute-granular) a blep is an accidental start.
Closing one (via any path — stop, clock-out, logout/deactivation) cancels it
with full `cancel_work` undo (delete + first/only-activity revert) rather than
persisting a closed blep; the UI's Stop control reads Cancel below the
threshold. **Invariant: a sub-minimum close is never persisted — it is
cancelled.** See `jobs-tasks-and-worksheets.md` §4.5/§5.5.

Materials: `default_material_accounting_category` (unset) — string-encoded
`AccountingCategory` PK applied to `is_material=True` hand-lines (Estimate and
ChangeOrder) with no explicit AC, and used to pre-fill `MaterialModal`'s
category field (`jobs-tasks-and-worksheets.md` §9.5). Editable in **Settings →
Accounting Categories → Materials** (blank clears it). The settings API
(`PATCH /api/settings/`) rejects a value that isn't blank or an existing
**active** `AccountingCategory` id. See `estimates-and-prices.md` §6.4.

---

### 1.2 User

Django `AbstractUser`. No Minibini-model dependencies (optional `contact` FK is
set later).

- Standard Django user fields apply (username unique, etc.)
- **contact** (optional OneToOne → Contact): set after Contacts exist
- **schedule_envelope** (nullable JSONField, default null; migration
  `core.0025`): the user's personal weekly work envelope in the canonical
  week-envelope shape (see `schedule_week_envelope` in §1.1). Null = use the
  shop default. Validated by
  `apps.schedule.calendar_arithmetic.validate_week_envelope` on both write
  endpoints (`PUT /api/auth/me/schedule-envelope/`,
  `PUT /api/users/{id}/schedule-envelope/`); exposed read-only on the auth
  `UserSerializer` and admin `UserDetailSerializer`.
- **Permissions**: 4 custom atoms defined on the model:
  `can_manage_jobs`, `can_manage_financials`, `can_manage_time`,
  `can_manage_config`. There is no `can_approve_expenses` atom — it was
  retired.
- Django Groups are not used. `set_permissions` writes directly to
  `user_permissions`; the admin UI uses per-atom checkboxes. Fixture data
  should not ship default groups.
- A `system` user (username='system', is_active=False) is auto-created by
  signals when needed — data sets should include one.

See `docs/designs/users-and-permissions.md` for the permission-to-view mapping
and the actor/target authorization rules.

---

### 1.2a Shift (+ ShiftChangeRequest / BlepChangeRequest)

Depends on: User.

A work-attendance span: the clock-in/clock-out band that encloses a worker's
Bleps. `db_table = 'shifts'`. `@history(exclude=['shift_id'])`.

- **shift_id**: auto primary key
- **user** (required FK → User, PROTECT, `related_name='shifts'`)
- **start_time**: required datetime (clock-in)
- **end_time**: nullable datetime. **Null = open** (worker is currently on the
  clock). `is_open` property returns `end_time is None`. When set, must be
  ≥ `start_time` (enforced by `ShiftService`).
- **Minute granularity**: Shift and Blep `start_time`/`end_time` are stored
  floored to the whole minute (seconds + microseconds = 0) via `Model.save()`
  (`Shift.save()` / `Blep.save()`, using `apps.core.timeutils.floor_to_minute`).
  This keeps the minute-granular edit UI (`datetime-local`) round-tripping
  losslessly and makes shift↔blep enclosure boundaries align exactly:
  `clock_out` sets the shift end = the closed blep end to the same minute, so
  the enclosure check (which is monotonic under flooring) cannot reject an edit
  re-sent at minute precision. `QuerySet.update()` / `bulk_*` bypass `save()`
  and must not be used to write these fields (iterate and call `.save()`).
- **One OPEN shift per user**: a user may have at most one shift with
  `end_time IS NULL`. This is enforced in `ShiftService` (`clock_in` blocks a
  second clock-in; `ensure_open_shift` reuses the existing open one) — **not**
  a DB constraint (MySQL has no partial unique index). Fixtures must not ship
  two open shifts for one user.
- **Multiple shifts per day** are allowed (split shifts, clock-out for lunch
  and back in).
- **No overlapping shifts per user** (added 2026-07-19): one user cannot be
  clocked in twice at once, so two shifts of the same user may never overlap
  — overlap would double-count attendance in the shift report. Spans are
  **half-open**: a shift ending exactly when the next starts (split shifts)
  is legal. A null `end_time` (open shift) is unbounded on the right.
  Enforced by `ShiftService._assert_no_overlap` on every shift write path —
  `create`, `update`, and `clock_in` — which also covers change-request
  approval (`ShiftChangeRequest.apply_requested` routes through
  `create`/`update`). Inputs are minute-floored before comparison, matching
  what `save()` stores. Service-layer only, not a DB constraint.

#### The shift↔blep enclosure invariant

**Every Blep must be fully enclosed by a Shift of the same user:**
`shift.start_time <= blep.start_time and blep.end_time <= shift.end_time`.
Bleps and Shifts are related by time overlap, not by an FK. Only a *closed*
shift can enclose (an open shift has no end yet). The invariant is enforced in
the service layer, not the DB — helpers live in `apps/core/time_integrity.py`
(`unenclosed_bleps_for_shift`, `enclosing_shift_for_blep`):

- Starting a live Blep auto-opens a shift for the worker if none is open
  (`TaskLifecycleService.start_work` → `ShiftService.ensure_open_shift`).
- Creating / editing a Blep (live or historical) is rejected unless a shift
  of that user encloses the resulting span.
- Editing / creating a Shift is rejected if it would fail to enclose any of
  the user's existing bleps (`ShiftService._assert_encloses`); the
  manager-approve path re-checks inside a transaction and rolls back on
  conflict.
- Pre-feature bleps were **backfilled** with enclosing shifts (one per
  user-per-local-day) during the feature's initial rollout, not exempted, so
  the invariant holds for historical data. (Open bleps and user-less bleps
  can't be enclosed and were skipped.)

Clocking out (`ShiftService.clock_out`) closes the worker's open bleps first,
then stamps `end_time` on the shift — so a clock-out can never leave a blep
unenclosed.

#### Self-edit window

`ShiftService.SELF_EDIT_WINDOW_HOURS = 30`. A worker may edit/create their own
shift only when its `start_time` is within the last 30 hours; older shifts must
go through a change request. Holders of `can_manage_time` (and superusers) edit
any shift at any time. (Bleps use the same **30h** self-edit window — see
§1.12.)

#### ShiftChangeRequest / BlepChangeRequest

Workers whose target time is outside their self-edit window submit a change
request that a manager approves or denies. Both concrete models extend the
abstract `TimeChangeRequest` (`apps/core/models.py`); `ShiftChangeRequest`
lives in core, `BlepChangeRequest` in `apps/jobs/models.py`.

- `db_table = 'shift_change_requests'` / `db_table = 'blep_change_requests'`.
  Both `@history(exclude=['request_id'])`.
- **requester** (required FK → User, PROTECT)
- **requested_start** (required) / **requested_end** (nullable) — the proposed
  span
- **reason** (required text — `TimeChangeRequestService.submit` rejects blank)
- **status**: `pending` (default) → `approved` / `denied`
- **has_known_conflict**: boolean set on submit; a request that would break the
  enclosure invariant is still allowed to be submitted (warn-and-flag), but
  approval re-validates and rolls back if it still conflicts.
- **reviewer** (nullable FK → User), **reviewed_at** (nullable),
  **review_note** (blank text), **created_at** (auto)
- `ShiftChangeRequest.shift` (nullable FK → Shift, PROTECT): null = a
  create-new-shift request. `BlepChangeRequest.blep` (nullable FK → Blep) +
  `task` (nullable FK → Task): null `blep` = a create-new-blep request against
  `task`.
- **Conflict surfacing**: `conflicting_records()` returns the actual records a
  request collides with (and `would_conflict()` derives `bool(...)` from it, so
  there's one source of truth). A `ShiftChangeRequest` returns the bleps the
  requested span would orphan (`unenclosed_bleps_for_shift`); a
  `BlepChangeRequest` returns the worker's shifts that overlap the requested
  time but don't enclose it (`overlapping_shifts_for_blep` in
  `apps/core/time_integrity.py`) — the candidates a manager widens. The
  change-request serializers expose this as a read-only `conflicts` list so the
  manager's review queue links straight to the record to adjust, then approve.

See `docs/designs/users-and-permissions.md` for the endpoint/atom mapping and
`jobs-tasks-and-worksheets.md` §5 for the Blep side.

---

### 1.3 AccountingCategory

Standalone. No FK dependencies.

- **code**: unique, max 20 chars (e.g. "SVC", "MAT")
- **name**: max 100 chars
- **taxable**: boolean, default True. The **only** konbini-side taxability
  signal: per-line QBO TaxCodeRef reads it directly (the per-line
  `taxable_override`/`tax_rate_override` fields were removed 2026-07-21).
- **is_active**: boolean, default True (soft delete)
- **qbo_item_id** / **qbo_expense_account_id**: optional, populated after
  connecting QBO. `qbo_item_id` is the **fallback** ItemRef for invoice
  lines with no catalog identity, and the source of `IncomeAccountRef`
  when `QBOItemMintService` mints catalog Items in the category (see
  quickbooks-integration.md).

---

### 1.4 PaymentTerms

Standalone. No FK dependencies.

- **term_id**: auto primary key
- No additional business constraints beyond DB schema

---

### 1.5 Business and Contact

Full model/service/API narrative: `docs/designs/contacts-and-businesses.md`.
This section stays a terse invariant reference.

These two models have a circular dependency: Business requires a `default_contact`
(non-nullable FK → Contact), and Contact optionally references a Business. Create
them together: create the Contact first with `business=None`, then the Business
with `default_contact` pointing to that Contact, then update the Contact's
`business` FK.

#### Business

- **our_reference_code**: unique, max 50 chars. Auto-generated as `BUS-{N:04d}`
  if not provided. Fixture data should always provide an explicit value.
- **default_contact** (required FK → Contact): must point to a Contact whose
  `business` FK points back to this Business
- **business_name**: required, max 255 chars, **unique** (case-insensitive
  pre-check + DB constraint — see the duplicate-detection section of
  `contacts-and-businesses.md`)
- **qbo_customer_id** / **qbo_vendor_id**: nullable, for QBO sync
- **tax_multiplier**: nullable decimal; null/1.0 = full rate, 0 = exempt,
  0.5 = half rate

#### Contact

- **email**: required, must be non-empty and valid, **unique** (case-insensitive
  pre-check + DB constraint — see the duplicate-detection section of
  `contacts-and-businesses.md`)
- **At least one phone number**: one of `work_number`, `mobile_number`,
  `home_number` must be non-empty
- **first_name** / **last_name**: required (max 100 chars each)
- **business** (optional FK → Business): if set, `qbo_customer_id` must be null
  (mutual exclusivity — contacts with a business use the business's QBO ID)
- **Deletion blocked** if contact is the sole contact for a business (the
  business would lose its required `default_contact`), or if it has any
  associated Job or Bill (the Bill check guards legacy rows only — retired
  schema, §1.18)

---

### 1.6 InventoryItem

Depends on: AccountingCategory.

- **code**: unique, max 50 chars. No duplicates allowed.
- **accounting_category** (required FK → AccountingCategory): a missing
  category should be impossible at the DB level. `validate_data.py` still
  warns on null to catch corrupt fixtures.
- **purchase_price**, **selling_price**: non-negative decimals
- **qty_on_hand**, **qty_sold**, **qty_wasted**: non-negative decimals
  (`qty_on_hand` has a DB `CHECK >= 0`)
- **is_active**: boolean, default True — the **only** retirement flag (a manual
  human judgment). `is_catalog`/`is_inventoried` and the computed
  `is_finished_lot` are **dropped**: one item kind, no catalog/lot fork, no
  auto-hiding. Clutter is handled by ranking (in-stock then newest), not hiding.
- **Deletion blocked** (`InventoryService.assert_item_deletable`) if referenced
  by any line item (PROTECT), Material, Earmark, or Expense stock receipt —
  the SET_NULL FKs would otherwise silently demote established materials.
  Never-referenced rows (mistake correction) delete; everything else retires
  via `is_active` and simply sinks in the ranking at QOH 0. No auto-delete and
  no auto-hiding (`collect_if_finished` and the hide-on-spend filter are gone).

---

### 1.7 RateScheme

Depends on: AccountingCategory. (`db_table = 'rate_schemes'`, FK field
`rate_scheme`, API `/api/rate-schemes/`.)

The service price list — a named, priced service the shop performs.
Describes how a Task/ServiceItem's billable amount is computed. Once any
atom references an entry, it is effectively immutable; edits must go
through `supersede()`, which forks a new entry and renames the old row.
See `docs/designs/estimates-and-prices.md` for algorithm/modifier semantics.

- **name**: required, unique, max 100 chars. `supersede()` renames the old
  row to `"<name> (v{N})"` before creating the new one to preserve the
  DB-level unique constraint.
- **algorithm**: one of `elapsed_time`, `entered_qty`, `percentage`
  (the former `flat_fee` algorithm was **removed** — fixed charges are the
  `Fee` atom, §1.8a).
- **rate**: decimal(10,2). Semantics depend on `algorithm`:
  - `elapsed_time` / `entered_qty`: per-unit price; **must be ≥ 0**
    (`RateScheme.clean()` raises `ValidationError` for negative values
    on these two algorithms).
  - `percentage`: the percent value (e.g. `10` = 10% surcharge; `-5` = 5%
    discount). **Negative values are allowed** only for `percentage`. This
    is the sole exception to the non-negative rate invariant.
    `validate_data.py` raises an error if a non-`percentage`
    service has a negative rate.
- **unit_label**: max 50 chars
- **modifiers**: JSON list of `{key, label, percent}` dicts (default `[]`).
  `percentage` services have no modifiers (their `modifiers` list is `[]`).
- **accounting_category** (required FK → AccountingCategory): `clean()`
  raises if missing
- **replaced_by** (optional FK → self) / **replaced_at**: set by `supersede()`

#### `percentage` algorithm — applicability constraints

A `percentage` service can **never** back a `Task` or `ServiceItem`. The
application enforces this in multiple places:

- `TaskService.create_direct` rejects a `percentage` rate_scheme.
- `EstimateLineItemSerializer` / `InvoiceLineItemSerializer` reject it on atom-based lines.
- `GET /api/rate-schemes/?task_applicable=true` excludes `percentage` entries from the response.
- `RateScheme.effective_rate()` and `get_actual_qty()` raise `ValueError` if called on a `percentage` entry.

A `percentage` entry that is **not** referenced by any atom (it can only be
used as `EstimateLineItem.adjustment_service` or
`InvoiceLineItem.adjustment_service`, which do not count as atom references)
is therefore always un-frozen and can be superseded freely.

#### Frozen fields

Once any Task or ServiceItem references an entry, the fields
`name`, `description`, `algorithm`, `rate`, `unit_label`, `modifiers`, and
`accounting_category` are frozen (`FROZEN_FIELDS`). `clean()` rejects edits.
The only legitimate mutations on a referenced entry are
`replaced_by`/`replaced_at` and the in-place rename `supersede()` does on
its predecessor. If `replaced_by` is set, `replaced_at` must also be set,
and vice versa. Templates pointing at a superseded entry raise
`SchemeSupersededError` when `generate_task()` is called.

---

### 1.8 Job

Depends on: Contact.

#### Status machine

```
draft → submitted → approved → in_progress → work_complete → completed
                  ↘ rejected   ↘ cancelled    ↘ cancelled    ↘ cancelled
draft → rejected
```

Valid transitions:
- `draft` → `submitted`, `rejected`
- `submitted` → `approved`, `rejected`
- `approved` → `in_progress`, `cancelled`
- `in_progress` → `work_complete`, `cancelled`
- `work_complete` → `completed`, `cancelled`, `in_progress`
- `cancelled` → `in_progress`
- `rejected`, `completed` → (terminal)

`work_complete → in_progress` and `cancelled → in_progress` are
*reactivation* transitions (undo a premature completion / accidental
cancel), gated by `can_manage_jobs` at the API layer.

`STATUS_IN_PROGRESS` sits between `approved` and `work_complete` (added when
WorkOrder was removed). `work_complete` = every task terminal AND no
pending material (task-attached or loose) with quantity still committed —
enforced as a hard gate in `JobService.update_job` on EVERY path into the
status (the B4 work-complete gate, 2026-07-12;
`JobService.work_complete_blockers` computes the offending list, and
`validate_data` errors on violations); earmarks release on entry.
`completed` = fully closed; gated on **both** all invoices
resolved **and** all deliverables shipped (see "Implied state" below and
§2.5).

`on_hold` is a **flag** (BooleanField, default False), not a status — a
held job keeps its true underlying status. It is the general pause
primitive (CO negotiation, awaiting deposit, backordered material),
settable only while the job is `approved` or `in_progress`, via
`JobService.hold_job(pk, reason)` (reason required; rejected while any
open Blep exists). `JobService.release_job(pk)` drops the flag (blocked
while a live CO exists — see "Implied state" below); the CO-accept path
clears the hold itself and the job resumes its true status directly.
Non-CO holds resume manually.

#### Fields

- **job_number**: unique, max 50 chars. Generated via NumberGenerationService
  (pattern from Configuration). Only generated for new instances.
- **contact** (required FK → Contact, PROTECT). Reassignable only while
  `status == draft` — `Job.clean()` rejects a contact change once the job has
  left draft (enforced regardless of what else changes in the same save; a
  no-op write of the same contact is always allowed). The SPA's Edit Job modal
  only renders the contact picker for draft jobs, showing the contact name
  read-only otherwise.
- **project_manager** (optional FK → `core.User`, SET_NULL, `related_name='managed_jobs'`): informational owner of the job; no business-logic side effects, no status interaction, no dedicated permission. Set/cleared via the job edit page by `can_manage_jobs`.
- **status**: must be one of the choices above, default `draft`
- **on_hold**: BooleanField, default False. Orthogonal pause flag — see above. Set/cleared only via `JobService.hold_job` / `release_job` (also cleared by CO acceptance and by cancellation); the API exposes it read-only (`POST /api/jobs/{id}/hold/` / `.../release/` are the write paths) and a status PATCH of `'on_hold'` is a 400.
- **hold_reason**: TextField, blank-allowed. Free-form pause reason ("CO-2026-0007 in negotiation", "awaiting deposit"). Cleared automatically by `Job.save()` whenever the `on_hold` flag drops.
- **name** / **description** / **customer_po_number**: optional text

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **start_date**: auto-set to `now()` on transition to `approved`. Immutable
  once set. Should be null for `draft`/`submitted`/`rejected`.
  **Load-bearing for the Estimated rollup:** because it is set exactly once (at
  first Approved) and never cleared, `start_date is not None` is the canonical
  "this job was ever approved / an estimate was once accepted" signal that
  `apps/jobs/financials.py` keys off to choose `compose_agreement` vs. the
  highest-version-estimate fallback. **If `start_date` is ever made
  clearable/editable, the Estimated branch in `financials.py` must be revisited**
  — a cleared `start_date` would silently flip an approved job back to the
  fallback path and misreport its Estimated total.
- **due_date**: optional, user-set
- **completed_date**: auto-set to `now()` on transition to `completed`,
  `cancelled`, or `rejected`. Immutable once set — *except* it is cleared
  back to null when a Job is reactivated to `in_progress` from
  `work_complete`/`cancelled`. Must be null for
  `draft`/`submitted`/`approved`/`in_progress`/`work_complete`.

#### Implied state from other models

- Any Estimate `open` or later → Job must be `submitted` or later.
- Any Estimate `accepted` → Job must be `approved` or later (or `cancelled`).
- At most one Estimate for the Job in `draft` or `open` status at a time;
  others must be `rejected` or `superseded` (validator-enforced).
- Job `approved` → exactly one Estimate must be `accepted`.
- Job `completed`/`cancelled` → no unresolved Estimates (none in `draft` or
  `open`).
- Job `work_complete` (or later) → all Tasks on the Job terminal.
- Job `completed` → all Deliverables on the Job have `qty_picked_up == qty_ordered` (the all-shipped gate; §2.5).
- All Invoices for a Job `paid`/`cancelled` AND all deliverables shipped → Job must be `completed` (`JobService.maybe_complete_if_resolved`).
- Job `cancelled` → all Invoices for the Job must be `cancelled` *or* outstanding under the stop-and-bill flow (see `invoicing-and-expenses.md` — `CANCELLED` is in `BILLABLE_JOB_STATUSES`; the Unpaid lane keeps a cancelled-with-open-invoice job visible until its invoices clear).
- Job held (`on_hold` flag) → no release while any `ChangeOrder` on the job is `draft` or `open` — the release guard, enforced by `JobService.release_job` and by the cancel path. The CO-accept handler clears the hold itself (the job's true status is preserved); a discarded draft CO also clears the guard.
- Job held → no status change at all (`JobService.update_job` rejects) **except** cancellation, which runs the release guard and drops the flag as part of the transition.

`JobService.hold_job` and transitions into `cancelled` are rejected if any `Blep` on the job's tasks is open (`end_time__isnull=True`).

**Job deletion (Rule 1 at job scale)**: `JobService.assert_job_deletable` (run
by the `DELETE /api/jobs/{id}/` endpoint) refuses when the job has any bleps,
any invoice, or any non-draft estimate/change order — the cascade would destroy
recorded work wholesale; those jobs are `cancelled` instead. An unworked draft
quote still hard-deletes.

While held (`on_hold` flag), the following are blocked (purely by flag filter — no Task is touched):
- New bleps (explicit `if job.on_hold` check in `_assert_job_allows_blep`, ahead of the status allow-list).
- Task and material mutations (`_assert_job_not_on_hold` in `JobService`).
- Schedule forecasting (`ScheduleService` never forecasts a held job; its history bars still render).
- Shipment creation (`ShipmentService._assert_job_not_on_hold`).

See `docs/designs/jobs-tasks-and-worksheets.md` for the loose-pending-material
guard on `in_progress → work_complete`.

---

### 1.8a Fee

Depends on: Job, AccountingCategory, (optionally) Task.
(`db_table = 'fees'`, FK field `job` `related_name='fees'`, API
`POST /api/jobs/{id}/fees/`.)

A **fixed charge** owned by the Job — `quantity × unit_rate`. The
crystallized form of an accepted estimate hand-line, and the replacement
for the removed `flat_fee` RateScheme algorithm. No lifecycle, no actuals;
always billable.

- **job** (required FK → Job, CASCADE)
- **task** (optional OneToOne → Task, SET_NULL): the work behind the charge
- **description**: CharField(255), blank default `''`
- **quantity**: decimal(10,2), default `1.00`
- **unit_rate**: decimal(10,2) — **required**
- **accounting_category** (required FK → AccountingCategory, PROTECT) —
  **NOT NULL**; a missing value surfaces as a `ValidationError` (→ 400) via
  `full_clean`, never a 500
- **sort_order**: PositiveInteger, default 0

`compute_amount() = (quantity × unit_rate).quantize('0.01')`. Writes go
through `FeeService.create_on_job` / `update` / `delete` (on-hold guarded).

- **Deletion (Rule 1)**: `FeeService.delete` refuses while the fee is claimed
  by any estimate/CO line or on a live invoice — removing an agreed charge is
  a change order, not a delete. Unreferenced fees (setup scratch, mistakes)
  delete freely.

---

### 1.9 ~~EstWorksheet~~ (removed)

> **Removed** with the planning layer. There is no worksheet model. Work
> atoms (`Task`, `Material`, `Fee`) live directly on the `Job`; the estimate
> is a lens that projects them.

---

### 1.10 ~~PlanTask~~ (removed)

> **Removed** with the planning layer. There is no planning-side task model.
> `Task` (§1.11) is the single work-and-billing task; the estimate projects
> a Task's `est_qty` via `Task.compute_estimate_amount`.

---

### 1.11 Task

Depends on: Job, RateScheme, (optionally) User, ServiceItem.

The Job's metered work atom. Lives on a Job; carries lifecycle, hierarchy,
and Bleps.

#### Status machine

```
pending → in_progress → complete
        ↘ blocked ↗    ↘ (terminal)
        ↘ complete
        ↘ cancelled
in_progress → blocked → in_progress
            ↘ complete
            ↘ cancelled
blocked → cancelled
```

Valid transitions:
- `pending` → `in_progress`, `blocked`, `complete`, `cancelled`
- `in_progress` → `blocked`, `complete`, `cancelled`
- `blocked` → `in_progress`, `complete`, `cancelled`
- `complete`, `cancelled` → (terminal)

#### Fields

- **job** (required FK → Job, CASCADE)
- **rate_scheme** (required FK → RateScheme, PROTECT): NOT NULL at DB level
- **active_modifiers**: JSON list of modifier keys (always a list, never a
  dict — see RateScheme §1.7).
- **est_qty** (inherited from `TaskBase`): nullable on Task — both at the DB
  level and the application layer. `Task.clean()` does **not** reject null.
  Drives the **estimate** lens (`Task.compute_estimate_amount`).

  In practice a null `est_qty` can only arise on a task **added directly to
  the Job with the quantity left blank** — specifically the two manual
  direct-create routes, both of which send `est_qty` through unguarded and
  both of which route through `TaskService.create_direct` (since
  2026-07-12 the subtasks endpoint no longer bypasses the service):
    - top-level task — `POST /api/jobs/{id}/tasks/`
    - subtask — `POST /api/tasks/{id}/subtasks/`

  Template-generation routes guarantee a non-null value:
    - `TaskService.create_from_template` defaults to `Decimal('1')`
    - the job-side `add-from-template` API defaults a blank to `Decimal('1')`;
      bulk template expansion uses `TemplateTaskAssociation.est_qty`
      (`default=1`)
- **est_worker_time**: optional Duration — **required when explicitly
  assigning** (the invariant lives on the assign gestures, not
  `Task.clean()`; auto-assign on start is exempt — see
  `jobs-tasks-and-worksheets.md` §4.4)
- **actual_qty**: optional decimal — running total of worker-entered increments for `entered_qty`
  schemes. Null for `elapsed_time` (derived from Bleps). Drives the
  **invoice** lens (`Task.compute_amount`).
- **status**: default `pending`
- **blocked_reason**: text, default '' — set by `block_task(reason=...)`, cleared by `unblock_task`/`complete_task`/`cancel_task`. The previous reason is overwritten as current state, but every set/clear lands in Task history as an audit diff (lifecycle transitions save() through the tracker since 2026-07-12)
- **worker_queue**: optional integer — position in assignee's queue; excluded from history (cosmetic)
- **assignee** (optional FK → User, SET_NULL): explicit assignment requires
  a non-zero `est_worker_time` (see that field); auto-assign on first
  blep does not
- **parent_task** (optional FK → self, CASCADE): **one level only** — a
  task whose `parent_task` is set can never itself be a parent
  (`TaskService.create_direct` rejects grandchildren and cross-job
  parents)
- **sort_order**: auto-assigned per Job on save
- **name** / **description**: text

#### Implied state from other models

- An **explicitly** assigned Task must carry a non-zero `est_worker_time`
  — assigned work has to be schedulable. Enforced on the assign gestures:
  `TaskService.assign` pre-checks and raises `TaskWorkerTimeRequired` (so
  the assign endpoint can answer `{needs_worker_time: true}` and the UI
  prompts for a duration), and `create_direct` / `update_task` reject an
  assignee without an estimate. **Not** enforced by `Task.clean()`:
  auto-assign on a worker's first blep (`start_work` /
  `create_historical`) deliberately claims the task without demanding a
  duration mid-clock-in, so assignee-without-est-time is a legal state.
  Unassigning has no requirement.
- A Task with any Bleps must not be in `pending`. Validator-enforced.
- Task → terminal auto-closes any open Bleps (end_time := now).
- **Deletion (Rule 1)**: `TaskService.delete_task` refuses when the task is
  in-progress/complete, has bleps, is claimed by a **non-draft** estimate/CO,
  or is on a live invoice — "cancel it instead." Draft claims stay deletable
  (release them by removing the line/atoms first).
- All Tasks on a Job terminal → `TaskLifecycleService._check_job_work_complete`
  walks the Job toward `work_complete` (silent-fail on loose pending
  task-less Materials; see §2.6, §2.7).

---

### 1.12 Blep

Depends on: Task, User.

- **task** (required FK → Task, PROTECT). Two creation paths with
  different rules, both intentional:
  - **Live clock-in (`start_work`)**: task must be in `pending` or
    `in_progress`. `pending` is auto-promoted to `in_progress` before
    the blep is created (see §2.8).
  - **Retroactive entry (`create_historical`)**: no task-status
    precondition. Supports backdating bleps onto tasks that have
    since transitioned to `blocked`, `complete`, or `cancelled` (e.g.
    a worker forgot to clock in for work they did earlier today).
  - **Job-status precondition (both paths)**: the task's Job must be in
    a status where work belongs. Pre-approval work is permitted:
    `start_work` allows `draft`, `submitted`, `approved`, and
    `in_progress`; `create_historical` additionally permits
    `work_complete` and `cancelled` (the latter so forgotten time can be
    logged for billing under the stop-and-bill flow — see
    `invoicing-and-expenses.md`). Any other Job status (`rejected`,
    `completed`) is rejected with `ValidationError`, and a **held** job
    (`on_hold` flag) is rejected on both paths by an explicit check in
    `_assert_job_allows_blep`, ahead of the status allow-list.
- Steady-state invariant: a Blep's task is in `in_progress`, `blocked`,
  `complete`, or `cancelled` — never `pending`, because `start_work`
  promotes before creating and `create_historical` is only sensibly
  used after work has already happened. The validator can check this
  on fixtures.
- **user** (required FK → User, PROTECT) — a Blep always belongs to a worker;
  the column is `NOT NULL`. Every write path supplies one (`create_historical`
  defaults `target_user` to the actor; `start_work` uses `on_behalf_of or user`).
- **start_time**: datetime, nullable
- **end_time**: datetime, nullable. If set, must be ≥ start_time and not
  in the future — a non-null `end_time` more than 30s ahead of `now`
  (clock-skew buffer) is rejected on create and update. Setting `end_time`
  on an open Blep (e.g. via the edit modal) closes the session.
- An "open" Blep has `start_time` set and `end_time` null (work in progress)
- **No overlapping Bleps per user**: for any given User, no two Bleps (across
  all Tasks) may have overlapping time ranges. The app enforces this by
  closing the user's open Blep before creating a new one.
- Open Bleps are auto-closed (end_time set to now) when their Task transitions
  to `complete`, `cancelled`, or `blocked`.
- **Shift enclosure**: every Blep must be fully enclosed by a Shift of the same
  user (`shift.start <= blep.start and blep.end <= shift.end`). Bleps and
  Shifts relate by time overlap, not an FK. Enforced in the service layer; see
  §1.2a for the full invariant, the auto-clock-in / clock-out behaviour, and
  the backfill. Self-edit window for direct user blep edits is **30h** (matches
  the shift self-edit window — §1.2a).
- **Deletion (invoiced-task freeze)**: `BlepService.delete` refuses — for
  every actor, own-window or `can_manage_time` — when the blep's task is on a
  live invoice: billed actuals are frozen (deleting a blep under an invoiced
  ELAPSED_TIME task would change the basis of a charged number). Estimate
  claims never block (estimates bill `est_qty`).

---

### 1.13 Estimate (+ EstimateLineItem + EstimateLineItemSource)

Depends on: Job. EstimateLineItem dropped its direct `task` FK; source atoms
are joined via the polymorphic `EstimateLineItemSource` table.

#### Status machine

```
draft → open → accepted
             → superseded
             → rejected
             → expired
draft → rejected
```

Valid transitions:
- `draft` → `open`, `rejected`
- `open` → `accepted`, `superseded`, `rejected`, `expired`
- `accepted`, `rejected`, `expired`, `superseded` → (terminal)

#### Fields

- **job** (required FK → Job, CASCADE)
- **estimate_number**: max 50 chars. Generated via NumberGenerationService.
  `(estimate_number, version)` is unique together.
- **version**: integer, default 1
- **parent** (optional FK → self, SET_NULL): for version chains
- **Only one accepted estimate per job**: if status is `accepted`, no other
  Estimate for the same Job can be `accepted`. Enforced in `clean()`.
- **public_token** (`CharField(max_length=64, null=True, blank=True,
  unique=True)`): opaque token minted at creation (`secrets.token_urlsafe(32)`,
  ~43 chars) in `Estimate.save()` when `not self.pk and not self.public_token`.
  Unique across all Estimate rows. Nullable so the column is additive (existing
  rows backfilled by migration `0022`). Each revision row mints its own token.
  Backs the customer-portal URL (`/portal/?token=<token>`) — see
  `estimates-and-prices.md` §15.1. Never regenerated after creation.

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **sent_date**: auto-set to `now()` on transition to `open`. Immutable once
  set. Must be null for `draft`.
- **expiration_date**: auto-set to `now() + est_expire_days` on transition to
  `open` (reads from Configuration). Should be null for `draft`.
- **closed_date**: auto-set to `now()` on transition to `accepted`, `rejected`,
  `superseded`, or `expired`. Immutable once set. Must be null for `draft`.

#### Version chain rules

- Estimates sharing the same `estimate_number` form a version chain.
- All versions below the maximum must be in `superseded` status.
- Parent chain should link sequential versions: v2's parent = v1, v3's parent
  = v2.
- A `superseded` Estimate must be an earlier version of another Estimate with
  the same `estimate_number` — superseded estimates cannot exist in isolation.
- Timestamps must be chronologically ordered within a version chain: a
  superseded estimate's `created_date` and `closed_date` must be earlier than
  the next version's `created_date`.

#### Line item requirement

Cannot transition out of `draft` without at least one EstimateLineItem.
Enforced in `Estimate.clean()`.

#### EstimateLineItem

- **estimate** (required FK → Estimate, CASCADE)
- No `task` FK — `BaseLineItem.clean()`'s task/PLI mutual-exclusivity rule
  is skipped on subclasses lacking that field.
- **inventory_item** (optional FK → InventoryItem, PROTECT): set when the
  line bills a freeform PLI rather than a plan-side atom
- **adjustment_service** (optional FK → RateScheme, PROTECT): set when
  this line is a percentage adjustment. A line with `adjustment_service_id`
  set is an **adjustment line**; `adjustment_service.algorithm` must be
  `percentage`. Cannot coexist with `inventory_item`.
- **adjustment_target_categories** (M2M → AccountingCategory, blank):
  the categories the adjustment applies to. Empty = all non-adjustment lines.
  Must only be set when `adjustment_service` is set.
- **line_number**: auto-generated sequentially per estimate if null
- **units** (required, max 50 chars, default `'none'`): **non-blank** —
  `CharField` without `blank=True`, and `BaseLineItem.save()` always runs
  `full_clean()`, so `''` is rejected (`{'units': ['This field cannot be
  blank.']}`). A PLI-linked line backfills `units` from the PLI in
  `_populate_from_pli()`; a freeform line must carry its own (default `'none'`).
  This is a **BaseLineItem-wide** rule — it holds for InvoiceLineItem,
  PurchaseOrderLineItem, and ChangeOrderLineItem too. Empty-string
  units can therefore only exist as legacy/bulk-inserted rows that bypassed
  `save()`; the normal path can't produce them, and re-saving such a row (e.g.
  `revise_estimate` copying line items) will raise.
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)
- **accounting_category** (optional FK): null = silently tax-exempt;
  auto-populated from PLI when linked

#### EstimateLineItemSource

Polymorphic row joining a line item to a Job atom (Task, Material, or Fee).

- **estimate_line_item** (required FK → EstimateLineItem, CASCADE)
- **source_type**: `task`, `material`, or `fee`
- **source_pk**: integer pointing at the atom
- `unique_together = [('source_type', 'source_pk')]` — an atom can be
  referenced by at most one estimate line item, ever. On revision,
  `revise_estimate` **moves** the source rows to the new revision (rather
  than duplicating), so the live estimate is the one lens over the atom.
- The atom's `job` must match the line item's estimate's `job`
  (validator-enforced — `validate_data.check_estimate_source_job_consistency`;
  the invoice side has the parallel `check_invoice_source_job_consistency`).
  Fee atoms are validated by `validate_data.check_fees` (unit_rate > 0,
  accounting_category present, quantity ≥ 0, `task.job == fee.job`).

See `docs/designs/estimates-and-prices.md`.

---

### 1.13a ChangeOrder (+ ChangeOrderLineItem)

Depends on: Job, Estimate.

A customer-approved post-acceptance amendment to the agreed Estimate. `db_table = 'change_orders'`.

#### Status machine

Valid transitions (`ChangeOrder.VALID_TRANSITIONS`):
- `draft` → `open`, `rejected`
- `open` → `accepted`, `rejected`, `superseded`, `expired`
- `accepted`, `rejected`, `expired`, `superseded` → (terminal)

#### Fields

- **job** (required FK → Job, CASCADE)
- **estimate** (required FK → Estimate, PROTECT): the accepted Estimate this CO amends
- **change_order_number**: unique, max 80. Assigned in `save()` as `{estimate.estimate_number}-CO{n}` where `n` = count of COs on this estimate + 1. The `unique` constraint is the race backstop.
- **version**: integer, default 1
- **parent** (optional FK → self, SET_NULL): the prior CO this one was seeded from

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **sent_date**: auto-set to `now()` on transition to `open`. Immutable once set. Must be null for `draft`.
- **expiration_date**: auto-set to `now() + est_expire_days` on transition to `open` (shared with Estimate). Should be null for `draft`.
- **closed_date**: auto-set to `now()` on transition to `accepted`, `rejected`, `superseded`, or `expired`. Immutable once set. Must be null for `draft`.

#### Invariants

- **One live CO per job**: at most one ChangeOrder per Job in `draft` or `open`.
- **Create requires the hold flag**: `ChangeOrderService.create` raises `ValidationError` unless `job.on_hold` is set and the job has an `accepted` Estimate.
- **Line item requirement**: cannot transition out of `draft` without at least one ChangeOrderLineItem. Enforced in `ChangeOrder.clean()`.
- **AC send guard**: cannot transition `draft → open` while any bare `add` line (no `service_item`, no `inventory_item`) lacks an `accounting_category` — it crystallizes into a Fee / provisional Material at acceptance and the category must be pinned before the customer can accept. Enforced in `ChangeOrder.clean()`.
- **Release guard**: a held Job cannot be released (`JobService.release_job`) or cancelled while any of its COs is `draft` or `open`.
- **Acceptance clears the hold**: on transition to `accepted`, the handler drops the job's `on_hold` flag — the job resumes its true underlying status directly (held from `in_progress` goes straight back to `in_progress`).
- **Acceptance crystallizes atoms**: on transition to `accepted`, `ChangeOrderAcceptanceService.on_accept` applies the line deltas to the Job's atoms (add → Task/Material/Fee; remove/replace → retire the target's current atom) in the same transaction, after the hold is cleared (atom writes are blocked while held). See `estimates-and-prices.md` §14.11.

#### ChangeOrderLineItem

Inherits `BaseLineItem`. `db_table = 'co_li'`.

- **change_order** (required FK → ChangeOrder, CASCADE)
- **action** (CharField, required): one of `add`, `remove`, `replace`
- **target_line_item** (optional FK → EstimateLineItem, PROTECT): required for `remove` / `replace`; must be null for `add` (enforced by `clean()`)
- **inventory_item** (optional FK → InventoryItem, SET_NULL)
- **service_item** (optional FK → ServiceItem, PROTECT): deferred service descriptor; crystallizes to a Task at CO acceptance (mirrors `EstimateLineItem.service_item`)
- **is_material** (bool, default False): marks a bare line as crystallizing into an established Material (reverse-markup placeholder cost) instead of a Fee (mirrors `EstimateLineItem.is_material`); authoring rejects it alongside an `inventory_item`/`service_item` and applies the `default_material_accounting_category` config default
- `clean()` also rejects `service_item` / `is_material` on `remove` lines (display-only; never crystallize)
- No `task` FK — `BaseLineItem.clean()`'s task/PLI mutual-exclusivity rule is skipped on subclasses lacking that field.

#### ChangeOrderLineItemSource

`db_table = 'co_li_sources'`. The CO analog of EstimateLineItemSource (§ estimates doc §6.2/§14.4): polymorphic join from a ChangeOrderLineItem to the atom it crystallized at acceptance.

- **change_order_line_item** (required FK → ChangeOrderLineItem, CASCADE, `related_name='sources'`)
- **source_type**: `task` | `material` | `fee`; **source_pk**: positive int
- `unique_together (source_type, source_pk)` — an atom is claimed by at most one CO line
- Rows exist only for add/replace lines of accepted COs; purged when the referenced atom is deleted by a later CO's remove/replace.

See `docs/designs/estimates-and-prices.md`.

---

### 1.14 WorkTemplate / ServiceItem / TemplateTaskAssociation / TemplateMaterialAssociation

The template system used to populate Jobs with reusable task/material
structures.

#### WorkTemplate

- **template_name**: max 255 chars; **description**: text
- **base_price**: optional decimal
- **created_date**: auto-set
- Hard-deleted. Nothing in the system holds a back-reference to a
  WorkTemplate after it has populated a Job, so a delete cascades cleanly
  through its TemplateTaskAssociation and TemplateMaterialAssociation rows.

#### ServiceItem

- **template_name**: max 255 chars; **description**: text
- **rate_scheme** (required FK → RateScheme, PROTECT): default service
  price for generated Tasks. Superseded entries raise
  `SchemeSupersededError` from `generate_task()`. The template holds **no
  price** of its own — the price is always read from `rate_scheme.rate`.
- **default_active_modifiers**: JSON list of modifier keys (always a list,
  never a dict).
- **work_templates**: M2M via `TemplateTaskAssociation`
- **is_active**: boolean, default True — the soft-delete flag.
  `WorkTemplate.generate_tasks_for_job` filters associations by
  `service_item__is_active=True`, and the ServiceItem picker UI hides
  inactive entries. Soft-delete (not hard-delete) is the intended path so
  historical references to a retired ServiceItem are preserved.

#### TemplateTaskAssociation

- **work_template**, **service_item**: CASCADE FKs
- **est_qty**: decimal, default 1 (quantity passed to `generate_task()`)
- **sort_order**: integer, default 0
- `unique_together = ['work_template', 'service_item']`

#### TemplateMaterialAssociation

- **work_template** (FK → WorkTemplate, CASCADE)
- **inventory_item** (required FK → InventoryItem, PROTECT) — templates
  carry no freeform materials; everything goes through the PLI catalog
- **template_task_association** (optional FK → TemplateTaskAssociation,
  SET_NULL): if set, generated material attaches to the corresponding
  generated Task. `clean()` enforces this association belongs to
  the same WorkTemplate.
- **quantity** (required, decimal); **sort_order**: integer, default 0

---

### 1.15 Material

The Job's material atom; extends `MaterialBase` (abstract). (The plan-side
`PlanMaterial` was **removed** with the planning layer — there is one
material model, created directly on the Job.)

#### Shared fields (MaterialBase)

- **description**: max 255 chars, default ''
- **quantity**: decimal, default 0 (non-negative)
- **units**: max 50 chars, default 'none'
- **unit_cost**, **sell_price**: decimals, default 0
- **inventory_item** (optional FK → InventoryItem, SET_NULL)
- **accounting_category** (required FK → AccountingCategory, PROTECT)

On save, `_populate_from_pli()` fills `description`, `units`, `unit_cost`,
`sell_price`, `accounting_category` from the linked PLI. A PLI-linked
Material is effectively immutable for description/units/AC
(pricing carve-out — see `docs/designs/materials-inventory-and-purchasing.md`).
Either a description or a `inventory_item` must be present.

#### Material

- **job** (required FK → Job, CASCADE)
- **task** (optional FK → Task, SET_NULL): if null, the Material floats on
  the Job. `clean()` enforces `task.job == job` when both are set.
- **consumption_state**: `pending`, `consumed`, or `released`. Default
  `pending`. Flipped to `consumed` by `MaterialService.consume` (reversible via
  `unconsume`); to `released` (terminal) by `MaterialService.release` / the
  restock-to-zero rule — the "planned it, didn't use it" retirement (full
  restock while referenced, job-completion loose release, PO sever, CO
  descope). Every other lifecycle op requires `pending`.
- **released_qty** (renamed from `restocked_qty` 2026-07-03): decimal, default
  0, non-negative. Quantity restocked/released back out of the plan —
  universal, not just expense-bound. Invariant: `quantity + released_qty` =
  originally planned (release zeroes `quantity` into it, so released rows sum
  to zero in aggregates; the expense-void reversal reconstructs the purchase
  from the sum).
- **Deletion (Rule 1)**: a pending material that nothing references (no
  expense, no PO link, no estimate/CO claim, not invoiced —
  `MaterialService._is_referenced`) may hard-delete; referenced materials are
  released instead.
- **po_line_item** (optional FK → PurchaseOrderLineItem, SET_NULL)
- **cost_source**: `estimated` / `entered` / `po` / `expense` /
  `customer_supplied`, or **NULL**. Provenance enum answering "is this cost
  real?" and "who owns this?". **Invariant: `cost_source IS NULL` ⇔
  `inventory_item IS NULL`** — a material is *provisional* (no lot) exactly when
  it has no provenance, and *established* (lot-backed) exactly when it has one.
  `establish` sets it when it mints/attaches the lot. `po` overrides
  `estimated`/`entered` (sell price untouched). Set by service code only.
- **Provisional refusals**: a provisional material (`inventory_item IS NULL`)
  cannot be **consumed** (`consume` raises), **ordered**, or **marked on-hand** —
  all require a lot first.
- **Customer-supplied lock** (`cost_source == 'customer_supplied'`): born
  established at a deliberate, **locked $0** (`unit_cost = sell_price = 0`).
  `create_on_job` rejects a `customer_supplied` add that also carries an
  `inventory_item` or any non-zero `unit_cost`/`sell_price`; `update_fields`
  rejects any pricing edit (including sell) on a customer-supplied material. It
  is never ordered or expense-attached; arrival is via **Mark received**.

#### Implied state from other models

- A Material with an inventoried PLI landing on a Job triggers an Earmark
  upsert via `InventoryService._mutate_earmark(pli, job, +qty)`. See §2.6.
- Consume / Restock flip earmarks back via `_mutate_earmark(..., -qty)`.
- Job entering `work_complete` releases all remaining earmarks for the Job.
- **Deletion purges document claims**: `Material.delete()` (like
  `Fee.delete()` and `Task.delete()`) calls `purge_source_rows_for_atom`
  (`apps/estimates/claims.py`) — no `EstimateLineItemSource` /
  `ChangeOrderLineItemSource` / `InvoiceLineItemSource` row may outlive its
  atom, on any deletion path (restock-to-zero, PO sever, CO retirement, …).

---

### 1.16 Invoice (+ InvoiceLineItem + InvoiceLineItemSource)

Depends on: Job.

#### Status machine

Statuses: `draft`, `open`, `cancelled`, `superseded`, `partly-paid`, `paid`,
`defaulted`.

No explicit transition validation in `clean()`. The validator checks:
- Status must be a valid choice
- Invoice should not exist for `draft`/`submitted`/`rejected` jobs

A `cancelled` Job may carry `open` / `partly-paid` / `paid` Invoices: `CANCELLED` is in `BILLABLE_JOB_STATUSES`, so a job stopped early can still be billed for work done. The Unpaid board lane queries by outstanding-invoice rather than job status, keeping such jobs visible until their invoices clear (see `invoicing-and-expenses.md`).

#### Fields

- **job** (required FK → Job, CASCADE)
- **invoice_number**: unique, max 50 chars, **nullable** (2026-07-21). QBO
  owns invoice numbering: NULL on drafts; the first QBO push writes QBO's
  `DocNumber` back (retry sends backfill). Never generated konbini-side —
  the `'invoice'` NumberGenerationService pattern is retired. UI surfaces
  render the `display_number` property (`invoice_number` or
  `"Draft — {job_number}"`), never raw `invoice_number`.
- **created_date**: set on creation
- **sent_date**: nullable. Auto-set to `now()` by `Invoice.save()` on the
  `draft → open` transition (the send-to-customer step; mirrors `Estimate`), and
  left untouched thereafter. A row created directly as `open` (test/seed path) is
  not stamped. The serializer derives `due_date` (= `sent_date + 30 days`, the
  hard-coded `DEFAULT_INVOICE_NET_DAYS`, *not* PaymentTerms) and `is_late` from
  it — both are `null`/`false` while `sent_date` is null.
- **closed_date**: nullable. Auto-set to `now()` on transition to `paid`.
- **qbo_id**, **qbo_payment_status**, **qbo_amount_paid**: nullable QBO sync
  fields

> **Note:** Invoice has **no stored `due_date`** — it is computed on the fly in
> `InvoiceSerializer` and consumed by the SPA (InvoiceDetailPage's Due Date row +
> "(late)" flag, and JobDetail's late styling via `is_late`).

#### Line item requirement

Cannot transition out of `draft` without at least one InvoiceLineItem.
Enforced in `Invoice.clean()`.

#### InvoiceLineItem

- **invoice** (required FK → Invoice, CASCADE)
- No `task` FK — the `task` property returns `None` for
  `BaseLineItem.clean()` compatibility. Source atoms are joined via
  `InvoiceLineItemSource`.
- **inventory_item** (optional FK → InventoryItem, PROTECT)
- **adjustment_service** (optional FK → RateScheme, PROTECT): set when
  this line is a percentage adjustment. `adjustment_service.algorithm` must
  be `percentage`. Cannot be combined with `InvoiceLineItemSource` atom
  sources (an adjustment line has no source atoms).
- **adjustment_target_categories** (M2M → AccountingCategory, blank):
  the categories the adjustment applies to. Empty = all non-adjustment lines.
  Must only be set when `adjustment_service` is set.
- **line_number**: auto-generated sequentially per invoice if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)

#### InvoiceLineItemSource

Polymorphic row joining an `InvoiceLineItem` to its source atom (a Job
`Task`, `Material`, or `Fee`, or a material-less `Expense`).

- **invoice_line_item** (required FK → InvoiceLineItem, CASCADE)
- **source_type**: `task`, `material`, `fee`, or `expense`; **source_pk**: integer
- `unique_together = [('source_type', 'source_pk')]` — global. An atom can
  be billed by at most one Invoice line, ever. Prevents double-billing
  across invoice revisions.

---

### 1.17 PurchaseOrder (+ PurchaseOrderLineItem)

Depends on: Business, (optionally) Contact.

#### Status machine

```
draft → issued → partly_received → received_in_full
               ↘ received_in_full
               ↘ cancelled
```

Valid transitions (live):
- `draft` → `issued`
- `issued` → `partly_received`, `received_in_full`, `cancelled`
- `partly_received` → `received_in_full`, `issued`
- `received_in_full` → `partly_received`, `issued`
- `cancelled` → (terminal)

The model permits `received_in_full → partly_received` and
`received_in_full → issued` to undo accidental over-receipts. Only `cancelled`
is genuinely terminal.

#### Fields

- **business** (FK → Business, PROTECT, **nullable**): the vendor. Nullable so
  a draft can be created **vendor-less** (the Order-from-material flow spins up a
  draft PO before the supplier is known). **Required at issue** — `clean()`
  raises `{'business': ['A purchase order needs a vendor before it can be
  issued.']}` on any non-`draft` status with no business (unconditional; also
  blocks an update nulling the vendor on an issued PO). Vendor-less drafts are
  deleted, not cancelled, so there is no cancelled exemption.
- **contact** (optional FK → Contact, PROTECT): if set, contact must have a
  business. On creation, if both contact and business are provided, contact's
  business must match.
- **po_number**: unique, max 50 chars. Auto-generated via
  NumberGenerationService if not provided.
- If contact is provided on creation and business is not explicitly set,
  business is auto-populated from contact's business.

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **issued_date**: auto-set to `now()` on transition to `issued`. Immutable
  once set.
- **received_date**: auto-set to `now()` on transition to `received_in_full`.
  Immutable once set.
- **cancel_date**: auto-set to `now()` on transition to `cancelled`. Immutable
  once set.
- Non-draft POs should have `issued_date`.
- `received_in_full` POs should have `received_date`.
- `cancelled` POs should have `cancel_date`.

#### Deletion

Only `draft` POs can be deleted.

#### Line item requirement

Cannot transition out of `draft` without at least one PurchaseOrderLineItem.
Enforced in `PurchaseOrder.clean()`.

#### PurchaseOrderLineItem

No direct `job` FK; the link to a Job derives through the Material that the
line item ordered (`Material.po_line_item`).

- **purchase_order** (required FK → PurchaseOrder, CASCADE)
- **task** (optional FK → Task, PROTECT): reserved for a future
  "service PO" feature. No flow currently populates it; the field is
  null on every PO line. Defined directly on the subclass, not on
  `BaseLineItem`.
- **inventory_item** (optional FK → InventoryItem, PROTECT)
- **line_number**: auto-generated sequentially per PO if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)
- **qty_received**: decimal, default 0 (populated by receive actions)
- **qty_cancelled**: decimal, default 0 (replaces the old `cancelled` boolean)
- **received_by** (optional FK → User, SET_NULL); **received_date**: nullable
- **receipt_note**: text, default ''

---

### 1.18 Bill (+ BillLineItem, BillPayment) — retired 2026-07-23

Vendor invoices live entirely in QBO. `Bill`, `BillLineItem`, and
`BillPayment` remain in `apps/purchasing/models.py` as **schema-only stubs**
(kept to avoid a destructive migration; legacy rows may exist), but no
active code creates, mutates, or displays them, so they carry **no live
constraints** — the former status machine, date rules, payment recompute,
and line-item requirements are gone with the business logic. What persists:

- The **PROTECT FKs** from legacy rows (business, contact, purchase_order,
  BillLineItem → InventoryItem) still block unsafe deletes of their targets
  — see the Contact deletion rule (§1.5), the business-delete impact counts,
  and `InventoryItem.has_document_line_refs`.
- `EmailRecord.bill` (§1.27) is a legacy-only column; the email API no
  longer exposes `bill` / `vendor_invoice_number`.

See `materials-inventory-and-purchasing.md` §13 for the full retirement
record. Vendor-invoice emails now link to the **PurchaseOrder** instead.

---

### 1.19 Earmark

Depends on: InventoryItem, Job.

A per-PLI-per-Job aggregate row representing the inventory committed to a
Job. There is exactly one row per `(inventory_item, job)`; quantity reflects
the running sum of Material commitments minus consumption/restock.

- **inventory_item** (required FK → InventoryItem, CASCADE): PLI should be
  inventoried (`is_inventoried=True`); a non-inventoried PLI never reaches
  `_mutate_earmark`
- **job** (required FK → Job, CASCADE)
- **quantity**: must be positive (> 0). Rows with `quantity <= 0` are deleted
  by `_mutate_earmark`. Warn if quantity exceeds PLI's `qty_on_hand`.
- `unique_together = [('inventory_item', 'job')]`
- `InventoryService._mutate_earmark` is the SOLE writer. Direct
  `Earmark.objects.create` calls outside that method (or
  `release_earmarks_for_job`) violate the invariant.
- Warn if job is in terminal state (`work_complete`, `completed`, `cancelled`,
  `rejected`) — inventory should have been consumed or released by then.

#### Implied state from other models

- For every `pending` Material on a Job with an inventoried PLI, the Earmark
  for `(pli, job)` reflects the committed quantity. Consume / Restock /
  Job → work_complete are the only legitimate ways to draw the earmark
  back down.

See §2.6 and `docs/designs/materials-inventory-and-purchasing.md`.

---

### 1.20 InventoryAdjustment

Depends on: InventoryItem.

- **inventory_item** (required FK → InventoryItem, CASCADE): warn if PLI is
  not inventoried
- **quantity_change**: decimal (can be positive or negative)
- **reason**: text, default ''
- **created_date**: auto-set on creation

---

### 1.21 Expense

Depends on: User (entered_by, purchased_by), AccountingCategory,
(optionally) Material, (optionally) Reimbursement.

A reported business expense — either company-paid (from a known account) or
personal (subject to reimbursement). The optional `material` FK is the
bridge that turns a real-world receipt into a Job-charged Material line.

- **entered_by** (required FK → User, PROTECT): recorder
- **purchased_by** (optional FK → User, PROTECT): actual purchaser; required
  for personal
- **amount** (required, decimal(10,2)); **purchased_on** (required, date)
- **description**: text, default ''
- **accounting_category** (required FK → AccountingCategory, PROTECT)
- **payment_method**: `company` or `personal`
- **payment_account_id**: max 50 chars, blank by default. Required for
  company; forbidden for personal (enforced by `clean()`).
- **reference_number**: max 50 chars, blank by default
- **material** (optional FK → Material, SET_NULL)
- **status**: `submitted`, `reimbursed`, `rejected`, `synced`, `sync_failed`
- **qbo_id** / **qbo_sync_error**: QBO sync fields
- **reimbursement** (optional FK → Reimbursement, PROTECT): set when a
  personal expense has been batched

See `docs/designs/invoicing-and-expenses.md` for the submit/reimburse/sync
flow.

---

### 1.22 Reimbursement

Depends on: User (purchased_by, created_by).

Batch payout to a user for one or more personal Expenses.

- **purchased_by** (required FK → User, PROTECT): the user being reimbursed
- **paid_on** (required, date)
- **payment_account_id** (required, max 50 chars): the account the payout
  was drawn from
- **reference_number**: max 50 chars, blank
- **notes**: text, default ''
- **created_by** (required FK → User, PROTECT)
- **status**: `pending`, `synced`, `sync_failed`
- **qbo_id** / **qbo_sync_error**: QBO sync fields

Personal Expenses point at a Reimbursement via `Expense.reimbursement`.
`Reimbursement.total` sums the linked expenses.

---

### 1.23 Deliverable

Depends on: Job.

A finished item the customer is buying on a Job. No price; only quantity,
units, and a free-text description. The Deliverables list is the
customer-facing manifest distinct from billing line items.

- **job** (required FK → Job, CASCADE)
- **description** (required, text)
- **qty_ordered** (required, decimal(10,2)): customer-agreed quantity.
  Changes via direct edit of the live list (pre-send) or via the
  draft-CO edit-in-place flow. Anchored once shipped (see below).
- **units** (required, max 50 chars): drawn from `Configuration['units_list']`
- **sort_order** (PositiveInteger): auto-assigned to next slot on save when
  unset (10, 20, 30, …). Renumbered to a contiguous sequence after a
  service-driven delete.
- **created_at** / **updated_at**: timestamps.
- `db_table = 'deliverables'`. Default ordering: `sort_order`.

**Editability** — computed from the Job's estimate / change-order state, not stored:

- **Editable** when no estimate exists, the latest non-terminal estimate is
  `draft`, OR a ChangeOrder on the job is `draft` (the CO edit-in-place window).
- **Read-only** when the latest active estimate is `open`, an accepted estimate is the agreement of record with no live CO, or a CO is `open`.
- **Anchored** rows — Deliverables with any `ShipmentItem` — are **never** editable or removable, regardless of the surrounding state. `DeliverableService.update` / `delete` reject the operation. Once any of the deliverable's quantity ships, the row is frozen at `qty_ordered` for the life of the job.
- Enforced by `DeliverableService._assert_editable(job)` for state checks; create / update / delete / reorder all raise `ValidationError` outside the editable state.

**Constraint**: `qty_ordered > 0` (validated by service when supplied via
API; not a DB constraint).

See `docs/designs/jobs-tasks-and-worksheets.md` for the workflow and §2.12
below for the estimate-send guard.

---

### 1.24 Shipment (+ ShipmentItem)

Depends on: Job (Shipment); Shipment + Deliverable (ShipmentItem).

A fulfillment event for a Job. Multiple Shipments per Job support phased
delivery / backorders. A Shipment is identified by a per-Job `sequence`
counter (no global document number).

#### Shipment

- **job** (required FK → Job, CASCADE)
- **sequence** (required PositiveInteger): per-Job counter assigned by
  `ShipmentService.create` as `max(existing.sequence) + 1` or 1.
- **status**: `prepared` (default) → `picked_up`. Terminal at `picked_up`;
  no reverse transition.
- **prepared_date** (default `now()`): set on create
- **picked_up_date** (nullable): set by `ShipmentService.mark_picked_up`
  when status flips
- **notes** (blank text)
- **created_at** / **updated_at**: timestamps.
- `db_table = 'shipments'`. `unique_together = [('job', 'sequence')]`.
  Default ordering: `sequence`.

**Constraints:**

- A Shipment can only be created when the Job has at least one estimate in
  `accepted` status. Enforced in `ShipmentService.create`; the model has no
  guard.
- A Shipment in `picked_up` status is read-only: no edits, no item changes,
  no deletion.
- A `prepared` Shipment can only be deleted if `shipment.items` is empty.
  The UI's "Discard shipment" flow removes items first, then deletes the
  shipment.
- If `status == 'picked_up'`, `picked_up_date` must be set. If
  `status == 'prepared'`, `picked_up_date` must be null.

#### ShipmentItem

- **shipment** (required FK → Shipment, CASCADE)
- **deliverable** (required FK → Deliverable, PROTECT)
- **qty** (required, decimal(10,2)): contribution this shipment makes
  toward the parent Deliverable.
- `db_table = 'shipment_items'`.
  `unique_together = [('shipment', 'deliverable')]` — one row per
  (Shipment, Deliverable) pair.
  Default ordering: by parent Deliverable's `sort_order`.

**Constraints:**

- `qty > 0` (validated by service).
- For each Deliverable, the sum of `qty` across all `ShipmentItem` rows
  that point at it must not exceed `Deliverable.qty_ordered`. Validated in
  `ShipmentService.add_item` / `update_item` via
  `_validate_qty_bounds(deliverable, …)`. The bound check counts items
  across all Shipments regardless of shipment status — committed inventory
  cannot exceed ordered quantity.
- Items may not be created, updated, or deleted on a `picked_up` Shipment.

**Defense-in-depth**: `Deliverable` PROTECT on `ShipmentItem.deliverable`
makes it impossible to remove a Deliverable that any Shipment references.
This is the anchoring invariant from the database side — see §1.23.

See `docs/designs/jobs-tasks-and-worksheets.md` for the full
fulfillment workflow.

---

### 1.24a DeliverableSnapshot

Depends on: Estimate **or** ChangeOrder (exactly one), Deliverable.

Immutable, write-once frozen copy of a Deliverable's agreed scope at the moment a document was finalized.

- **estimate** (optional FK → Estimate, CASCADE)
- **change_order** (optional FK → ChangeOrder, CASCADE)
- **version** (PositiveInteger): display ordinal (1 = Estimate; 2.. = successive COs on that estimate)
- **description** / **qty_ordered** / **units** / **sort_order**: mirror `Deliverable` at snapshot time
- **source_deliverable** (optional FK → Deliverable, SET_NULL): traceability to the live row copied from
- **created_at**: auto-set
- `db_table = 'deliverable_snapshots'`. Default ordering: `sort_order`.

**Constraints:**

- Exactly one of `estimate` / `change_order` set. Enforced by `DeliverableSnapshot.clean()`.
- A document has at most one snapshot set. `DeliverableService.snapshot_document` short-circuits if any snapshot already exists for that document.
- Snapshots are never edited or deleted by application code.

See `docs/designs/jobs-tasks-and-worksheets.md` §12.9.

---

### 1.25 QBOConnection

Standalone. One active row at a time (singleton-ish — uniqueness enforced
in the application, not the schema). See
`docs/designs/quickbooks-integration.md` for the OAuth lifecycle.

- **realm_id** (max 50 chars)
- **access_token** / **refresh_token**: TextField
- **access_token_expires_at** / **refresh_token_expires_at**: required
  datetimes
- **is_active**: boolean, default True. At most one row should have
  `is_active=True`. The active connection's `refresh_token_expires_at` must
  be in the future for sync to succeed.
- **connected_at** (required datetime); **last_sync_at** (nullable)

---

### 1.26 QBOSyncLog

Append-only audit trail of sync operations. No invariants beyond schema.

- **entity_type** (e.g. `invoice`, `expense`; historical rows retain retired
  types — `bill`, `bill_payment`, `vendor`); **entity_id** (int)
- **qbo_entity_type** / **qbo_entity_id** (max 50 chars, blank)
- **action** (e.g. `create`, `update`); **status** (e.g. `success`,
  `failure`)
- **error_message**: text, blank
- **synced_at**: auto-set on creation

### 1.27 EmailRecord

Permanent record of an email and which entities (if any) it is
associated with. Inbound (IMAP-fetched) and outbound (sent by this
system) both live here, distinguished by `direction`.

- **message_id**: unique, max 255 chars (RFC 5322 Message-ID). For
  outbound, generated by us as `<minibini-<uuid4>@<our_domain>>`.
- **direction**: `'inbound'` (default) or `'outbound'`.
- **sent_at**: nullable DateTime. Outbound-only meaningful: set when
  SMTP succeeded, null when the send is pending or its last attempt
  failed. Always null for inbound.
- **last_send_error**: text, blank default. Outbound-only meaningful:
  populated with the SMTP exception's message after a failed attempt,
  cleared on a successful send.
- **job** (optional FK → Job, `on_delete=SET_NULL`)
- **purchase_order** (optional FK → PurchaseOrder, `on_delete=SET_NULL`)
- **bill** (optional FK → Bill, `on_delete=SET_NULL`): **legacy-only**
  since the 2026-07-23 bill retirement — no active code sets or exposes it
  (the email API no longer serializes `bill` / `vendor_invoice_number`);
  vendor-invoice emails link to the PO instead
- **created_at**: auto-set on creation

The associations are not exclusive: a single email can
simultaneously link to a Job (e.g. the customer thread it relates to)
and a PO (the vendor quote it spawned, or the vendor invoice for it).
Deleting any of the target entities clears that FK; the
EmailRecord itself persists.

Outbound rows are created at send time by
`OutboundEmailService.send_tracked` and the per-document services
that wrap it (EstimateEmailService, PurchaseOrderEmailService,
InvoiceEmailService). Retry reuses the most recent failed outbound
row for the same target, preserving its `message_id`.

The three association FKs propagate within a thread when set: any
link / create / correlate-reply path that sets a non-null FK on an
EmailRecord also copies that FK to every other EmailRecord in the
same RFC 5322 thread whose value for the same field is currently
null. Pre-existing differing values are not overwritten. The
association FKs are therefore not strictly per-email invariants —
they're effectively per-thread, set per-email and propagated. See
`architecture-and-conventions.md` §7.11a for the mechanism.

Body, metadata, and threading headers live on the related `TempEmail`
row (see `architecture-and-conventions.md` §7.7 / §7.10 / §7.11);
they are not part of the EmailRecord invariants.

### 1.27a TempEmail additions for outgoing + threading

(See `architecture-and-conventions.md` §7.7 for the inbound caching
story.) Additional columns supporting outbound and reply correlation:

- **bcc_email**: text, blank default. Populated only on outbound
  TempEmail rows — inbound IMAP fetches can't see BCC.
- **in_reply_to**: max 255 chars, blank default. RFC 5322 In-Reply-To
  header, captured at fetch time for inbound. Used by
  `EmailService.correlate_reply` to look up the immediate parent.
- **references**: text, blank default. RFC 5322 References chain,
  space-separated. Walked right-to-left when In-Reply-To doesn't
  match anything we know about.

---

## Section 2: State Reconciliation (Side Effects)

These are things the application does automatically when one object changes,
affecting other objects. A translation script must replay these after creating
all objects in Section 1 to ensure cross-model consistency.

Work through these in order — later rules may depend on earlier ones.

---

### 2.1 Estimate sent → Job submitted

**Trigger:** Estimate status changes to `open` (sent to customer).

**Effects:**
- Job status transitions from `draft` → `submitted`.
- Does NOT affect Jobs already in `submitted` or later status.

**Data constraint:** If any Estimate for a Job is `open` or later, the Job must
be `submitted` or later (never `draft`).

Implemented in `Estimate._maybe_update_job_status()` which fires
`estimate_status_changed_for_job` with `Job.STATUS_SUBMITTED` on the
`draft` → `open` transition.

---

### 2.2 Estimate accepted → Job approved

**Trigger:** Estimate status changes to `accepted`.

**Effects:**
- Job status transitions from `submitted` → `approved`.
- Job's `start_date` is set to `now()` on the `approved` transition (if not
  already set).
- Does NOT affect Jobs already in `completed` or `cancelled` status.

**Data constraint:** If an Estimate is `accepted`, its Job must be `approved`,
`in_progress`, `work_complete`, `completed`, or `cancelled`.

---

### 2.3 Estimate accepted → hand-lines crystallized into Fees

**Trigger:** Estimate status changes to `accepted`; the `estimate_accepted`
signal calls `EstimateAcceptanceService.on_accept(estimate)`.

**Effects** (the work already lives on the Job — Tasks/Materials were
created directly — so nothing is "carried over"):
- For each `EstimateLineItem` with **no source row** (a hand-line) that is
  not a percentage adjustment → create a `Fee` on the Job (`description`,
  `quantity = qty or 1`, `unit_rate = price or 0`, `accounting_category`,
  `sort_order = line_number`) and record an `EstimateLineItemSource`
  (`source_type='fee'`) back to it.
- Atom-backed lines (Task/Material sources) are skipped.
- `InventoryService.create_earmarks_for_job(job)` earmarks the job's
  inventoried materials.

**Data constraint:** Every hand-authored line on an `accepted` Estimate
should have a corresponding `Fee` on its Job, claimed by a `fee` source
row. Because the crystallized line becomes source-backed, re-firing the
signal does not duplicate Fees.

See `docs/designs/estimates-and-prices.md` §9 and
`apps/estimates/acceptance.py`.

---

### 2.4 ~~Estimate status change → EstWorksheet status update~~ (removed)

> **Removed** with the planning layer. There is no worksheet to update; the
> `estimate_status_changed_for_worksheet` signal was deleted. Estimate
> editability now derives from the live estimate's own status.

---

### 2.5 Job auto-completion gate (all invoices resolved + all deliverables shipped)

**Triggers:**
- An Invoice transitions to `paid` — `Invoice._maybe_complete_job` runs, delegating to `JobService.maybe_complete_if_resolved`.
- A Shipment transitions to `picked_up` — `ShipmentService.mark_picked_up` calls `JobService.maybe_complete_if_resolved`.

**Effects** (gate runs only when **both** conditions hold):

1. **All invoices resolved** — every `Invoice` for the Job is `paid` or `cancelled`.
2. **All deliverables shipped** — `DeliverableService.all_deliverables_shipped(job)` returns True, i.e. every `Deliverable`'s `qty_picked_up == qty_ordered`. Prepared-but-not-picked-up does not count. A job with zero deliverables is vacuously shipped.

A third precondition guards both: the Job's **work must be finished** — `work_complete`, or `approved`/`in_progress` with at least one Task and every Task terminal (the loose-material-stranded case). When all hold, the handler releases any loose pending Materials (claimed → `released` history, unclaimed → deleted; a `HistoryEntry` records the release) and walks the state machine up to `completed` (each step via `JobService.update_job`). Jobs with open Tasks, task-less jobs (a deposit invoice paid before work starts), and `draft`/`submitted` jobs are a no-op; a held job never auto-completes either — status changes are blocked while the `on_hold` flag is set. Job's `completed_date` is set to `now()`. A `HistoryEntry` of `entry_type='action'` attributed to `system` records the auto-complete.

Manual `JobService.update_job(status=completed)` enforces the all-shipped precondition independently and raises `ValidationError('All deliverables must be shipped before completing the job.')` otherwise.

`cancelled` jobs are exempt — the state machine forbids `cancelled → completed`, so neither trigger advances them.

**Data constraint:** Whenever a Job is `completed`, all of its Invoices must be `paid`/`cancelled` AND all of its Deliverables must be fully picked up. Whenever a Job has all invoices resolved AND all deliverables picked up, it must be `completed` (or `cancelled`) with `completed_date` set.

Implemented in `JobService.maybe_complete_if_resolved` (`apps/jobs/services.py`), reached from `Invoice.save()._maybe_complete_job` and `ShipmentService.mark_picked_up`.

---

### 2.6 Inventoried Material on Job → Earmark created

**Trigger:** A Material with an inventoried `inventory_item` is created on a
Job — via any path (Work-surface add, template populate, PO line
creation, expense submission).

**Effects:**
- `MaterialService.create_on_job` calls
  `InventoryService._mutate_earmark(pli, job, +qty)`.
- The Earmark row for `(pli, job)` is upserted: existing rows are
  incremented; missing rows are created with `quantity = qty`.

**Data constraint:** For every `pending` Material with an inventoried PLI on
a Job, the Earmark for `(pli, job)` reflects the sum of outstanding
quantities. Earmarks are released by `MaterialService.consume`
(decrements by Material.quantity, flips state to `consumed`),
`MaterialService.restock` (decrements by restocked qty), and by
`JobService.update_job` on entry to `work_complete`, `cancelled`, or
`rejected` → `InventoryService.release_earmarks_for_job(job)` (deletes all
remaining earmarks for the Job).

See `docs/designs/materials-inventory-and-purchasing.md`.

---

### 2.7 Work starts → Job auto-advance to in_progress / work_complete

**Trigger:** A Task on a Job transitions to `complete` or `cancelled`; or
work starts (a Blep is opened via `start_work` / `create_historical`).

**Effects:**
- `JobService.mark_work_started(job)` advances an `approved` Job to
  `in_progress` whenever work starts on it (a Blep is created, or a Task is
  completed). No-op for any other status. So completing one Task of several
  moves an `approved` Job to `in_progress`.
- `TaskLifecycleService._check_job_work_complete` then checks whether ALL
  Tasks on the Job are terminal (`complete` or `cancelled`). If yes and the
  Job is `approved` or `in_progress`, it walks through
  `approved → in_progress → work_complete` (skipping `approved → in_progress`
  if already past). Entering `work_complete` releases all remaining earmarks
  (via §2.6).

**Silent-fail guard:** if `JobService._loose_pending_materials(job)` finds
task-less, `pending`, positive-quantity Materials on the Job, the
auto-advance catches the `ValidationError` raised by `update_status` and
the Job stays put. The task completion itself still succeeds. The explicit
`update_status` path surfaces the error.

**Data constraint:** A Job in `work_complete` (or later) must have ALL Tasks
terminal. The converse does NOT hold — a Job with all-terminal Tasks may
still be `in_progress` if loose pending Materials block auto-advance.

Implemented in `apps/jobs/services.py`.

---

### 2.8 Blep started on pending Task → Task in_progress

**Trigger:** `start_work` (or `start_task`) is called on a `pending` Task.

**Effects:**
- Task transitions from `pending` → `in_progress`.
- A Blep is created on the Task with `start_time` set to `now()`.
- Any other open Blep the user has (on any task) is closed.
- Pending Materials on the Task may be auto-consumed (see jobs-tasks doc).
- If the Job is `approved`, it advances to `in_progress` (see §2.7).

**Data constraint:** A Task's first Blep `start_time` should coincide with or
follow the Task's transition out of `pending`. If a Task is `in_progress`,
all Bleps on it must have `start_time` at or after the moment the Task
entered `in_progress`.

---

### 2.8a Work starts → Shift auto-opened; clock-out → open Bleps closed

**Trigger:** `start_work` opens a live Blep / `ShiftService.clock_out` runs.

**Effects:**
- On `start_work`, if the worker has no open Shift, one is opened with
  `start_time = now` (`ShiftService.ensure_open_shift`). This guarantees the
  new Blep is enclosed (§1.2a).
- On clock-out, the worker's open Bleps are closed (`end_time = now`) first,
  then the open Shift's `end_time` is stamped — so clock-out never strands an
  unenclosed open Blep.

**Data constraint:** A worker with an open Blep must have an open Shift that
started at or before the Blep. A closed Shift must enclose every Blep of that
user whose span overlaps it.

---

### 2.9 Task terminal → open Bleps closed

**Trigger:** A Task transitions to `complete`, `cancelled`, or `blocked`.

**Effects:**
- All Bleps on that Task with `end_time=null` get `end_time` set to `now()`.

**Data constraint:** A Task in terminal state (`complete` or `cancelled`)
should have no open Bleps (Bleps with null `end_time`). A `blocked` Task
should also have no open Bleps.

---

### 2.10 Estimate version chain → supersession

**Trigger:** A new version of an Estimate is created.

**Effects:**
- The previous version's status is set to `superseded`.
- The previous version's `closed_date` is set.
- The new version's `parent` FK points to the previous version.
- Each line's `EstimateLineItemSource` rows are **moved** onto the new
  revision (the live revision is the one lens over the job atoms).

**Data constraint:** In a version chain (same `estimate_number`), all versions
below the maximum must be `superseded` with a `closed_date` set.

---

### 2.11 ~~EstWorksheet version chain → supersession~~ (removed)

> **Removed** with the planning layer. Worksheets had no version chain in
> the final pre-removal design and the model is now gone entirely. The
> estimate keeps its own version chain (§2.10).

---

### 2.12 Estimate mark_open → Deliverables non-empty guard

**Trigger:** `EstimateService.mark_open(estimate_pk)` is called to transition
an Estimate from `draft` to `open`.

**Effects:**
- If the Job has zero `Deliverable` rows, `ValidationError` is raised and
  no state changes.
- Otherwise the transition proceeds normally (Estimate goes `open`, signal
  walks the Job through `draft → submitted` if needed).

**Data constraint:** Every `open` (or `accepted` / `superseded` / `rejected`
that was previously `open`) Estimate must have a Job with at least one
Deliverable. A `draft` Estimate may exist without Deliverables.

---

### 2.13 Shipment pick-up → picked_up_date set

**Trigger:** `ShipmentService.mark_picked_up(pk)` is called on a `prepared`
Shipment.

**Effects:**
- `Shipment.status` transitions `prepared → picked_up`.
- `Shipment.picked_up_date` is set to `now()`.
- The Shipment and its `ShipmentItem` rows become read-only.

**Data constraint:** A Shipment in `picked_up` status must have
`picked_up_date` set. A Shipment in `prepared` status must have
`picked_up_date` null.

---

### 2.14 RateScheme supersession

**Trigger:** `RateScheme.supersede(**overrides)` is called.

**Effects:**
- The old row is renamed to `"<orig> (v{N})"` where N is the chain depth.
- A new row is created inheriting all fields from the old one (with any
  overrides applied), under the original name.
- The old row's `replaced_by` is set to the new row; `replaced_at` is set
  to `now()`.

**Data constraint:** A RateScheme with `replaced_by` set must have
`replaced_at` set, and vice versa. Templates referencing a superseded
entry should be updated to point at the new entry; otherwise
`generate_task()` raises `SchemeSupersededError`.

---

## Section 3: History Generation

HistoryEntry records the audit trail via generic refs (no real FKs), created
as side effects of object operations.

### HistoryEntry structure

- **entry_type**: `audit` (field changes), `action` (system status
  transitions), `note` (user-written text)
- **object_type**: string identifier (e.g. `job`, `estimate`, `contact`,
  `business`, `inventoryitem`, `invoice`, `purchaseorder`; historical rows
  may carry `bill` — retired 2026-07-23)
- **object_id**: integer PK of the referenced object
- **user** (FK → User, nullable): `audit` → acting user; `action` →
  `system` user; `note` → authoring user
- **timestamp**: auto-set on creation
- **changes**: JSON. For `audit`: `{field: {old, new}, ...}` plus optional
  `_created: true`. For `action`: includes `_action` description string.
- **text**: human-entered text (notes only). Empty for `audit`/`action`.

### What generates history

`@history`-decorated models: Contact, Business, Job, Estimate, ChangeOrder,
Invoice, PurchaseOrder, Shift, ShiftChangeRequest, BlepChangeRequest.
(Bill's decorator was removed with the 2026-07-23 retirement; its old
entries remain.)
The decorator creates `audit` entries on create and update.

Signal handlers create `action` entries (as `system` user) for:
- Job status changes triggered by Estimate acceptance
- Job status changes triggered by last-invoice-paid (§2.5)

### Generating realistic history for test data

After all objects and states are reconciled:

1. **Creation entries** — one `audit` entry per `@history` object with
   `_created: true`, timestamped at `created_date`.
2. **Status transition entries** — one `action` entry per transition,
   timestamped between `created_date` and any terminal date.
3. **Signal-driven entries** — accepted Estimates: record the
   `draft → submitted → approved` walk on the Job as `system`. Auto-completed
   Jobs (§2.5): record `approved → in_progress → work_complete → completed`
   as `system`.
4. **Notes** (optional) — user-written content on jobs, contacts, businesses.
