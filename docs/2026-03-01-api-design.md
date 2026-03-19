# API Design — Django Rest Framework

**Date:** 2026-03-01
**Status:** Draft

## Overview

REST API for Minibini using Django Rest Framework (DRF), enabling multiple front-end consumers: SPA (React/Vue/Svelte), mobile apps, and external integrations.

**Key principles:**
- Business logic stays in the Django backend (service classes, signals, model methods)
- PATCH for simple field edits; dedicated action endpoints for operations with side effects
- Action endpoints are tagged as **[routine]** (normal workflow) or **[exceptional]** (problem resolution, unusual circumstances — front-ends should put these behind confirmation dialogs or admin menus)
- Exceptional actions require a `reason` field
- Line items are never fetched standalone — always in context of their parent document

## Open Questions / Deferred

- **Authentication — kiosk/biometric:** Future requirement for quick physical auth at shared workstations (keycard tap, fingerprint). DRF's multiple auth backend support accommodates this — add a kiosk auth class that resolves a hardware credential to a user and issues a short-lived scoped token. No current design work needed, just don't preclude it.
- **Payment processing:** `record-payment` endpoints are placeholders. Will evolve significantly with Stripe integration. Expense reimbursement workflow also deferred to payments design.
- **Work Order / Job status overlap:** Work order status arguably *is* the job status from a business perspective. May consolidate later.
- **Audit trail — storage:** Middleware approach decided, but database schema for audit entries is TBD. Tracked changes, user notes, and action reasons all feed into the same history stream. Note edits and deletes are tracked as audit entries themselves.
- **Non-job time tracking:** Employees need to track time on non-job activities (training, maintenance, meetings). Approach TBD — could be a special "overhead" job, standalone categories, or something else.
- **Accounting module:** Decision pending on whether to build minimal internal accounting (bank import, reconciliation) or integrate with Xero/QuickBooks. Affects expense reconciliation and bank transaction matching.
- **Expense accounting categories:** To be added later.

---

## Authentication

