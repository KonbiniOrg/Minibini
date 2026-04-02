# Data Constraints

Business invariants that the database schema cannot enforce. These constraints are
enforced by model `clean()`/`save()` methods, services, and signals — all of which
are bypassed when loading fixture data directly.

This document answers: **what must be true about each object for it to be
indistinguishable from one created by the running application?**

Consumers: the data validator (`validate_data.py`), the translation script
(`convert_neals_data.py`), anyone creating test fixtures.

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
- `bill_number_sequence` / `bill_counter`

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
- **Permissions**: 6 custom atoms defined on the model: `can_view_financials`,
  `can_manage_jobs`, `can_manage_financials`, `can_manage_time`,
  `can_approve_expenses`, `can_manage_config`
- A `system` user (username='system', is_active=False) is auto-created by
  signals when needed — data sets should include one

---

### 1.3 AccountingCategory

Standalone. No FK dependencies.

- **code**: unique, max 20 chars (e.g. "SVC", "MAT")
- **name**: max 100 chars
- **taxable**: boolean, default True
- **is_active**: boolean, default True (soft delete)

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
- **accounting_category** (FK → AccountingCategory): should be set; missing
  category causes line items to be silently tax-exempt
- **purchase_price**, **selling_price**: non-negative decimals
- **qty_on_hand**, **qty_sold**, **qty_wasted**: non-negative decimals
- **is_inventoried**: boolean. If false, all quantity fields should be 0.
- **is_active**: boolean, default True (soft delete)
- **Deletion blocked** if referenced by any line item, earmark, or adjustment

---

### 1.7 Job

Depends on: Contact.

#### Status machine

```
draft → submitted → approved → completed
                  ↘ rejected    ↘ cancelled
draft → rejected
```

Valid transitions:
- `draft` → `submitted`, `rejected`
- `submitted` → `approved`, `rejected`
- `approved` → `completed`, `cancelled`
- `rejected`, `completed`, `cancelled` → (terminal)

#### Fields

- **job_number**: unique, max 50 chars. Generated via NumberGenerationService
  (pattern from Configuration). Only generated for new instances.
- **contact** (required FK → Contact)
- **status**: must be one of the choices above, default `draft`

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **start_date**: auto-set to `now()` on transition to `approved`. Immutable
  once set. Should be null for `draft`/`submitted`/`rejected`.
- **due_date**: optional, user-set
- **completed_date**: auto-set to `now()` on transition to `completed` or
  `cancelled`. Immutable once set. Must be null for
  `draft`/`submitted`/`approved`.

#### Implied state from other models

- If any Estimate for this Job is `open` or later (i.e. has been sent), this
  Job must be `submitted` or later (never `draft`).
- If any Estimate for this Job has status `accepted`, this Job must be
  `approved`, `completed`, or `cancelled` (never `draft`, `submitted`, or
  `rejected`).
- At most one Estimate for this Job can be on a track for approval — i.e. in
  `draft` or `open` status. All other Estimates must be `rejected` or
  `superseded`. (The "only one `accepted`" rule is a subset of this.)
  Not enforced in code but true by UI design — the validator should check this.
- If Job is `approved`, exactly one Estimate for this Job must be `accepted`.
- If Job is `completed` or `cancelled`, no Estimates for this Job should be
  `draft` or `open` (unresolved).
- If all Invoices for this Job are `paid`, this Job must be `completed`.
  Not enforced in code but true by UI design — the validator should check this.
- If Job is `cancelled`, all Invoices for this Job must also be `cancelled`.
- WorkOrder auto-completes when all its Tasks reach terminal state — but this
  does not auto-change the Job's status.

---

### 1.8 EstWorksheet

Depends on: Job, (optionally) Estimate, WorkOrderTemplate.

#### Status machine

No explicit transition validation in `clean()`. Status is driven by Estimate
status changes (see implied state).

Statuses: `draft`, `final`, `superseded`.

#### Fields

- **job** (required FK → Job)
- **estimate** (optional FK → Estimate): if set, the worksheet was used to
  generate that estimate
