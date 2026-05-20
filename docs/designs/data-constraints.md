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

### 1.1 Configuration

Key-value store. No FK dependencies.

- **key** is the primary key (unique, max 100 chars)
- **value** is a text field, always stored as a string even for numeric values

Required keys for document numbering (each entity type needs both):
- `job_number_sequence` / `job_counter`
- `estimate_number_sequence` / `estimate_counter`
- `invoice_number_sequence` / `invoice_counter`
- `po_number_sequence` / `po_counter`

Sequence values use Python format placeholders: `{year}`, `{month:02d}`,
`{day:02d}`, `{counter:04d}`. Counter values are string-encoded integers.

Additional keys: `email_retention_days`, `latest_email_date`,
`email_display_limit`, `est_expire_days`.

---

### 1.2 User

Django `AbstractUser`. No Minibini-model dependencies (optional `contact` FK is
set later).

- Standard Django user fields apply (username unique, etc.)
- **contact** (optional OneToOne → Contact): set after Contacts exist
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

### 1.3 AccountingCategory

Standalone. No FK dependencies.

- **code**: unique, max 20 chars (e.g. "SVC", "MAT")
- **name**: max 100 chars
- **taxable**: boolean, default True
- **is_active**: boolean, default True (soft delete)
- **qbo_item_id** / **qbo_expense_account_id**: optional, populated after
  connecting QBO

---

### 1.4 PaymentTerms

Standalone. No FK dependencies.

- **term_id**: auto primary key
- No additional business constraints beyond DB schema

---

### 1.5 Business and Contact

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
- **business_name**: required, max 255 chars
- **qbo_customer_id** / **qbo_vendor_id**: nullable, for QBO sync
- **tax_multiplier**: nullable decimal; null/1.0 = full rate, 0 = exempt,
  0.5 = half rate

#### Contact

- **email**: required, must be non-empty and valid
- **At least one phone number**: one of `work_number`, `mobile_number`,
  `home_number` must be non-empty
- **first_name** / **last_name**: required (max 100 chars each)
- **business** (optional FK → Business): if set, `qbo_customer_id` must be null
  (mutual exclusivity — contacts with a business use the business's QBO ID)
- **Deletion blocked** if contact is the sole contact for a business (the
  business would lose its required `default_contact`)

---

### 1.6 PriceListItem

Depends on: AccountingCategory.

- **code**: unique, max 50 chars. No duplicates allowed.
- **accounting_category** (required FK → AccountingCategory): a missing
  category should be impossible at the DB level. `validate_data.py` still
  warns on null to catch corrupt fixtures.
- **purchase_price**, **selling_price**: non-negative decimals
- **qty_on_hand**, **qty_sold**, **qty_wasted**: non-negative decimals
- **is_inventoried**: boolean. If false, all quantity fields should be 0.
- **is_active**: boolean, default True (soft delete)
- **Deletion blocked** if referenced by any line item, earmark, or adjustment

---

### 1.7 RateScheme

Depends on: AccountingCategory.

Describes how a Task/PlanTask/TaskTemplate's billable amount is computed.
Once any atom references a scheme, it is effectively immutable; edits must
go through `supersede()`, which forks a new scheme and renames the old row.
See `docs/designs/estimates-and-prices.md` for algorithm/modifier semantics.

- **name**: required, unique, max 100 chars. `supersede()` renames the old
  row to `"<name> (v{N})"` before creating the new one to preserve the
  DB-level unique constraint.
- **algorithm**: one of `elapsed_time`, `entered_qty`, `flat_fee`
- **rate**: decimal(10,2)
- **unit_label**: max 50 chars
- **modifiers**: JSON list of `{key, label, percent}` dicts (default `[]`)
- **accounting_category** (required FK → AccountingCategory): `clean()`
  raises if missing
- **replaced_by** (optional FK → self) / **replaced_at**: set by `supersede()`

For `flat_fee` schemes, `rate` is only a fallback — the real per-unit price
lives on each atom / `TaskTemplate` in `active_modifiers` as
`{"flat_fee_price": str}`, and the billable quantity comes from `est_qty`.
See `estimates-and-prices.md` §2.2.

#### Frozen fields

Once any PlanTask, Task, or TaskTemplate references a scheme, the fields
`name`, `description`, `algorithm`, `rate`, `unit_label`, `modifiers`, and
`accounting_category` are frozen (`FROZEN_FIELDS`). `clean()` rejects edits.
The only legitimate mutations on a referenced scheme are
`replaced_by`/`replaced_at` and the in-place rename `supersede()` does on
its predecessor. If `replaced_by` is set, `replaced_at` must also be set,
and vice versa. Templates pointing at a superseded scheme raise
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
WorkOrder was removed). `work_complete` = all tasks terminal and earmarks
released. `completed` = fully closed (typically: all invoices paid).

