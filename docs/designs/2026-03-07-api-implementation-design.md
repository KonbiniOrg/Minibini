# API Implementation Design

**Date:** 2026-03-07
**Status:** Approved
**Prerequisite docs:** `2026-03-07-service-mediated-saves.md`, `2026-03-07-permissions-design.md`
**Reference spec:** `docs/2026-03-01-api-design.md`

---

## Overview

REST API for Minibini using Django Rest Framework (DRF). Coexists with the existing HTML front-end — both call the same service layer. The API lives entirely under `/api/` and is cleanly separated from the HTML views.

### Key Decisions

- **Approach C (Hybrid):** Single `apps/api/` app with per-domain submodules
- **Session auth only** for now; JWT and OAuth stubbed at 501
- **`IsAuthenticated` only** for permissions initially; full permission atoms are a separate task
- **All writes go through services** — never inline model saves in API views (prerequisite: service-mediated saves refactor)
- **Serializers return raw model data** — computed/derived values (totals, etc.) are the SPA's responsibility. Exception: fields requiring server-side data the SPA doesn't have (e.g., tax rates from Configuration), handled case-by-case.
- **Full URL tree from day one** — unimplemented endpoints return 501
- **Progressive Job detail enrichment** — start flat, add nested serializers incrementally without breaking changes

### Prerequisites (do before API implementation)

1. **Service-mediated saves refactor** — HTML views call services for all writes (see `2026-03-07-service-mediated-saves.md`)
2. **App reorganization** — models in correct apps, fresh migrations (separate planning session)
3. **Permissions structure** — groups + atoms created (see `2026-03-07-permissions-design.md`; can be done in parallel with API work since API uses `IsAuthenticated` initially)

---

## Directory Structure

```
apps/api/
    __init__.py
    urls.py                  # Full URL tree — all includes in one place
    permissions.py           # IsAuthenticated for now; permission atoms later
    mixins.py                # StatusTransitionMixin, LineItemMixin, TaskBundleMixin
    pagination.py            # Shared pagination config
    auth/
        __init__.py
        serializers.py
        views.py             # login, logout, me (session auth)
        urls.py              # JWT refresh, OAuth → 501 stubs
    jobs/
        __init__.py
        serializers.py
        views.py
    contacts/
        __init__.py
        serializers.py
        views.py
    estimates/
        __init__.py
        serializers.py
        views.py
    worksheets/
        __init__.py
        serializers.py
        views.py
    work_orders/
        __init__.py
        serializers.py
        views.py
    invoicing/
        __init__.py
        serializers.py
        views.py
    purchasing/
        __init__.py
        serializers.py
        views.py
    templates_config/        # WO/task templates + line item types + settings
        __init__.py
        serializers.py
        views.py
    inventory/
        __init__.py
        serializers.py
        views.py
    search/
        __init__.py
        views.py
    email/
        __init__.py
        serializers.py
        views.py             # Inbox, detail, create-job, link/unlink → real
                             # Send, templates, link-to-po/bill → 501 stubs
    time_tracking/
        __init__.py
        urls.py              # All routes → 501 stubs
    expenses/
        __init__.py
        urls.py              # All routes → 501 stubs
```

---

## Project-Level Wiring

One line added to `minibini/urls.py`:

```python
path('api/', include('apps.api.urls')),
```

All existing HTML view routes unchanged.

---

## Authentication

Session auth only. DRF configured with `SessionAuthentication` as the sole backend. The existing dev auto-login middleware works — it sets `request.user` on the session, which DRF reads.

### Endpoints

- `POST /api/auth/login/` — username + password, returns session cookie
- `POST /api/auth/logout/` — ends session
- `GET /api/auth/me/` — current user info

### Stubs (501)

- `POST /api/auth/refresh/` — JWT (future)
- OAuth routes (future, via django-allauth)

---

## Shared Mixins

Three patterns repeat across nearly every domain. Implemented as mixin classes in `apps/api/mixins.py`.

### LineItemMixin

Used by: Estimates, Invoices, POs, Bills

Adds line-item CRUD actions to any document viewset. Subclasses declare:
- `line_item_serializer_class`
- `line_item_model`
- `parent_field` (FK name on the line item)

Provides:
- `POST /{id}/line-items/` — create
- `PATCH /{id}/line-items/{item_id}/` — update
- `DELETE /{id}/line-items/{item_id}/` — delete (via `LineItemService.delete_line_item_with_renumber()`)
- `POST /{id}/line-items/reorder/` — reorder (via `LineItemService.reorder_line_items()`)

### StatusTransitionMixin

Used by: every document type for status transitions.

Subclasses declare a `status_actions` dict:

```python
status_actions = {
    'send':   {'service': EstimateService.send_estimate},
    'accept': {'service': EstimateService.accept_estimate},
    # Exceptional — requires reason
    'expire': {'service': EstimateService.expire_estimate, 'requires_reason': True},
    'cancel': {'service': EstimateService.cancel_estimate, 'requires_reason': True},
}
```

The mixin auto-registers `@action` endpoints from this dict. If `requires_reason` is true, validates that `reason` is present in the request body before calling the service. Front-ends can use this metadata to decide which actions need confirmation dialogs.