- **version**: integer, default 1. Must be unique per job when combined with
  parent chain.
- **parent** (optional FK → self): if set, parent must belong to the same Job
  and have a lower version number. Parent should be in `superseded` status.
- **created_date**: set on creation

#### Implied state from other models

- If **estimate** is set and estimate status is `superseded` → worksheet status
  must be `superseded`
- If **estimate** is set and estimate status is anything else → worksheet status
  must be `final` (sending the estimate locks the worksheet). The worksheet's
  `draft` → `final` transition should coincide with the estimate's `sent_date`.
- If **estimate** is null → worksheet status is `draft` (no estimate generated
  yet)
- Worksheet's **job** must match its linked estimate's **job** (if estimate is
  set)

---

### 1.9 TaskBundle

Depends on: EstWorksheet or WorkOrder, AccountingCategory.

- Must belong to **exactly one** container: either `est_worksheet` or
  `work_order` (not both, not neither)
- **accounting_category** (required FK → AccountingCategory)
- **sort_order**: integer, position at the container level
- All Tasks in this bundle must belong to the same container as the bundle

---

### 1.10 Task

Depends on: EstWorksheet or WorkOrder, (optionally) TaskBundle, User,
AccountingCategory.

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

- Must belong to **exactly one** container: either `work_order` or
  `est_worksheet` (not both, not neither)
- **mapping_strategy**: `direct`, `bundle`, or `exclude`
  - If `bundle` → `bundle` FK must be set
  - If `bundle` FK is set → `mapping_strategy` must be `bundle`
  - Bundle must belong to the same container as the task
- **sort_order**: auto-generated if null. For bundled tasks: sequential within
  bundle. For unbundled tasks: sequential at container level (alongside
  TaskBundles).
- **parent_task** (optional FK → self): for hierarchical task structures
- **assignee** (optional FK → User)

#### Implied state from other models

- A Task with any Bleps must not be in `pending` status.
  Not enforced in code but true by UI design — the validator should check this.
- When a Task on a WorkOrder reaches `complete` or `cancelled`, and ALL other
  Tasks on that WorkOrder are also in terminal state (`complete` or `cancelled`),
  the WorkOrder auto-completes.
- When a Task transitions to `complete` or `cancelled`, any open Bleps
  (end_time is null) on that Task are auto-closed with end_time set to now.

---

### 1.11 Estimate (+ EstimateLineItem)

Depends on: Job.

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

- **job** (required FK → Job)
- **estimate_number**: max 50 chars. Generated via NumberGenerationService.
  `(estimate_number, version)` is unique together.
- **version**: integer, default 1
- **parent** (optional FK → self): for version chains
- **Only one accepted estimate per job**: if status is `accepted`, no other
  Estimate for the same Job can be `accepted`.

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **sent_date**: auto-set to `now()` on transition to `open`. Immutable once
  set. Should be null for `draft`.
- **expiration_date**: auto-set to `now() + est_expire_days` on transition to
  `open` (reads from Configuration). Should be null for `draft`.
- **closed_date**: auto-set to `now()` on transition to `accepted`, `rejected`,
  `superseded`, or `expired`. Immutable once set.

#### Version chain rules

- Estimates sharing the same `estimate_number` form a version chain
- All versions below the maximum must be in `superseded` status
- Parent chain should link sequential versions: v2's parent = v1, v3's parent = v2
- A `superseded` Estimate must be an earlier version of another Estimate with
  the same `estimate_number` — superseded estimates cannot exist in isolation.
  Not enforced in code but true by UI design — the validator should check this.
- Timestamps must be chronologically ordered within a version chain: a
  superseded estimate's `created_date` and `closed_date` must be earlier than
  the next version's `created_date`.
  Not enforced in code but true by UI design — the validator should check this.

#### Line item requirement

Cannot transition out of `draft` without at least one EstimateLineItem.
Enforced in `Estimate.clean()`.

#### EstimateLineItem

- **estimate** (required FK → Estimate)
- Cannot have both **task** and **price_list_item** set (mutually exclusive)
- **line_number**: auto-generated sequentially per estimate if null
- **price**: warn on negative values
- If **task** is set, the task's container's job must match the estimate's job

