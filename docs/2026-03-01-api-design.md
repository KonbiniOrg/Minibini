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

- **Authentication:** Needed but deferred. Will need to support SPA sessions + token auth for mobile/external.
- **Payment processing:** `record-payment` endpoints are placeholders. Will evolve significantly with Stripe integration.
- **Work Order / Job status overlap:** Work order status arguably *is* the job status from a business perspective. May consolidate later.
- **Email fetch:** Synchronous for now, may need to become async if IMAP performance is a concern.
- **Audit trail:** Planned via middleware, not per-endpoint. Exceptional actions capture `reason` as explicit user-provided data separate from the audit trail.

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
- Active work order (one per job)
- Open invoices (unpaid)
- Open purchase orders (not fully received)
- Contact and business (always full, small objects)

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
- `POST /api/estimates/{id}/send/` — send estimate to customer, transitions to open. **Immutable after this point.** Side effect: will eventually trigger delivery to customer.
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
- `POST /api/invoices/{id}/send/` — send to customer, transitions to open (immutable after)
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
- `POST /api/purchase-orders/{id}/issue/` — send to vendor, transitions to issued
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
- `POST /api/bills/{id}/record-payment/` — placeholder, same pattern as invoices

### Bill Actions — [exceptional]
- `POST /api/bills/{id}/cancel/` — requires `reason`
- `POST /api/bills/{id}/refund/` — requires `reason`

### Bill Line Items
- `POST /api/bills/{id}/line-items/` — add
- `PATCH/DELETE /api/bills/{id}/line-items/{item_id}/` — update, delete
- `POST /api/bills/{id}/line-items/reorder/` — reorder

---

## Email

- `GET /api/emails/` — list inbox (TempEmail, paginated)
- `GET /api/emails/{id}/` — view email detail/content
- `POST /api/emails/{id}/link-to-job/` — associate email with a job. **Side effect: creates permanent EmailRecord.**
- `POST /api/emails/{id}/unlink-from-job/` — remove association
- `POST /api/emails/{id}/create-job/` — **side effect: creates Job + links email to it**
- `POST /api/emails/fetch/` — trigger IMAP fetch for new emails. Synchronous for now; may need async if performance is a concern.

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