#### Fields

- **job_number**: unique, max 50 chars. Generated via NumberGenerationService
  (pattern from Configuration). Only generated for new instances.
- **contact** (required FK → Contact, PROTECT)
- **status**: must be one of the choices above, default `draft`
- **name** / **description** / **customer_po_number**: optional text

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **start_date**: auto-set to `now()` on transition to `approved`. Immutable
  once set. Should be null for `draft`/`submitted`/`rejected`.
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
- All Invoices for a Job `paid`/`cancelled` → Job must be `completed`
  (`Invoice._maybe_complete_job()`).
- Job `cancelled` → all Invoices for the Job must be `cancelled`.

See `docs/designs/jobs-tasks-and-worksheets.md` for the loose-pending-material
guard on `in_progress → work_complete`.

---

### 1.9 EstWorksheet

Depends on: Job, (optionally) Estimate, WorkTemplate.

#### Status machine

No explicit transition validation in `clean()`. Status is driven by Estimate
status changes (see implied state and §2.4).

Statuses: `draft`, `final`, `superseded`.

#### Fields

- **job** (required FK → Job)
- **estimate** (optional FK → Estimate, SET_NULL): if set, the worksheet was
  used to generate that estimate
- **version**: integer, default 1. Must be unique per job when combined with
  parent chain.
- **parent** (optional FK → self, SET_NULL): if set, parent must belong to the
  same Job and have a lower version number. Parent should be in `superseded`
  status.
- **created_date**: set on creation

#### Implied state from other models

- If **estimate** is set and estimate status is `draft` → worksheet status
  is `draft` (worksheet and estimate are edited together until the
  estimate is sent — see open question in `estimates-and-prices.md`)
- If **estimate** is set and estimate status is `open`, `accepted`, or
  `rejected` → worksheet status must be `final`
- If **estimate** is set and estimate status is `superseded` → worksheet
  status must be `superseded`
- If **estimate** is null → worksheet status is `draft` (no estimate
  generated yet)
- Worksheet's **job** must match its linked estimate's **job** (if estimate is
  set)
- Worksheet's `parent.job` must equal its own `job`

---

### 1.10 PlanTask

Depends on: EstWorksheet, RateScheme.

The planning-side counterpart to Task. Lives on an EstWorksheet; no
lifecycle, no hierarchy, no Bleps. Carries billing fields directly so a
worksheet is a self-contained pricing artefact.

- **est_worksheet** (required FK → EstWorksheet, CASCADE)
- **rate_scheme** (required FK → RateScheme, PROTECT)
- **active_modifiers**: for `elapsed_time` / `entered_qty`, a JSON list of
  modifier keys (default `[]`), each present in `rate_scheme.modifiers`; for
  `flat_fee`, a dict `{"flat_fee_price": str}` holding the per-unit price
- **est_qty** (required at the application layer — `clean()` raises if null):
  decimal in the scheme's units. DB column is nullable, but every PlanTask
  must have a value.
- **est_worker_time**: optional Duration
- **name**: required, max 255 chars; **description**: text, default ''
- **sort_order**: auto-assigned per worksheet on save

PlanTasks are flat (no `parent_task`). Hierarchy is Job-side only.

---

### 1.11 Task

Depends on: Job, RateScheme, (optionally) User, PlanTask, TaskTemplate.

The work-side counterpart to PlanTask. Lives on a Job; carries lifecycle,
hierarchy, and Bleps.

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
- **active_modifiers**: JSON — list of modifier keys, or
  `{"flat_fee_price": str}` for `flat_fee` schemes (see RateScheme §1.7)
- **est_qty** (inherited from `TaskBase`): optional — for `flat_fee` it is
  the billable quantity (charge is `flat_fee_price × est_qty`)
- **est_worker_time**: optional Duration — but **required (and must be > 0)
  once `assignee` is set**; assigned work has to be schedulable