---

### 1.12 WorkOrder

Depends on: Job, (optionally) WorkOrderTemplate.

#### Status machine

```
incomplete → blocked → incomplete
           ↘ complete
```

Valid transitions:
- `incomplete` → `blocked`, `complete`
- `blocked` → `incomplete`
- `complete` → (terminal)

#### Fields

- **job** (required FK → Job)
- **status**: default `incomplete`

#### Implied state from other models

- If any Task on this WorkOrder is `blocked`, this WorkOrder must be `blocked`.
  Not enforced in code but true by UI design — the validator should check this.
- Auto-completes when ALL Tasks on this WorkOrder are in terminal state
  (`complete` or `cancelled`)

---

### 1.13 Blep

Depends on: Task, User.

- **task** (required FK → Task, PROTECT): task must NOT be in `pending` status.
  Bleps can exist on tasks in any other state (`in_progress`, `blocked`,
  `complete`, `cancelled`).
  Not enforced in code but true by UI design — the validator should check this.
- **user** (optional FK → User, PROTECT)
- **start_time**: datetime, nullable
- **end_time**: datetime, nullable. If set, must be after start_time.
- An "open" Blep has `start_time` set and `end_time` null (work in progress)
- **No overlapping Bleps per user**: for any given User, no two Bleps (across
  all Tasks) may have overlapping time ranges. The app enforces this by closing
  the user's open Blep before creating a new one.
- Open Bleps are auto-closed (end_time set to now) when their Task transitions
  to `complete`, `cancelled`, or `blocked`

---

### 1.14 Material

Depends on: Task, (optionally) PriceListItem, AccountingCategory.

- **task** (required FK → Task)
- Must have either **description** or **price_list_item** (or both)
- **quantity**: non-negative decimal
- If **price_list_item** is set and fields are at defaults, auto-populated on
  save:
  - `description` ← `price_list_item.description` (truncated to 255 chars)
  - `unit_cost` ← `price_list_item.purchase_price` (if unit_cost is 0.00)
  - `sell_price` ← `price_list_item.selling_price` (if sell_price is 0.00)
  - `accounting_category` ← `price_list_item.accounting_category` (if null)

---

### 1.15 Invoice (+ InvoiceLineItem)

Depends on: Job.

#### Status machine

Statuses: `draft`, `open`, `cancelled`, `superseded`, `partly-paid`, `paid`,
`defaulted`.

No explicit transition validation in `clean()`. The validator checks:
- Status must be a valid choice
- Invoice should not exist for `draft`/`submitted`/`rejected` jobs
- If Job is `cancelled`, Invoice must also be `cancelled`

#### Fields

- **job** (required FK → Job)
- **invoice_number**: unique, max 50 chars. Auto-generated via
  NumberGenerationService if not provided.
- **created_date**: set on creation
- **sent_date**: nullable (when sent to customer)
- **closed_date**: nullable (when paid in full or defaulted)

#### Line item requirement

Cannot transition out of `draft` without at least one InvoiceLineItem.
Enforced in `Invoice.clean()`.

#### InvoiceLineItem

- **invoice** (required FK → Invoice)
- Cannot have both **task** and **price_list_item** set (mutually exclusive)
- **line_number**: auto-generated sequentially per invoice if null
- **price**: warn on negative values

---

### 1.16 PurchaseOrder (+ PurchaseOrderLineItem)

Depends on: Business, (optionally) Contact.

#### Status machine

```
draft → issued → partly_received → received_in_full
               ↘ received_in_full
               ↘ cancelled
```

Valid transitions:
- `draft` → `issued`
- `issued` → `partly_received`, `received_in_full`, `cancelled`
- `partly_received` → `received_in_full`
- `received_in_full`, `cancelled` → (terminal)

#### Fields

- **business** (required FK → Business)
- **contact** (optional FK → Contact): if set, contact must have a business.
  On creation, if both contact and business are provided, contact's business
  must match.
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
- Non-draft POs should have `issued_date`
- `received_in_full` POs should have `received_date`
- `cancelled` POs should have `cancel_date`

