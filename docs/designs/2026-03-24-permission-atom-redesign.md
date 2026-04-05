# Permission Atom Redesign

**Date:** 2026-03-24 (revised 2026-04-05)
**Status:** Implemented
**Scope:** API permission atoms, DRF permission classes, group definitions, fixtures

**2026-04-05 revision:** `can_view_financials` was removed. All authenticated users can now read invoices, POs, and bills. Writes remain gated on `can_manage_financials`. Atom count: 5.

---

## Overview

Reorganize permission atoms to better reflect real-world access patterns:

- **Drop `can_view_jobs`** — all internal users can see jobs and the work tier. Reading jobs/work orders/tasks/contacts/etc. becomes `IsAuthenticated`.
- **Drop `can_manage_invoicing` and `can_manage_purchasing`** — merge into `can_manage_financials`.
- **Add `can_view_financials`** — gates read access to invoices, POs, bills, price list items.
- **Add `can_manage_financials`** — gates write access to the same.
- **Move group definitions** from data migration into fixture data.

Estimates remain part of the jobs workflow, not financials.

Customer/external access (object-level permissions for client contacts to approve/reject estimates on their own jobs) is deferred — not part of this work.

---

## Permission Atoms (5)

```python
class Meta:
    permissions = [
        ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks, contacts'),
        ('can_manage_financials', 'Can manage invoices, POs, bills, price list'),
        ('can_manage_time', "Can edit/delete anyone's time entries"),
        ('can_approve_expenses', 'Can approve/reject expenses over threshold'),
        ('can_manage_config', 'Can manage settings, templates, user admin'),
    ]
```

### Removed

| Old Atom | Disposition |
|----------|------------|
| `can_view_jobs` | Dropped — absorbed into `IsAuthenticated` |
| `can_manage_invoicing` | Merged into `can_manage_financials` |
| `can_manage_purchasing` | Merged into `can_manage_financials` |
| `can_view_financials` | Dropped 2026-04-05 — absorbed into `IsAuthenticated` |

### Coverage

| Atom | Gates |
|------|-------|
| `can_manage_jobs` | **Read+write:** emails. **Write:** jobs, work orders, worksheets, bundles, estimates, estimate line items, contacts, businesses, email-to-job linking, status transitions on all of the above. (Notes on jobs/contacts/businesses and adding tasks to work orders are `IsAuthenticated` — see above.) |
| `can_manage_financials` | **Write:** invoices, POs, bills, price list items, and their line items, status transitions (issue, cancel) |
| `can_manage_time` | **Edit/delete** anyone's time entries (shifts, bleps) |
| `can_approve_expenses` | **Approve/reject** expenses over threshold |
| `can_manage_config` | **Read+write:** settings, templates, line item types, user admin |

### Implicit (any authenticated user, no atom)

- Track own time (clock in/out, start/stop bleps)
- Submit own expenses
- View own expenses and time entries

### `IsAuthenticated` (any logged-in user, no atom)

Read access to:
- Jobs, job history
- Estimates, estimate line items
- Est worksheets, worksheet tasks/bundles
- Work orders, work order tasks/bundles/bleps
- Contacts, contact history
- Businesses, business history
- Payment terms
- Templates (work order, task)
- Line item types
- Search
- Price list items
- Invoices, invoice line items
- Purchase orders, PO line items
- Bills, bill line items

Write access to:
- Notes on jobs, contacts, and businesses
- Tasks on work orders (add tasks to existing work orders)

---

## API Endpoint-to-Atom Map

### `IsAuthenticated` — any logged-in user