Session auth for SPA, JWT for mobile/external. Username + password credentials (username is freeform — could be an email, but we don't treat it specially).

- `POST /api/auth/login/` — username + password → session cookie (SPA) or JWT access + refresh token pair (mobile/external)
- `POST /api/auth/logout/` — end session / invalidate token
- `GET /api/auth/me/` — current user info, permissions, groups
- `POST /api/auth/refresh/` — refresh JWT (mobile/external only)

**OAuth (optional):** Users can link an external provider (Google, Microsoft, etc.) as an alternative to username + password. Supported via `django-allauth`. Specific providers configured per deployment. OAuth and password login coexist — each user chooses their preference.

**Implementation:** Django's built-in session auth + `djangorestframework-simplejwt` + `django-allauth`. DRF configured with multiple authentication backends so all methods work simultaneously.

**Future:** Kiosk/biometric auth will be added as a separate DRF auth backend (see Open Questions).

---

## Permissions

Uses Django's built-in groups and permissions system. No custom role field on User — groups are just convenient bundles of permissions. The owner can assign individual permissions to any user beyond their group defaults.

### Permission Atoms

| Permission | Covers |
|---|---|
| `can_manage_jobs` | Full CRUD on jobs, estimates, worksheets, work orders, tasks, bundles |
| `can_view_jobs` | Read-only access to all jobs and related documents |
| `can_manage_invoicing` | Invoices, price list, send/payment actions |
| `can_manage_purchasing` | POs, bills, send/receive actions |
| `can_manage_time` | Edit/delete anyone's time entries (shifts + bleps) |
| `can_approve_expenses` | Approve/reject expenses over threshold |
| `can_manage_config` | Settings, templates, line item types, user admin |

### Implicit (no permission needed)

All authenticated users can:
- Track their own time (clock in/out, start/stop bleps)
- Submit expenses
- View their own time entries

### Default Groups

| Group | Permissions |
|---|---|
| Worker | `can_view_jobs` |
| Manager | `can_view_jobs`, `can_manage_jobs`, `can_manage_time`, `can_approve_expenses` |
| Bookkeeper | `can_view_jobs`, `can_manage_invoicing`, `can_manage_purchasing`, `can_approve_expenses` |
| Admin | All permissions |

Groups are starter bundles, not rigid roles. A user can belong to multiple groups and/or have individual permissions added directly. DRF permission classes check for the relevant permission regardless of how it was granted.

---

## Jobs

### CRUD
- `GET /api/jobs/` — list
- `POST /api/jobs/` — create
- `GET /api/jobs/{id}/` — retrieve (**rich response**, see below)
- `PATCH /api/jobs/{id}/` — update fields
- `DELETE /api/jobs/{id}/` — delete

### Rich Job Detail Response

`GET /api/jobs/{id}/` returns the job plus related objects. **Current/active** objects are returned in full; **historical** objects are returned as summaries (id, number, status, date, total) with links.

Full representations:
- Current/accepted estimate
- Active est worksheet (current version)
- Active work order (including all tasks and their bleps)
- Open invoices (unpaid)
- Open purchase orders (not fully received)
- Contact and business (always full, small objects)
- Associated email thread

Summary representations:
- Superseded/rejected/expired estimates
- Completed work orders
- Paid invoices
- Fully received / cancelled purchase orders

### Actions — [routine]
- `POST /api/jobs/{id}/complete/` — mark job completed

### Actions — [exceptional]
- `POST /api/jobs/{id}/cancel/` — requires `reason`
- `POST /api/jobs/{id}/reopen/` — requires `reason`

### History

Unified chronological feed combining audit trail entries (system-generated) and user notes. Audit entries are aggregated from the job and its related objects (estimates, worksheets, work orders, invoices, linked POs). User notes live on the job only. Action reasons from exceptional actions appear in the same stream.

- `GET /api/jobs/{id}/history/` — paginated, newest first. Each entry has a `type` (`audit`, `action`, `note`) and carries `object_type`/`object_id` to indicate which related object it pertains to.

### User Notes

Free-text notes attached to a job by any authenticated user. Permissions: author can edit/delete own notes; `can_manage_jobs` can delete any note.

- `POST /api/jobs/{id}/history/notes/` — add a note
- `PATCH /api/jobs/{id}/history/notes/{note_id}/` — edit own note
- `DELETE /api/jobs/{id}/history/notes/{note_id}/` — delete own, or any with `can_manage_jobs`

---

## Contacts & Businesses

### Contacts
- `GET/POST /api/contacts/` — list, create
- `GET/PATCH/DELETE /api/contacts/{id}/` — retrieve, update, delete

### Businesses
- `GET/POST /api/businesses/` — list, create
- `GET/PATCH/DELETE /api/businesses/{id}/` — retrieve, update, delete
- `POST /api/businesses/{id}/set-default-contact/` — **side effect: updates business.default_contact**

### Payment Terms
- `GET /api/payment-terms/` — list (read-only for API consumers)

### Deletion Note
Contact and business deletion has cascading implications (custom `delete()` methods handle reassignment). Delete endpoints should surface warnings: return a confirmation payload showing what will be affected, then require `?confirm=true` to proceed.

---

## EstWorksheets

### CRUD
- `GET/POST /api/est-worksheets/` — list, create (requires job, optional template — template populates tasks/bundles if provided)
- `GET/PATCH/DELETE /api/est-worksheets/{id}/` — retrieve, update fields, delete

### Actions — [routine]
- `POST /api/est-worksheets/{id}/generate-estimate/` — **major side effect: creates Estimate + line items from tasks/bundles**
- `POST /api/est-worksheets/{id}/revise/` — **side effect: creates new worksheet version**

### Tasks
- `POST /api/est-worksheets/{id}/tasks/` — add task (manually or from task template)
- `PATCH/DELETE /api/est-worksheets/{id}/tasks/{task_id}/` — update fields (including `mapping_strategy`), delete. **Note:** deleting a bundled task removes it from its bundle as a side effect.
- `POST /api/est-worksheets/{id}/tasks/reorder/` — reorder unbundled tasks (accepts ordered list of IDs)

### Bundles
- `GET/POST /api/est-worksheets/{id}/bundles/` — list, create (requires name + at least one task ID)
- `PATCH/DELETE /api/est-worksheets/{id}/bundles/{bundle_id}/` — update name, delete (**unbundles tasks** — tasks revert to direct, are not deleted)
- `POST /api/est-worksheets/{id}/bundles/{bundle_id}/add-tasks/` — move tasks into bundle, sets mapping_strategy to `bundle`
- `POST /api/est-worksheets/{id}/bundles/{bundle_id}/remove-tasks/` — unbundle tasks, reverts mapping_strategy to `direct`
- `POST /api/est-worksheets/{id}/bundles/{bundle_id}/reorder/` — reorder tasks within bundle

---

## Estimates

### CRUD
- `GET/POST /api/estimates/` — list, create (usually created via worksheet's `generate-estimate`)
- `GET/PATCH/DELETE /api/estimates/{id}/` — retrieve, update fields, delete. Response includes version chain references (previous/next version ID and number).

### Actions — [routine]
- `POST /api/estimates/{id}/send/` — send estimate to customer, transitions to open. **Immutable after this point.** Side effect: sends email to customer with PDF attachment.
- `POST /api/estimates/{id}/accept/` — **major side effect: updates parent job status**
- `POST /api/estimates/{id}/reject/` — **side effect: updates parent job status**
- `POST /api/estimates/{id}/revise/` — **side effect: supersedes this estimate, creates new version**

### Actions — [exceptional]
- `POST /api/estimates/{id}/expire/` — manually expire, requires `reason`
- `POST /api/estimates/{id}/cancel/` — requires `reason`

### Line Items
- `POST /api/estimates/{id}/line-items/` — add
- `PATCH/DELETE /api/estimates/{id}/line-items/{item_id}/` — update, delete
- `POST /api/estimates/{id}/line-items/reorder/` — reorder (accepts ordered list of IDs)

---

## Work Orders

### CRUD
- `GET/POST /api/work-orders/` — list, create (usually from accepted estimate, can be direct)
- `GET/PATCH/DELETE /api/work-orders/{id}/` — retrieve, update fields, delete

### Actions — [routine]
- `POST /api/work-orders/{id}/complete/` — mark complete
- `POST /api/work-orders/{id}/block/` — mark as blocked, requires `reason`

### Actions — [exceptional]
- `POST /api/work-orders/{id}/cancel/` — requires `reason`
- `POST /api/work-orders/{id}/reopen/` — requires `reason`

### Tasks
- `POST /api/work-orders/{id}/tasks/` — add task
- `PATCH/DELETE /api/work-orders/{id}/tasks/{task_id}/` — update, delete
- `POST /api/work-orders/{id}/tasks/reorder/` — reorder
- `POST /api/work-orders/{id}/tasks/{task_id}/assign/` — assign to a user

### Bundles
- `POST /api/work-orders/{id}/bundles/` — create (name + at least one task)
- `PATCH/DELETE /api/work-orders/{id}/bundles/{bundle_id}/` — update name, delete (unbundles)
- `POST /api/work-orders/{id}/bundles/{bundle_id}/add-tasks/`
- `POST /api/work-orders/{id}/bundles/{bundle_id}/remove-tasks/`
- `POST /api/work-orders/{id}/bundles/{bundle_id}/reorder/`

### Bleps (time tracking)
- `POST /api/work-orders/{id}/tasks/{task_id}/bleps/` — add time entry
- `PATCH/DELETE /api/work-orders/{id}/tasks/{task_id}/bleps/{blep_id}/` — update, delete

---

## Invoicing

### Invoices
- `GET/POST /api/invoices/` — list, create
- `GET/PATCH/DELETE /api/invoices/{id}/` — retrieve, update fields, delete

### Actions — [routine]
- `POST /api/invoices/{id}/send/` — send to customer, transitions to open (immutable after). Sends email with PDF attachment.
- `POST /api/invoices/{id}/record-payment/` — record payment (`amount`, `payment_date`). Partial → `partly-paid`, full → `paid-in-full`. **Placeholder — will evolve with Stripe integration.**

### Actions — [exceptional]
- `POST /api/invoices/{id}/cancel/` — requires `reason`
- `POST /api/invoices/{id}/supersede/` — replace with corrected invoice, requires `reason`

### Line Items
- `POST /api/invoices/{id}/line-items/` — add
- `PATCH/DELETE /api/invoices/{id}/line-items/{item_id}/` — update, delete
- `POST /api/invoices/{id}/line-items/reorder/` — reorder

### Price List
- `GET/POST /api/price-list-items/` — list, create
- `GET/PATCH/DELETE /api/price-list-items/{id}/` — retrieve, update, delete

---

## Purchasing

### Purchase Orders
- `GET/POST /api/purchase-orders/` — list, create
- `GET/PATCH/DELETE /api/purchase-orders/{id}/` — retrieve, update fields, delete

### Actions — [routine]
- `POST /api/purchase-orders/{id}/issue/` — send to vendor, transitions to issued. Sends email with PDF attachment.
- `POST /api/purchase-orders/{id}/receive/` — record receipt with line-item-level quantities. Backend calculates partial vs full receipt and sets status accordingly. For "received in full", the UI sends all quantities.

### Actions — [exceptional]
- `POST /api/purchase-orders/{id}/cancel/` — requires `reason`

### Line Items
- `POST /api/purchase-orders/{id}/line-items/` — add
- `PATCH/DELETE /api/purchase-orders/{id}/line-items/{item_id}/` — update, delete
- `POST /api/purchase-orders/{id}/line-items/reorder/` — reorder

### Bills
- `GET/POST /api/bills/` — list, create (often from a PO)
- `GET/PATCH/DELETE /api/bills/{id}/` — retrieve, update fields, delete

### Bill Actions — [routine]
- `POST /api/bills/{id}/receive/` — mark bill as received
- `POST /api/bills/{id}/record-payment/` — placeholder, same pattern as invoices. Bills carry the check number on their payment record when paid by check.

### Bill Actions — [exceptional]
- `POST /api/bills/{id}/cancel/` — requires `reason`
- `POST /api/bills/{id}/refund/` — requires `reason`

### Bill Line Items
- `POST /api/bills/{id}/line-items/` — add
- `PATCH/DELETE /api/bills/{id}/line-items/{item_id}/` — update, delete
- `POST /api/bills/{id}/line-items/reorder/` — reorder

---

## Email

### Inbox
- `GET /api/emails/` — list inbox (paginated). Fetching happens via background task (every ~5 minutes), not triggered by this endpoint.
- `GET /api/emails/{id}/` — view email detail/content

### Sending
- `POST /api/emails/send/` — universal outbound endpoint. Handles replies, new emails, and document sends.
  - `to`, `cc`, `bcc` — recipient addresses
  - `subject`, `body` — content (user-editable, pre-populated from boilerplate for document sends)
  - `thread_reference` (optional) — message ID of email being replied to. Server sets `In-Reply-To` and `References` headers for threading.
  - `document_type` + `document_id` (optional) — generates PDF attachment for estimate/invoice/PO
  - `job`, `purchase_order`, `bill` (optional) — association slots. When sending a document, auto-associates with the document's parent job.

### Email Templates (boilerplate)
- `GET/PATCH /api/email-templates/{type}/` — manage boilerplate per document type (estimate, invoice, po). UI fetches boilerplate, lets user edit, submits via send endpoint.

### Association
An email can be associated with up to 3 objects independently: 0-1 Jobs, 0-1 POs, 0-1 Bills.

- `POST /api/emails/{id}/link-to-job/` — link to a job
- `POST /api/emails/{id}/unlink-from-job/`
- `POST /api/emails/{id}/link-to-po/`
- `POST /api/emails/{id}/unlink-from-po/`
- `POST /api/emails/{id}/link-to-bill/`
- `POST /api/emails/{id}/unlink-from-bill/`
- `POST /api/emails/{id}/create-job/` — **side effect: creates Job + links email**

### Auto-association
Incoming emails are automatically associated with existing jobs/POs/bills using:
1. **Email headers (primary):** `In-Reply-To` and `References` headers matched against message IDs of emails already in the system. Follows the thread back to the associated objects.
2. **Subject line parsing (fallback):** Regex matching for document numbers (`JOB-2026-0042`, `PO-2026-0015`, etc.) in the subject line.

Auto-association is silent — no user confirmation required. Users can un-associate manually if needed.

---

## Time Tracking

### Shifts (clock in/out)
Job-agnostic attendance tracking. A shift is "I'm at work," not tied to any specific job.

- `POST /api/shifts/clock-in/` — start a shift for the current user
- `POST /api/shifts/clock-out/` — end current shift. **Side effect: stops any running blep.**
- `GET /api/shifts/` — list shifts (filterable by user, date range)
- `GET /api/shifts/{id}/` — shift detail, includes bleps that fell within it
- `PATCH /api/shifts/{id}/` — edit (manual time corrections)

### Bleps (task timers)
Task-level time tracking. A blep must fall within a shift. Only one active blep per user at a time.

- `POST /api/work-orders/{wo_id}/tasks/{task_id}/start/` — start timer. **Side effect: stops any running blep for this user.** Requires active shift.
- `POST /api/work-orders/{wo_id}/tasks/{task_id}/stop/` — stop timer
- `POST /api/work-orders/{wo_id}/tasks/{task_id}/bleps/` — add manual time entry (after-the-fact logging)
- `PATCH/DELETE /api/work-orders/{wo_id}/tasks/{task_id}/bleps/{blep_id}/` — edit, delete

### Status & Dashboard
- `GET /api/time-tracking/status/` — current user's state: active shift (if any) and active blep (if any). Front-end uses this to show "you're clocked in, working on Task X."
- `GET /api/time-tracking/active/` — manager view: all currently active shifts and bleps across all users. **Requires permission.**

### Deferred
- **Non-job time tracking:** Employees need to track time on activities not tied to a job (training, maintenance, meetings). Approach TBD.

---

## Expenses

### CRUD
- `GET/POST /api/expenses/` — list, create
- `GET/PATCH/DELETE /api/expenses/{id}/` — retrieve, update, delete

**Fields:** amount, description, date, submitted_by (user), job (optional), payment_method (credit_card / employee_out_of_pocket / cash)

### Receipt Upload
- `POST /api/expenses/{id}/upload-receipt/` — upload receipt image

### Approval — [routine]
Expenses under a configurable threshold are auto-approved. Over threshold requires role-based approval.

- `POST /api/expenses/{id}/approve/` — approve expense. **Requires approval permission.**
- `POST /api/expenses/{id}/reject/` — requires `reason`

### Rules
- **Checks always go through Bills**, not expenses. A check implies a payee, which is what Bills capture with their vendor/contact relationship.
- Bills carry the check number on their payment record.

### Duplicate Detection
On creation of a Bill or Expense, the system checks for matches on amount + date and flags potential duplicates to the user.

### Deferred
- Reimbursement workflow (pending payments design)
- Bank import / reconciliation (pending accounting module decision)
- Accounting categories

---

## Inventory

- `GET/POST /api/inventory-items/` — list, create
- `GET/PATCH/DELETE /api/inventory-items/{id}/` — retrieve, update, delete

Straightforward CRUD for now. Inventory adjustments (waste, corrections) may need action endpoints later.

---

## Search

- `GET /api/search/?q=term&category=jobs,estimates` — cross-model search via SearchService

---

## Templates (reference data)

### Work Order Templates
- `GET/POST /api/work-order-templates/` — list, create
- `GET/PATCH/DELETE /api/work-order-templates/{id}/` — retrieve, update, delete
- `POST /api/work-order-templates/{id}/associations/` — add task template association
- `PATCH/DELETE /api/work-order-templates/{id}/associations/{assoc_id}/` — update, delete
- `POST /api/work-order-templates/{id}/associations/reorder/` — reorder

### Task Templates
- `GET/POST /api/task-templates/` — list, create
- `GET/PATCH/DELETE /api/task-templates/{id}/` — retrieve, update, delete

---

## Configuration

- `GET/PATCH /api/settings/` — read/update system configuration (number sequences, tax rates, email settings)
- `GET/POST /api/line-item-types/` — list, create
- `GET/PATCH/DELETE /api/line-item-types/{id}/` — retrieve, update, delete