#### Deletion

Only `draft` POs can be deleted.

#### Line item requirement

Cannot transition out of `draft` without at least one PurchaseOrderLineItem.
Enforced in `PurchaseOrder.clean()`.

#### PurchaseOrderLineItem

- **purchase_order** (required FK → PurchaseOrder)
- **job** (optional FK → Job)
- Cannot have both **task** and **price_list_item** set (mutually exclusive)
- **line_number**: auto-generated sequentially per PO if null
- **price**: warn on negative values

---

### 1.17 Bill (+ BillLineItem)

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

- **business** (required FK → Business)
- **contact** (optional FK → Contact): same rules as PurchaseOrder (must have
  business, must match on creation)
- **bill_number**: unique, max 50 chars. Auto-generated via
  NumberGenerationService if not provided.
- **vendor_invoice_number**: required, max 50 chars
- **purchase_order** (optional FK → PurchaseOrder): if set, PO must NOT be in
  `draft` status. PO's business must match bill's business.
- If contact is provided on creation and business is not explicitly set,
  business is auto-populated from contact's business.

#### Date rules

- **created_date**: set on creation, immutable thereafter
- **received_date**: auto-set to `now()` on transition to `received`. Immutable
  once set.
- **paid_date**: auto-set to `now()` on transition to `paid_in_full`. Immutable
  once set.
- **cancelled_date**: auto-set to `now()` on transition to `cancelled`.
  Immutable once set.

#### Line item requirement

Cannot transition out of `draft` without at least one BillLineItem.

#### Deletion

Only `draft` Bills can be deleted.

#### BillLineItem

- **bill** (required FK → Bill)
- Cannot have both **task** and **price_list_item** set (mutually exclusive)
- **line_number**: auto-generated sequentially per bill if null
- **price**: warn on negative values

---

### 1.18 Earmark

Depends on: PriceListItem, Job.

- **price_list_item** (required FK → PriceListItem): PLI must be inventoried
  (`is_inventoried=True`)
- **job** (required FK → Job)
- **quantity**: must be positive (> 0). Warn if exceeds PLI's `qty_on_hand`.
- `(price_list_item, job)` is unique together
- Warn if job is in terminal state (`completed`, `cancelled`, `rejected`) —
  inventory should have been consumed or released

#### Implied state from other models

- Earmarks are auto-created when an Estimate is accepted, for all inventoried
  materials on the accepted estimate's worksheets.

---

### 1.19 InventoryAdjustment

Depends on: PriceListItem.

- **price_list_item** (required FK → PriceListItem): warn if PLI is not
  inventoried
- **quantity_change**: decimal (can be positive or negative)
- **created_date**: auto-set on creation

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
- **Current code behavior:** The `update_job_status` signal handler still
  includes a double-transition path (`draft` → `submitted` → `approved`) as
  a safety net, even though 2.1 should ensure the Job is already `submitted`
  by the time the Estimate is accepted.

**Data constraint:** If an Estimate is `accepted`, its Job must be `approved`,
`completed`, or `cancelled`.

---

### 2.3 Last Invoice paid → Job completed

**Trigger:** An Invoice transitions to `paid`.

**Effects:**
- If ALL Invoices for the Job are now `paid`, the Job transitions from
  `approved` → `completed`.
- Job's `completed_date` is set to `now()` (or should match the last Invoice's
  `closed_date`).

**Data constraint:** If all Invoices for a Job are `paid`, the Job must be
`completed` with a `completed_date` no earlier than the last Invoice's
`closed_date`.

Implemented in `Invoice.save()` → `_maybe_complete_job()`. Checks whether
all Invoices for the Job are `paid` (or `cancelled`) and transitions the Job
to `completed`.

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

---

### 2.5 Estimate accepted → WorkOrder created from worksheet

**Trigger:** Estimate status changes to `accepted` and the Estimate has a
linked EstWorksheet.

**Effects:**
- A new WorkOrder is created for the same Job.
- All TaskBundles, Tasks, and Materials are copied from the EstWorksheet to the
  new WorkOrder (same logic as `WorkOrderService.copy_from_worksheet`).