### TaskBundleMixin

Used by: EstWorksheets, WorkOrders

Adds task + bundle CRUD actions. Subclasses declare:
- `task_serializer_class`
- `bundle_serializer_class`
- `task_model`
- `parent_field`

Provides:
- Tasks: add, update, delete, reorder
- Bundles: create, update name, delete (unbundles tasks), add-tasks, remove-tasks, reorder

---

## Serializer Strategy

- **Serializers wrap models.** They expose model fields, not computed values. The SPA computes totals and derived display values.
- **One serializer per model** for basic CRUD.
- **Nested read serializers** for progressive Job detail enrichment — start flat, add nested serializers over time without breaking consumers.
- **Line item serializers** follow a base pattern specialized per document type, mirroring the `BaseLineItem` model abstraction.

---

## Service Reuse

API views delegate to existing services — never duplicate business logic.

| API Action | Existing Service |
|---|---|
| `generate-estimate` | `EstimateGenerationService.generate_estimate_from_worksheet()` |
| `create work order` | `WorkOrderService.create_from_estimate()` |
| Line item delete | `LineItemService.delete_line_item_with_renumber()` |
| Line item reorder | `LineItemService.reorder_line_items()` |
| Document numbering | `NumberGenerationService.generate_next_number()` |
| Tax calculation | `TaxCalculationService` |
| Email inbox/detail | `EmailService.fetch_new_emails()`, `get_email_content()` |
| Search | `SearchService.search()` |
| All field updates | Domain-specific service methods (post service-mediated saves refactor) |

---

## URL Routing

Full URL tree in `apps/api/urls.py` using DRF's `DefaultRouter` for standard CRUD viewsets. Action endpoints use `@action` decorators.

Nested routes (line items, tasks, bundles, bleps under parents) use `@action` on parent viewsets rather than `drf-nested-routers` — the nesting is shallow (max 2 levels) and the patterns are handled by mixins.

---

## Response Format

Standard DRF conventions, no custom envelope.

### Single Object

```json
{"id": 1, "job_number": "JOB-2026-0042", "status": "approved", ...}
```

### Paginated List

```json
{"count": 47, "next": "...?page=2", "previous": null, "results": [...]}
```

Page-number pagination, default page size 25.

### Action Response

Returns the updated object after the action is applied.

### Error Responses

```json
// Validation error (400)
{"field_name": ["This field is required."], "other_field": ["Invalid value."]}

// Non-field validation error (400)
{"non_field_errors": ["Cannot transition from 'draft' to 'accepted'."]}

// Permission denied (403)
{"detail": "You do not have permission to perform this action."}

// Not found (404)
{"detail": "Not found."}

// Not implemented (501)
{"detail": "Not yet implemented.", "endpoint": "POST /api/shifts/clock-in/"}
```

### Deletion Confirmation

For contacts and businesses, `DELETE` without `?confirm=true` returns an impact summary instead of deleting:

```json
// DELETE /api/contacts/5/
{"confirm_required": true, "impact": {"jobs": 3, "estimates": 7, "invoices": 2}}

// DELETE /api/contacts/5/?confirm=true
// 204 No Content (actually deletes)
```

**Note:** This pattern may be expanded to other object types and/or refined. Design is provisional — revisit when the broader deletion UX is worked out.

---

## Implementation Scope

### Fully Implemented (First Pass)

Endpoints backed by existing models and services:

- **Jobs** — CRUD + complete/cancel/reopen actions
- **Contacts & Businesses** — CRUD + set-default-contact + deletion confirmation
- **Payment Terms** — read-only list
- **EstWorksheets** — CRUD + tasks + bundles + generate-estimate + revise
- **Estimates** — CRUD + line items + send/accept/reject/revise/expire/cancel
- **Work Orders** — CRUD + tasks + bundles + complete/block/cancel/reopen
- **Invoices** — CRUD + line items + send/record-payment/cancel/supersede
- **Purchase Orders** — CRUD + line items + issue/receive/cancel
- **Bills** — CRUD + line items + receive/record-payment/cancel/refund
- **Price List Items** — CRUD
- **Inventory Items** — CRUD
- **Search** — cross-model search via SearchService
- **Email** — inbox list, detail, create-job-from-email, link/unlink job
- **Templates** — WO templates, task templates, associations
- **Configuration** — settings, line item types
- **Auth** — session login/logout/me

### 501 Stubs (URL Exists, Returns Not Implemented)

- **Auth:** JWT refresh, OAuth
- **Payment Terms:** create, update, delete
- **Email:** send, email templates, link-to-po/bill, unlink-from-po/bill
- **Time Tracking:** all endpoints (shifts, bleps start/stop, status, active dashboard)
- **Expenses:** all endpoints (CRUD, receipt upload, approve/reject)
- **Job History:** history feed + user notes (needs audit trail model, TBD)
- **Bleps on work order tasks:** manual CRUD exists but start/stop timer doesn't

---

## Dependencies

- `djangorestframework` — core API framework
- No other third-party packages required for first pass (no `drf-nested-routers`, no `simplejwt` yet)