- **actual_qty**: optional decimal — worker-entered qty for `entered_qty`
  schemes. Null for `elapsed_time` (derived from Bleps) and `flat_fee`.
- **status**: default `pending`
- **blocked_reason**: text, default '' — set by `block_task(reason=...)`, cleared by `unblock_task`/`complete_task`/`cancel_task`. The previous reason is overwritten and not preserved anywhere; once `@history` is added to Task (see `jobs-tasks-and-worksheets.md` §13), each block/unblock will surface in the HistoryPanel
- **worker_queue**: optional integer — position in assignee's queue
- **assignee** (optional FK → User, SET_NULL): setting it requires a
  non-zero `est_worker_time` (see that field)
- **parent_task** (optional FK → self, CASCADE)
- **source_template** (optional FK → TaskTemplate, SET_NULL)
- **source_plan_task** (optional OneToOne → PlanTask, SET_NULL): set by
  carry-over; enforces idempotency.
- **sort_order**: auto-assigned per Job on save
- **name** / **description**: text

#### Implied state from other models

- An assigned Task (`assignee` set) must carry a non-zero `est_worker_time`
  — assigned work has to be schedulable. Enforced by `Task.clean()` on
  every save. `TaskService.assign` additionally pre-checks before saving
  and raises `TaskWorkerTimeRequired`, so the assign endpoint can answer
  `{needs_worker_time: true}` and have the UI prompt for an estimate
  instead of surfacing a generic validation error. Unassigning has no
  such requirement.
- A Task with any Bleps must not be in `pending`. Validator-enforced.
- Task → terminal auto-closes any open Bleps (end_time := now).
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
    a status where work belongs. `start_work` requires `approved` or
    `in_progress`; `create_historical` also permits `work_complete`.
    Any other Job status (`draft`, `submitted`, `rejected`, `completed`,
    `cancelled`) is rejected with `ValidationError`.
- Steady-state invariant: a Blep's task is in `in_progress`, `blocked`,
  `complete`, or `cancelled` — never `pending`, because `start_work`
  promotes before creating and `create_historical` is only sensibly
  used after work has already happened. The validator can check this
  on fixtures.
- **user** (optional FK → User, PROTECT)
- **start_time**: datetime, nullable
- **end_time**: datetime, nullable. If set, must be after start_time.
- An "open" Blep has `start_time` set and `end_time` null (work in progress)
- **No overlapping Bleps per user**: for any given User, no two Bleps (across
  all Tasks) may have overlapping time ranges. The app enforces this by
  closing the user's open Blep before creating a new one.
- Open Bleps are auto-closed (end_time set to now) when their Task transitions
  to `complete`, `cancelled`, or `blocked`.

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
- **price_list_item** (optional FK → PriceListItem, PROTECT): set when the
  line bills a freeform PLI rather than a plan-side atom
- **source_template** (optional FK → TaskTemplate, SET_NULL): preserves the
  catalog ref for direct-estimate lines so carry-over can still create a
  Task at acceptance even with no PlanTask
- **line_number**: auto-generated sequentially per estimate if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)
- **accounting_category** (optional FK): null = silently tax-exempt;
  auto-populated from PLI when linked

#### EstimateLineItemSource

Polymorphic row joining a line item to a plan-side atom.

- **estimate_line_item** (required FK → EstimateLineItem, CASCADE)
- **source_type**: `plan_task` or `plan_material`
- **source_pk**: integer pointing at the atom
- `unique_together = [('source_type', 'source_pk')]` — a plan atom can be
  referenced by at most one line item, ever. (Worksheet revisions copy
  atoms, so this never fires across revisions in practice.)
- The atom's worksheet's `job` must match the line item's estimate's `job`
  (validator-enforced).

See `docs/designs/estimates-and-prices.md`.

---

### 1.14 WorkTemplate / TaskTemplate / TemplateTaskAssociation / TemplateMaterialAssociation

The template system used to populate Jobs and EstWorksheets with reusable
task/material structures.

#### WorkTemplate

- **template_name**: max 255 chars; **description**: text
- **base_price**: optional decimal
- **created_date**: auto-set
- Hard-deleted. Nothing in the system holds a back-reference to a
  WorkTemplate after it has populated a Job or Worksheet, so a delete
  cascades cleanly through its TemplateTaskAssociation and
  TemplateMaterialAssociation rows.