- Tasks on the new WorkOrder start in `pending` status.

**Data constraint:** If an Estimate is `accepted` and has a linked worksheet,
a WorkOrder should exist for the same Job containing the same task/bundle
structure as the worksheet. The WorkOrder's Tasks should be in `pending` or
later status.

Implemented as a manual step via the `work_order_create_from_estimate` view.
The user clicks a button after estimate acceptance; the view calls
`WorkOrderService.copy_from_worksheet` (or generates tasks from line items
if no worksheet exists). Not auto-triggered by a signal.

---

### 2.6 Inventoried Material added to WorkOrder Task → Earmark created

**Trigger:** A Material with an inventoried PriceListItem is added to a Task
on a WorkOrder.

**Effects:**
- An Earmark is created (or updated) linking the PriceListItem to the Task's
  Job with the material's quantity.

**Data constraint:** For every inventoried Material on a WorkOrder's Tasks, a
corresponding Earmark should exist for that PriceListItem + Job. Earmark
quantities should reflect the sum of Material quantities per PriceListItem
across the WorkOrder.

This replaces the previous approach of creating Earmarks directly from Estimate
acceptance. The cascade is now: Estimate accepted → WorkOrder copied from
worksheet (2.5, which copies Materials) → each copied Material triggers earmark
creation (this rule). The estimate acceptance signal no longer needs to handle
earmarks directly.

> **Not yet automated.** Adding Materials to WorkOrder-linked Tasks does not
> currently trigger earmark creation. The existing earmark signal on estimate
> acceptance (`auto_earmark_inventory`) reads from worksheet materials and
> should eventually be removed in favor of this approach.

---

### 2.7 Task blocked → WorkOrder blocked

**Trigger:** A Task on a WorkOrder transitions to `blocked`.

**Effects:**
- WorkOrder status transitions to `blocked`.

**Data constraint:** A WorkOrder with any `blocked` Tasks must be `blocked`.

Implemented in `TaskLifecycleService._check_wo_blocked()`, called when a
Task transitions to `blocked`.

---

### 2.8 All Tasks terminal → WorkOrder auto-complete

**Trigger:** A Task on a WorkOrder transitions to `complete` or `cancelled`.

**Effects:**
- If ALL Tasks on that WorkOrder are now in terminal state (`complete` or
  `cancelled`), the WorkOrder status is set to `complete`.

**Data constraint:** A WorkOrder whose Tasks are ALL in terminal state must be
`complete`. A `complete` WorkOrder must have ALL Tasks in terminal state.

---

### 2.8 Blep started on pending Task → Task in_progress

**Trigger:** `start_task` is called on a `pending` Task.

**Effects:**
- Task transitions from `pending` → `in_progress`.
- A Blep is created on the Task with `start_time` set to `now()`.
- Any other open Blep the user has (on any task) is closed.

**Data constraint:** A Task's first Blep `start_time` should coincide with or
follow the Task's transition out of `pending`. If a Task is `in_progress`, all
Bleps on it must have `start_time` at or after the moment the Task entered
`in_progress`.

---

### 2.9 Task terminal → open Bleps closed

**Trigger:** A Task transitions to `complete`, `cancelled`, or `blocked`.

**Effects:**
- All Bleps on that Task with `end_time=null` get `end_time` set to `now()`.

**Data constraint:** A Task in terminal state (`complete` or `cancelled`) should
have no open Bleps (Bleps with null `end_time`). A `blocked` Task should also
have no open Bleps.

---

### 2.10 Estimate version chain → supersession

**Trigger:** A new version of an Estimate is created.

**Effects:**
- The previous version's status is set to `superseded`.
- The previous version's `closed_date` is set.
- The new version's `parent` FK points to the previous version.

**Data constraint:** In a version chain (same `estimate_number`), all versions
below the maximum must be `superseded` with a `closed_date` set.

---

### 2.11 EstWorksheet version chain → supersession

**Trigger:** `create_new_version()` is called on an EstWorksheet.