| Endpoint | Method |
|----------|--------|
| `/api/jobs/` | GET |
| `/api/jobs/{id}/` | GET |
| `/api/jobs/{id}/history/` | GET |
| `/api/estimates/` | GET |
| `/api/estimates/{id}/` | GET |
| `/api/estimates/{id}/line-items/` | GET |
| `/api/est-worksheets/` | GET |
| `/api/est-worksheets/{id}/` | GET |
| `/api/est-worksheets/{id}/tasks/` | GET |
| `/api/est-worksheets/{id}/bundles/` | GET |
| `/api/work-orders/` | GET |
| `/api/work-orders/{id}/` | GET |
| `/api/work-orders/{id}/tasks/` | GET |
| `/api/work-orders/{id}/bundles/` | GET |
| `/api/work-orders/{id}/tasks/{tid}/bleps/` | GET |
| `/api/contacts/` | GET |
| `/api/contacts/{id}/` | GET |
| `/api/contacts/{id}/history/` | GET |
| `/api/businesses/` | GET |
| `/api/businesses/{id}/` | GET |
| `/api/businesses/{id}/history/` | GET |
| `/api/payment-terms/` | GET |
| `/api/payment-terms/{id}/` | GET |
| `/api/work-order-templates/` | GET |
| `/api/work-order-templates/{id}/` | GET |
| `/api/task-templates/` | GET |
| `/api/task-templates/{id}/` | GET |
| `/api/line-item-types/` | GET |
| `/api/line-item-types/{id}/` | GET |
| `/api/search/?q=...` | GET |
| `/api/price-list-items/` | GET |
| `/api/price-list-items/{id}/` | GET |
| `/api/invoices/` | GET |
| `/api/invoices/{id}/` | GET |
| `/api/invoices/{id}/line-items/` | GET |
| `/api/purchase-orders/` | GET |
| `/api/purchase-orders/{id}/` | GET |
| `/api/purchase-orders/{id}/line-items/` | GET |
| `/api/bills/` | GET |
| `/api/bills/{id}/` | GET |
| `/api/bills/{id}/line-items/` | GET |
| `/api/jobs/{id}/notes/` | POST |
| `/api/contacts/{id}/notes/` | POST |
| `/api/businesses/{id}/notes/` | POST |
| `/api/work-orders/{id}/tasks/` | POST |

### `can_manage_jobs`

| Endpoint | Method |
|----------|--------|
| `/api/emails/` | GET |
| `/api/emails/{id}/` | GET |
| `/api/jobs/` | POST |
| `/api/jobs/{id}/` | PUT, PATCH, DELETE |
| `/api/jobs/{id}/complete/` | POST |
| `/api/jobs/{id}/cancel/` | POST |
| `/api/jobs/{id}/reopen/` | POST |
| `/api/contacts/` | POST |
| `/api/contacts/{id}/` | PUT, PATCH, DELETE |
| `/api/businesses/` | POST |
| `/api/businesses/{id}/` | PUT, PATCH, DELETE |
| `/api/businesses/{id}/set-default-contact/` | POST |
| `/api/estimates/` | POST |
| `/api/estimates/{id}/` | PUT, PATCH, DELETE |
| `/api/estimates/{id}/line-items/` | POST |
| `/api/estimates/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/estimates/{id}/line-items/reorder/` | POST |
| `/api/estimates/{id}/mark-open/` | POST |
| `/api/estimates/{id}/revise/` | POST |
| `/api/est-worksheets/` | POST |
| `/api/est-worksheets/{id}/` | PUT, PATCH, DELETE |
| `/api/est-worksheets/{id}/tasks/` | POST |
| `/api/est-worksheets/{id}/tasks/{tid}/` | PATCH, DELETE |
| `/api/est-worksheets/{id}/bundles/` | POST |
| `/api/est-worksheets/{id}/bundles/{bid}/` | PATCH, DELETE |
| `/api/est-worksheets/{id}/bundles/{bid}/add-tasks/` | POST |
| `/api/est-worksheets/{id}/bundles/{bid}/remove-tasks/` | POST |
| `/api/est-worksheets/{id}/generate-estimate/` | POST |
| `/api/est-worksheets/{id}/revise/` | POST |
| `/api/work-orders/` | POST |
| `/api/work-orders/{id}/` | PUT, PATCH, DELETE |
| `/api/work-orders/{id}/tasks/{tid}/` | PATCH, DELETE |
| `/api/work-orders/{id}/bundles/` | POST |
| `/api/work-orders/{id}/bundles/{bid}/` | PATCH, DELETE |
| `/api/work-orders/{id}/bundles/{bid}/add-tasks/` | POST |
| `/api/work-orders/{id}/bundles/{bid}/remove-tasks/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/start/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/complete/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/block/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/unblock/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/cancel/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/start-work/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/stop-work/` | POST |
| `/api/work-orders/{id}/complete/` | POST |
| `/api/work-orders/{id}/block/` | POST |
| `/api/work-orders/{id}/reopen/` | POST |
| `/api/emails/{id}/link-to-job/` | POST |
| `/api/emails/{id}/unlink-from-job/` | POST |
| `/api/emails/{id}/create-job/` | POST |