#### TaskTemplate

- **template_name**: max 255 chars; **description**: text
- **rate_scheme** (required FK → RateScheme, PROTECT): default for generated
  PlanTasks / Tasks. Superseded schemes raise `SchemeSupersededError` from
  `generate_task()`.
- **default_active_modifiers**: JSON — list of modifier keys, or
  `{"flat_fee_price": str}` for `flat_fee` schemes. `TaskTemplate.clean()`
  requires a positive `flat_fee_price` when the rate scheme is `flat_fee`.
- **default_billable_qty** (required, decimal): used as `est_qty` when
  generating
- **work_templates**: M2M via `TemplateTaskAssociation`
- **is_active**: boolean, default True — the soft-delete flag.
  `WorkTemplate.generate_tasks_for_worksheet` and `generate_tasks_for_job`
  filter associations by `task_template__is_active=True`, and the
  TaskTemplate picker UI hides inactive entries. Soft-delete (not
  hard-delete) is the intended path because `Task.source_template` and
  `EstimateLineItem.source_template` are `SET_NULL` FKs — hard-deleting
  a TaskTemplate would lose the catalog reference on every Task and
  EstimateLineItem that originated from it.

#### TemplateTaskAssociation

- **work_template**, **task_template**: CASCADE FKs
- **est_qty**: decimal, default 1 (quantity passed to `generate_task()`)
- **sort_order**: integer, default 0
- `unique_together = ['work_template', 'task_template']`

#### TemplateMaterialAssociation

- **work_template** (FK → WorkTemplate, CASCADE)
- **price_list_item** (required FK → PriceListItem, PROTECT) — templates
  carry no freeform materials; everything goes through the PLI catalog
- **template_task_association** (optional FK → TemplateTaskAssociation,
  SET_NULL): if set, generated material attaches to the corresponding
  generated PlanTask/Task. `clean()` enforces this association belongs to
  the same WorkTemplate.
- **quantity** (required, decimal); **sort_order**: integer, default 0

---

### 1.15 Material (+ PlanMaterial)

Real-side and plan-side material rows; both extend `MaterialBase` (abstract).

#### Shared fields (MaterialBase)

- **description**: max 255 chars, default ''
- **quantity**: decimal, default 0 (non-negative)
- **units**: max 50 chars, default 'none'
- **unit_cost**, **sell_price**: decimals, default 0
- **price_list_item** (optional FK → PriceListItem, SET_NULL)
- **accounting_category** (required FK → AccountingCategory, PROTECT)

On save, `_populate_from_pli()` fills `description`, `units`, `unit_cost`,
`sell_price`, `accounting_category` from the linked PLI. A PLI-linked
Material/PlanMaterial is effectively immutable for description/units/AC
(pricing carve-out — see `docs/designs/materials-inventory-and-purchasing.md`).
Either a description or a `price_list_item` must be present.

#### PlanMaterial

Worksheet-side. No inventory side effects.

- **est_worksheet** (required FK → EstWorksheet, CASCADE)
- **plan_task** (optional FK → PlanTask, CASCADE): if set, task-bound;
  otherwise floats at the worksheet level. `clean()` enforces
  `plan_task.est_worksheet == est_worksheet`.

#### Material

- **job** (required FK → Job, CASCADE)
- **task** (optional FK → Task, SET_NULL): if null, the Material floats on
  the Job. `clean()` enforces `task.job == job` when both are set.
- **consumption_state**: `pending` or `consumed`. Default `pending`. Flipped
  to `consumed` by `MaterialService.consume`.
- **restocked_qty**: decimal, default 0, non-negative. Tracks returned qty
  for expense-bound materials.
- **po_line_item** (optional FK → PurchaseOrderLineItem, SET_NULL)
- **source_plan_material** (optional OneToOne → PlanMaterial, SET_NULL):
  set by carry-over; enforces idempotency.

#### Implied state from other models

- A Material with an inventoried PLI landing on a Job triggers an Earmark
  upsert via `InventoryService._mutate_earmark(pli, job, +qty)`. See §2.6.
- Consume / Restock flip earmarks back via `_mutate_earmark(..., -qty)`.
- Job entering `work_complete` releases all remaining earmarks for the Job.

---