**Effects:**
- Current worksheet marked `superseded`
- New worksheet created with `version = old.version + 1`, `parent = old`,
  `status = draft`, `estimate = None`
- All TaskBundles and Tasks (with Materials) are copied to the new worksheet

**Data constraint:** In a worksheet version chain (same Job), parent worksheets
should be `superseded`. Child version numbers must be higher than parent's.

---

## Section 3: History Generation

HistoryEntry records the audit trail. They use generic references (not real FKs)
and are created as side effects of object operations.

### HistoryEntry structure

- **entry_type**: `audit` (field changes), `action` (system status transitions),
  `note` (user-written text)
- **object_type**: string identifier (e.g. `job`, `estimate`, `contact`,
  `business`, `workorder`, `worksheet`)
- **object_id**: integer PK of the referenced object
- **user**: FK → User (nullable). `audit` entries use the acting user. `action`
  entries use the `system` user. `note` entries use the authoring user.
- **timestamp**: auto-set on creation
- **changes**: JSON field. For `audit`: `{field: {old: val, new: val}, ...}`.
  May include `_created: true` for creation events. For `action`: includes
  `_action` key with description string.
- **text**: reserved for human-entered text only (`note` entries). Empty string
  for `audit` and `action` entries.

### What generates history

Objects decorated with `@history`: Contact, Business, Job, WorkOrder, Estimate,
EstWorksheet, Invoice, PurchaseOrder, Bill. The decorator creates `audit` entries
on create and update.

Signal handlers create `action` entries for:
- Job status changes triggered by Estimate acceptance (system user)

### Generating realistic history for test data

After all objects and states are reconciled:

1. **Creation entries**: For each `@history`-decorated object, create an `audit`
   entry with `_created: true` in changes, timestamped at the object's
   `created_date`.
2. **Status transition entries**: For objects not in their default status, create
   `action` entries for each transition step. Timestamps should be between
   `created_date` and any terminal date (`completed_date`, `closed_date`, etc.).
3. **Signal-driven entries**: For accepted Estimates, create `action` entries on
   the Job recording the `draft` → `submitted` → `approved` transitions,
   attributed to the `system` user.
4. **Notes** (optional): User-written notes on jobs, contacts, businesses for
   realism.

---

## Section 4: Code Updates Needed

Constraints documented above that differ from current code behavior. These
should be implemented to match the intended design.

### Completed

- **Task: blocked → complete transition** (Section 1.10) — Added
  `STATUS_COMPLETE` to `STATUS_BLOCKED` transitions in `Task.VALID_TRANSITIONS`.
- **Estimate sent → Job submitted** (Section 2.1) — Signal in
  `Estimate._maybe_update_job_status()` fires `estimate_status_changed_for_job`
  with `Job.STATUS_SUBMITTED` on the `draft` → `open` transition.
- **Last Invoice paid → Job completed** (Section 2.3) — Implemented in
  `Invoice.save()` → `_maybe_complete_job()`.
- **Task blocked → WorkOrder blocked** (Section 2.7) — Implemented in
  `TaskLifecycleService._check_wo_blocked()`.
- **Line item requirement on Estimate, Invoice, PurchaseOrder** (Sections 1.11,
  1.15, 1.16) — All four line item container types (Estimate, Invoice,
  PurchaseOrder, Bill) now enforce this in `clean()`.
- **Estimate accepted → WorkOrder created** (Section 2.5) — Manual step via
  `work_order_create_from_estimate` view. Uses
  `WorkOrderService.copy_from_worksheet` or generates tasks from line items.

### Remaining

- **Earmarks from Material creation on WorkOrder Tasks** (Section 2.6) —
  Adding an inventoried Material to a WO Task should trigger earmark
  creation. This replaces the current `auto_earmark_inventory` signal on
  estimate acceptance, which reads from worksheet materials. The new approach
  cascades naturally from the WorkOrder copy in 2.5.
- **Material addition on WorkOrder Tasks** — Adding Materials to Tasks on a
  WorkOrder is not yet supported in the UI/API. Needed for 2.6 to work.