### `can_manage_financials`

| Endpoint | Method |
|----------|--------|
| `/api/invoices/` | POST |
| `/api/invoices/{id}/` | PUT, PATCH, DELETE |
| `/api/invoices/{id}/line-items/` | POST |
| `/api/invoices/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/invoices/{id}/line-items/reorder/` | POST |
| `/api/invoices/{id}/cancel/` | POST |
| `/api/purchase-orders/` | POST |
| `/api/purchase-orders/{id}/` | PUT, PATCH, DELETE |
| `/api/purchase-orders/{id}/line-items/` | POST |
| `/api/purchase-orders/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/purchase-orders/{id}/line-items/reorder/` | POST |
| `/api/purchase-orders/{id}/issue/` | POST |
| `/api/purchase-orders/{id}/cancel/` | POST |
| `/api/bills/` | POST |
| `/api/bills/{id}/` | PUT, PATCH, DELETE |
| `/api/bills/{id}/line-items/` | POST |
| `/api/bills/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/bills/{id}/line-items/reorder/` | POST |
| `/api/bills/{id}/cancel/` | POST |
| `/api/price-list-items/` | POST |
| `/api/price-list-items/{id}/` | PUT, PATCH, DELETE |

### `can_manage_config`

| Endpoint | Method |
|----------|--------|
| `/api/settings/` | GET, PATCH |
| `/api/work-order-templates/` | POST |
| `/api/work-order-templates/{id}/` | PUT, PATCH, DELETE |
| `/api/task-templates/` | POST |
| `/api/task-templates/{id}/` | PUT, PATCH, DELETE |
| `/api/line-item-types/` | POST |
| `/api/line-item-types/{id}/` | PUT, PATCH, DELETE |

### `can_manage_time` (future — no endpoints yet)

Candidates: `/api/shifts/`, `/api/time-tracking/`, blep CRUD (if separated from task lifecycle)

### `can_approve_expenses` (future — no endpoints yet)

Candidates: `/api/expenses/`, expense approval actions

---

## Default Groups

Defined in fixture data (not migrations). Shops customize to suit their needs.

| Group | Atoms |
|-------|-------|
| Worker | *(none — IsAuthenticated covers read access)* |
| Admin | `can_manage_jobs` |
| Bookkeeper | `can_manage_financials`, `can_approve_expenses` |
| Manager | `can_manage_jobs`, `can_manage_financials`, `can_manage_time`, `can_approve_expenses` |
| Owner | all 5 atoms |

---

## DRF Permission Classes

```python
# apps/api/permissions.py

CanManageJobs = atom_permission('can_manage_jobs')
CanManageFinancials = atom_permission('can_manage_financials')
CanManageTime = atom_permission('can_manage_time')
CanApproveExpenses = atom_permission('can_approve_expenses')
CanManageConfig = atom_permission('can_manage_config')
```

Removed: `CanViewJobs`, `CanManageInvoicing`, `CanManagePurchasing`, `CanViewFinancials` (2026-04-05)

---

## Viewset Change Table

Explicit mapping of what changes per viewset:

| Viewset | Current Read | Target Read | Current Write | Target Write |
|---------|-------------|-------------|---------------|--------------|
| JobViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManageJobs` | mixed (see notes) |
| ContactViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageJobs` | mixed (see notes) |
| BusinessViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageJobs` | mixed (see notes) |
| PaymentTermsViewSet | `IsAuthenticated` | `IsAuthenticated` | *(read-only)* | *(read-only)* |
| EstimateViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManageJobs` | `CanManageJobs` |
| EstWorksheetViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManageJobs` | `CanManageJobs` |
| WorkOrderViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManageJobs` | mixed (see notes) |
| InvoiceViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManageInvoicing` | `CanManageFinancials` |
| PurchaseOrderViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManagePurchasing` | `CanManageFinancials` |
| BillViewSet | `CanViewJobs` | `IsAuthenticated` | `CanManagePurchasing` | `CanManageFinancials` |
| PriceListItemViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageInvoicing` | `CanManageFinancials` |
| WorkOrderTemplateViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageConfig` | `CanManageConfig` |
| TaskTemplateViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageConfig` | `CanManageConfig` |
| LineItemTypeViewSet | `IsAuthenticated` | `IsAuthenticated` | `CanManageConfig` | `CanManageConfig` |
| settings_view | `CanManageConfig` | `CanManageConfig` | `CanManageConfig` | `CanManageConfig` |
| email_list/detail | `IsAuthenticated` | `CanManageJobs` | — | — |
| email link/unlink/create-job | — | — | `CanManageJobs` | `CanManageJobs` |
| search_view | `IsAuthenticated` | `IsAuthenticated` | — | — |

**Mixed-permission viewset notes:**
- **JobViewSet** `notes` action: `IsAuthenticated` for POST (was `CanManageJobs`). All other writes stay `CanManageJobs`.
- **ContactViewSet** `notes` action: `IsAuthenticated` for POST (was `CanManageJobs`). All other writes stay `CanManageJobs`.
- **BusinessViewSet** `notes` action: `IsAuthenticated` for POST (was `CanManageJobs`). All other writes stay `CanManageJobs`.
- **WorkOrderViewSet** `tasks` action: `IsAuthenticated` for POST (add tasks). PATCH/DELETE on tasks and all other writes stay `CanManageJobs`.

**Viewsets that need code changes** (read or write permission differs):
- JobViewSet, EstimateViewSet, EstWorksheetViewSet, WorkOrderViewSet — read: `CanViewJobs` → `IsAuthenticated`
- JobViewSet, ContactViewSet, BusinessViewSet — `notes` action write: `CanManageJobs` → `IsAuthenticated`
- WorkOrderViewSet — `tasks` POST: `CanManageJobs` → `IsAuthenticated` (PATCH/DELETE unchanged)
- InvoiceViewSet — read: `CanViewJobs` → `CanViewFinancials`, write: `CanManageInvoicing` → `CanManageFinancials`
- PurchaseOrderViewSet, BillViewSet — read: `CanViewJobs` → `CanViewFinancials`, write: `CanManagePurchasing` → `CanManageFinancials`
- PriceListItemViewSet — write: `CanManageInvoicing` → `CanManageFinancials`
- email_list/detail — read: `IsAuthenticated` → `CanManageJobs`

---

## Implementation Steps

1. Update `User.Meta.permissions` — remove 3 old atoms (`can_view_jobs`, `can_manage_invoicing`, `can_manage_purchasing`), add 2 new atoms (`can_view_financials`, `can_manage_financials`)
2. Run `makemigrations` (schema only — do NOT run `migrate`)
3. Write a new data migration (0006) that:
   - Reverses the group creation from 0005 (deletes the old Worker/Manager/Bookkeeper/Admin groups)
   - Removes the old permission atoms (`can_view_jobs`, `can_manage_invoicing`, `can_manage_purchasing`) from any users/groups that have them
   - Does NOT create new groups (groups are now fixture/test-setup data, not migration data)
4. Update main fixture files in `fixtures/` — remove group definitions and old atom references from test user data. Group creation for tests moves into test class `setUp` methods.
   - Defer updating fixture files in `fixtures/` subfolders to a later pass.
5. Update `apps/api/permissions.py` — remove `CanViewJobs`, `CanManageInvoicing`, `CanManagePurchasing`; add `CanViewFinancials`, `CanManageFinancials`
6. Update viewset `get_permissions()` methods per the viewset change table above
7. Update `test_permissions.py` — atom existence tests (6 atoms not 7), factory tests (new classes), group tests (update to new group definitions or rework to test in setUp)
8. Update `test_atom_api_permissions.py` per the revised test plan
9. Update CLAUDE.md to reflect new atoms and groups

---

## Deferred

- **Customer/external access** — object-level permissions for client contacts to view/approve/reject estimates on their own jobs. Mechanism TBD (login vs. email link). Will be a separate design.
- **`can_manage_time` and `can_approve_expenses`** — atoms exist but no endpoints yet. Placeholder test classes reserved.
- **Stub endpoints** — `/api/emails/send/`, `/api/shifts/clock-in/`, `/api/shifts/clock-out/`, `/api/expenses/`, `/api/time-tracking/status/`, `/api/time-tracking/active/` all exist as 501 stubs. Will need atom assignments when implemented.
- **Fixture subfolders** — files in `fixtures/` subfolders need updating to match new atoms/groups but are deferred to a later pass.