### 1.16 Invoice (+ InvoiceLineItem + InvoiceLineItemSource)

Depends on: Job.

#### Status machine

Statuses: `draft`, `open`, `cancelled`, `superseded`, `partly-paid`, `paid`,
`defaulted`.

No explicit transition validation in `clean()`. The validator checks:
- Status must be a valid choice
- Invoice should not exist for `draft`/`submitted`/`rejected` jobs
- If Job is `cancelled`, Invoice must also be `cancelled`

#### Fields

- **job** (required FK → Job, CASCADE)
- **invoice_number**: unique, max 50 chars. Auto-generated via
  NumberGenerationService if not provided.
- **created_date**: set on creation
- **sent_date**: nullable (when sent to customer)
- **closed_date**: nullable (when paid in full or defaulted)
- **qbo_id**, **qbo_payment_status**, **qbo_amount_paid**: nullable QBO sync
  fields

#### Line item requirement

Cannot transition out of `draft` without at least one InvoiceLineItem.
Enforced in `Invoice.clean()`.

#### InvoiceLineItem

- **invoice** (required FK → Invoice, CASCADE)
- No `task` FK — the `task` property returns `None` for
  `BaseLineItem.clean()` compatibility. Source atoms are joined via
  `InvoiceLineItemSource`.
- **price_list_item** (optional FK → PriceListItem, PROTECT)
- **line_number**: auto-generated sequentially per invoice if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)

#### InvoiceLineItemSource

Polymorphic row joining an `InvoiceLineItem` to its real-side source atom.

- **invoice_line_item** (required FK → InvoiceLineItem, CASCADE)
- **source_type**: `material` or `task`; **source_pk**: integer
- `unique_together = [('source_type', 'source_pk')]` — global. A Task or
  Material can be billed by at most one Invoice line, ever. Prevents
  double-billing across invoice revisions.

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

- **business** (required FK → Business, PROTECT)
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
- **price_list_item** (optional FK → PriceListItem, PROTECT)
- **line_number**: auto-generated sequentially per PO if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work)
- **qty_received**: decimal, default 0 (populated by receive actions)
- **qty_cancelled**: decimal, default 0 (replaces the old `cancelled` boolean)
- **received_by** (optional FK → User, SET_NULL); **received_date**: nullable
- **receipt_note**: text, default ''

---

### 1.18 Bill (+ BillLineItem)

Depends on: Business, (optionally) Contact, PurchaseOrder.

#### Status machine

```
draft → received → partly_paid → paid_in_full → refunded
                 ↘ paid_in_full
                 ↘ cancelled
```

Valid transitions:
- `draft` → `received`
- `received` → `partly_paid`, `paid_in_full`, `cancelled`
- `partly_paid` → `paid_in_full`
- `paid_in_full` → `refunded`
- `cancelled`, `refunded` → (terminal)

#### Fields

- **business** (required FK → Business, PROTECT)
- **contact** (optional FK → Contact, PROTECT): same rules as PurchaseOrder
  (must have business, must match on creation)
- **vendor_invoice_number**: required, max 50 chars. The vendor's own
  number from the invoice; serves as the primary human-facing identifier
  for the Bill (no Minibini-side auto-generated number).
- **purchase_order** (optional FK → PurchaseOrder, PROTECT): if set, PO must
  NOT be in `draft` status. PO's business must match bill's business.
- If contact is provided on creation and business is not explicitly set,
  business is auto-populated from contact's business.
- **qbo_id**: optional QBO sync ID
- **qbo_payment_status**: optional QBO payment state string

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **received_date**: auto-set to `now()` on transition to `received`.
  Immutable once set.
- **paid_date**: auto-set to `now()` on transition to `paid_in_full`.
  Immutable once set.
- **cancelled_date**: auto-set to `now()` on transition to `cancelled`.
  Immutable once set.
- **due_date**: optional, user-set

#### Line item requirement

Cannot transition out of `draft` without at least one BillLineItem.

#### Deletion

Only `draft` Bills can be deleted.

#### BillLineItem

- **bill** (required FK → Bill, CASCADE)
- **task** (optional FK → Task, PROTECT): reserved alongside
  `PurchaseOrderLineItem.task` for the future "service PO" feature.
  Only `BillService.create_bill_from_po` writes to it (copying the value
  from the source PO line); since PO-line `task` is always null today,
  this field is null in practice too. Defined directly on the subclass,
  not on `BaseLineItem`.
- **price_list_item** (optional FK → PriceListItem, PROTECT)
- Cannot have both **task** and **price_list_item** set (mutually exclusive
  per `BaseLineItem.clean()`)
- **line_number**: auto-generated sequentially per bill if null
- **price**: decimal, no current validation (negative values are legitimate for discount/credit lines; a sanity-check warning is tracked in `architecture-and-conventions.md` unfinished work) values

---

### 1.19 Earmark

Depends on: PriceListItem, Job.

A per-PLI-per-Job aggregate row representing the inventory committed to a
Job. There is exactly one row per `(price_list_item, job)`; quantity reflects
the running sum of Material commitments minus consumption/restock.

- **price_list_item** (required FK → PriceListItem, CASCADE): PLI should be
  inventoried (`is_inventoried=True`); a non-inventoried PLI never reaches
  `_mutate_earmark`
- **job** (required FK → Job, CASCADE)
- **quantity**: must be positive (> 0). Rows with `quantity <= 0` are deleted
  by `_mutate_earmark`. Warn if quantity exceeds PLI's `qty_on_hand`.
- `unique_together = [('price_list_item', 'job')]`
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

Depends on: PriceListItem.

- **price_list_item** (required FK → PriceListItem, CASCADE): warn if PLI is
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
- **qty_ordered** (required, decimal(10,2)): customer-agreed quantity. Only
  changes via change order (deferred — not yet implemented).
- **units** (required, max 50 chars): drawn from `Configuration['units_list']`
- **sort_order** (PositiveInteger): auto-assigned to next slot on save when
  unset (10, 20, 30, …). Renumbered to a contiguous sequence after a
  service-driven delete.
- **created_at** / **updated_at**: timestamps.
- `db_table = 'deliverables'`. Default ordering: `sort_order`.

**Editability** — computed from the Job's estimate state, not stored:

- **Editable** when no estimate exists OR the latest non-terminal estimate is
  in `draft` (terminal here means `superseded`, `rejected`, or `expired`).
- **Read-only otherwise**, with the UI surfacing a reason
  (`estimate_sent` when latest active is `open`; `estimate_accepted` when any
  estimate on the Job is `accepted`).
- Enforced by `DeliverableService._assert_editable(job)`; create / update /
  delete / reorder all raise `ValidationError` outside the editable state.

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
Reachable only via change orders (deferred); the Deliverable editability
rules already prevent deletion once shipments could exist.

See `docs/designs/jobs-tasks-and-worksheets.md` for the full
fulfillment workflow.

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

- **entity_type** (e.g. `invoice`, `bill`, `expense`); **entity_id** (int)
- **qbo_entity_type** / **qbo_entity_id** (max 50 chars, blank)
- **action** (e.g. `create`, `update`); **status** (e.g. `success`,
  `failure`)
- **error_message**: text, blank
- **synced_at**: auto-set on creation

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

### 2.3 Estimate accepted → atoms carried over to Job

**Trigger:** Estimate status changes to `accepted`; the `estimate_accepted`
signal calls `AtomCarryOverService.carry_over_for_estimate(estimate)`.

**Effects:**
- For each PlanTask on the estimate's worksheet → create a Task on the Job
  (copying `name`, `description`, `rate_scheme`, `active_modifiers`,
  `est_qty`, `est_worker_time`, `sort_order`). `Task.source_plan_task` is
  set; the OneToOne enforces idempotency.
- For each PlanMaterial on the worksheet → create a Material on the Job
  (task-bound if the PlanMaterial was attached to a PlanTask, floating
  otherwise) via `MaterialService.create_on_job`, which also fires §2.6.
- For direct-estimate line items with `source_template` set and no source
  row → create a Task on the Job from the TaskTemplate.
- For direct-estimate line items with `price_list_item` set and no source
  row → create a Material on the Job.

**Data constraint:** An `accepted` Estimate should have matching atoms on
its Job. `Task.source_plan_task` and `Material.source_plan_material`
(both OneToOne) ensure re-firing the signal does not duplicate atoms.

See `docs/designs/estimates-and-prices.md` and
`apps/estimates/carry_over.py`.

---

### 2.4 Estimate status change → EstWorksheet status update

**Trigger:** Estimate status changes.

**Effects (mapping):**
- Estimate `draft` → Worksheet `draft`
- Estimate `open`, `accepted`, `rejected` → Worksheet `final`
- Estimate `superseded` → Worksheet `superseded`

All EstWorksheets linked to the Estimate (via `estimate` FK) are updated.

**Data constraint:** A worksheet with a linked estimate must have the status
dictated by the mapping above. When an Estimate transitions to `open` (sent),
the worksheet moves from `draft` → `final` — the worksheet's transition
timestamp should match the Estimate's `sent_date`.

Implemented by the `estimate_status_changed_for_worksheet` signal in
`apps/estimates/signals.py`.

---

### 2.5 Last Invoice paid → Job completed

**Trigger:** An Invoice transitions to `paid`.

**Effects:**
- If ALL Invoices for the Job are now `paid` (or `cancelled`), the Job
  transitions to `completed`. The handler walks the state machine through
  `in_progress` → `work_complete` → `completed` if the Job is still
  `approved` at the moment of payment (each step via `JobService.update_job`).
- Before the walk, any loose pending Materials on the Job are released
  (restocked) so the `work_complete` materials gate cannot strand the Job —
  this is an unattended path with no user to resolve them. A `HistoryEntry`
  records the release if anything was released.
- Job's `completed_date` is set to `now()` (or should match the last
  Invoice's `closed_date` in a backdated translation).
- A `HistoryEntry` of `entry_type='action'` is created on the Job, attributed
  to the `system` user, recording the auto-complete.

**Data constraint:** If all Invoices for a Job are `paid`/`cancelled`, the
Job must be `completed` with a `completed_date` no earlier than the last
Invoice's `closed_date`.

Implemented in `Invoice.save()` → `_maybe_complete_job()`.

---

### 2.6 Inventoried Material on Job → Earmark created

**Trigger:** A Material with an inventoried `price_list_item` is created on a
Job — via any path (direct add, template populate, worksheet copy, PO line
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
- The worksheet linked to the previous Estimate moves to `superseded` via
  §2.4.

**Data constraint:** In a version chain (same `estimate_number`), all versions
below the maximum must be `superseded` with a `closed_date` set.

---

### 2.11 EstWorksheet version chain → supersession

**Trigger:** `create_new_version()` is called on an EstWorksheet.

**Effects:**
- Current worksheet marked `superseded`.
- New worksheet created with `version = old.version + 1`, `parent = old`,
  `status = draft`, `estimate = None`.
- All PlanTasks (with their PlanMaterials) are copied to the new worksheet.

**Data constraint:** In a worksheet version chain (same Job), parent
worksheets should be `superseded`. Child version numbers must be higher than
parent's.

---

### 2.12 Estimate mark_open → Deliverables non-empty guard

**Trigger:** `EstimateService.mark_open(estimate_pk)` is called to transition
an Estimate from `draft` to `open`.

**Effects:**
- If the Job has zero `Deliverable` rows, `ValidationError` is raised and
  no state changes.
- Otherwise the transition proceeds normally (Estimate goes `open`, signal
  walks the Job through `draft → submitted` if needed, the worksheet — if
  draft — moves to `final`).

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
scheme should be updated to point at the new scheme; otherwise
`generate_task()` raises `SchemeSupersededError`.

---

## Section 3: History Generation

HistoryEntry records the audit trail via generic refs (no real FKs), created
as side effects of object operations.

### HistoryEntry structure

- **entry_type**: `audit` (field changes), `action` (system status
  transitions), `note` (user-written text)
- **object_type**: string identifier (e.g. `job`, `estimate`, `contact`,
  `business`, `estworksheet`, `invoice`, `purchaseorder`, `bill`)
- **object_id**: integer PK of the referenced object
- **user** (FK → User, nullable): `audit` → acting user; `action` →
  `system` user; `note` → authoring user
- **timestamp**: auto-set on creation
- **changes**: JSON. For `audit`: `{field: {old, new}, ...}` plus optional
  `_created: true`. For `action`: includes `_action` description string.
- **text**: human-entered text (notes only). Empty for `audit`/`action`.

### What generates history

`@history`-decorated models: Contact, Business, Job, Estimate, EstWorksheet,
Invoice, PurchaseOrder, Bill. The decorator creates `audit` entries on
create and update.

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
