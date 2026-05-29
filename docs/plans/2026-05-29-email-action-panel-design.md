# Email action panel + PO/Bill associations — design spec

**Status:** Draft, ready for review.
**Date:** 2026-05-29
**Scope:** add Purchase Order and Bill associations on `EmailRecord` (FKs +
endpoints + UI), unify the existing per-email actions into a right-rail
side panel on the email detail page, add dedicated Create-from-Email
wizard pages for PO and Bill that share a sender-resolution sub-component
with the existing Create-Job-from-Email page. Out of scope: the Bill
creation form itself (`#/bills/new` is the future-page placeholder we
navigate to after the Contact/Business is resolved), picker scaling /
recency-sort across all three picker pages (in LATER.md), outbound email
tracking.

---

## 1. Problem

The email detail page exposes three actions today as a flat link strip:

> ← Back to Inbox | Create Job from this Email | Associate with Existing Job

`EmailRecord.job` is the only target — there's no equivalent for
Purchase Order or Bill, even though a vendor email is just as likely to
result in a PO (a customer-supplied quote we need to convert) or a Bill
(an incoming vendor invoice). The user wants symmetric Create + Associate
actions for all three targets, grouped into a single side rail.

Constraint that shapes the UX: `Business.default_contact` is a required
FK. A vendor Business cannot exist without a Contact pointing at a real
person (typically a sales rep). So the Contact+Business resolution
flow that the Create-Job-from-Email page already runs is structurally
correct for Create-PO and Create-Bill too — the sender is the natural
Contact, the sender's company is the natural Business / vendor.

## 2. Data model

`EmailRecord` gains two FKs paralleling the existing `job`:

```python
purchase_order = models.ForeignKey(
    'purchasing.PurchaseOrder', on_delete=models.SET_NULL,
    null=True, blank=True, related_name='email_records',
)
bill = models.ForeignKey(
    'purchasing.Bill', on_delete=models.SET_NULL,
    null=True, blank=True, related_name='email_records',
)
```

One migration, both fields. The three associations (`job`,
`purchase_order`, `bill`) are independent — any combination is valid, the
user decides which apply. `EmailRecordSerializer` exposes
`purchase_order` + `po_number` (read-only via FK traversal) and `bill` +
`vendor_invoice_number` alongside the existing `job` / `job_number`.

## 3. Service layer

`EmailService.associate_with_job` / `disassociate_from_job` exist today.
Rather than copy-paste them four more times, refactor to a single
parameterized pair:

```python
EmailService.associate_with(email_pk, target_field, target_pk)
EmailService.disassociate_from(email_pk, target_field)
```

`target_field` is one of `'job' | 'purchase_order' | 'bill'`. The service
validates the field against an allowlist and resolves the target model
from it; one method does the EmailRecord lookup, the target lookup, the
assignment, and `save()`. `NotFoundError` semantics unchanged.

The existing `associate_with_job` / `disassociate_from_job` methods stay
as thin shims that delegate to the new pair so existing callers
(`link_to_job`, `unlink_from_job`, `create_job_from_email`) don't all
churn.

## 4. API endpoints

Five new endpoints under `/api/emails/<int:pk>/`, paralleling the
existing `link-to-job` / `unlink-from-job` / `create-job`:

| Endpoint | Body | Permission |
|---|---|---|
| `POST link-to-po/` | `{po_id}` | `IsAuthenticated, CanManageFinancials` |
| `POST unlink-from-po/` | — | `IsAuthenticated, CanManageFinancials` |
| `POST link-to-bill/` | `{bill_id}` | `IsAuthenticated, CanManageFinancials` |
| `POST unlink-from-bill/` | — | `IsAuthenticated, CanManageFinancials` |
| `POST create-po/` | `{vendor_business_id}` | `IsAuthenticated, CanManageFinancials` |

The link / unlink view bodies mirror the existing job versions almost
line-for-line; extract a `_link_email_to(target_field, target_model,
body_key, request, pk)` helper in `apps/api/email/views.py` so the three
pairs share code. `create-po/` mirrors `create_job_from_email`: validate
`vendor_business_id`, call `PurchaseOrderService` to create a PO with
only the vendor populated (line items get added on the PO detail page),
call `EmailService.associate_with(email_pk, 'purchase_order', po.pk)`,
return `{po_id, po_number}`.

No `create-bill/` endpoint this round. `EmailCreateBillPage` resolves
the Contact+Business via the existing `/api/contacts/` and
`/api/businesses/` endpoints, then navigates to `#/bills/new?email=<id>
&vendor=<business_id>`. The Bill creation page (future work) will be
responsible for creating the Bill and calling `link-to-bill` itself.

## 5. SPA architecture

### 5.1 New shared sub-component

`frontend/src/components/email/SenderResolutionForm.svelte`. Encapsulates
the "sender info display + existing-contact pick or new-contact form +
business mode (none / existing / new)" sub-flow that
`EmailCreateJobPage.svelte` runs today. Props: `senderInfo` (already
fetched by the parent), submit-callback that receives a resolved
`{contactId, businessId}`. The component handles its own internal state
(selected mode, new-contact form values, business mode) and exposes
only the resolved IDs to the parent on submit.

`EmailCreateJobPage.svelte` is refactored to mount this component and
add its trailing Job-name + Description fields above the submit row.
Behavior is unchanged for users.

### 5.2 New pages

| Route | Component | Behavior |
|---|---|---|
| `/email/:id/create-po` | `EmailCreatePOPage.svelte` | Loads `sender-info`, mounts `SenderResolutionForm`. On submit (after Contact/Business resolution), POST `/api/emails/:id/create-po/` with `{vendor_business_id}`. Redirects to `#/purchase-orders/<po_id>`. |
| `/email/:id/create-bill` | `EmailCreateBillPage.svelte` | Loads `sender-info`, mounts `SenderResolutionForm`. On submit, ensures Contact/Business via existing endpoints, then `push('#/bills/new?email=<id>&vendor=<business_id>')`. Does **not** call `link-to-bill` — the placeholder Bill page will. |
| `/email/:id/associate-po` | `EmailAssociatePOPage.svelte` | Mirrors `EmailAssociatePage.svelte` (job picker). Loads `/api/purchase-orders/?page_size=100`, dropdown, on submit POSTs `link-to-po`. |
| `/email/:id/associate-bill` | `EmailAssociateBillPage.svelte` | Same shape against `/api/bills/?page_size=100`. |

The 100-cap is the known shortcoming captured in LATER.md (along with
the recency-sort question per entity).

### 5.3 New panel component

`frontend/src/components/email/EmailActionPanel.svelte` — right-side
rail on the email detail page. Props: `emailRecord` (so it knows which
targets are already linked), `onChange` (called after a successful
link/unlink/create so the parent can refetch).

Section per target (Job, Purchase Order, Bill). Per-target row layout:

- **When linked** (e.g. `emailRecord.job` is set):
  ```
  Job
    Linked: JOB-2026-0042   [Disassociate]
  ```
  `JOB-2026-0042` is an `<a href="#/jobs/<id>">` for quick navigation;
  Disassociate is a `<button>` (state change, no navigation).

- **When not linked:**
  ```
  Job
    [Create new]   [Link existing]
  ```
  Both are `<a>`s with `use:link` (they navigate to a form); styled to
  read like buttons so the panel is visually consistent. The
  "Links navigate, buttons act" project convention is satisfied at the
  semantic-element level, not by visual style.

Per-target rows are hidden entirely when the user lacks the relevant
permission atom:

- Job actions require `can_manage_jobs`
- PO and Bill actions require `can_manage_financials`

A superuser sees all three.

### 5.4 Email detail page changes

`frontend/src/routes/email/EmailDetailPage.svelte` mounts
`EmailActionPanel` to the right of `EmailContent` (right rail, full
height of the content area). The current inline "Create Job from this
Email | Associate with Existing Job" link strip and the Disassociate
button next to "Linked to job" are removed — both are now in the panel.

### 5.5 API client additions

`frontend/src/lib/email.js` gains:

- `linkToPo(emailId, poId)` → `POST /api/emails/<id>/link-to-po/` with
  `{po_id}`
- `unlinkFromPo(emailId)` → `POST /api/emails/<id>/unlink-from-po/`
- `linkToBill(emailId, billId)`
- `unlinkFromBill(emailId)`
- `createPo(emailId, payload)` → `POST /api/emails/<id>/create-po/`

## 6. Permissions summary

| Action | Atom |
|---|---|
| Job actions (Create / Associate / Disassociate) | `can_manage_jobs` |
| PO actions | `can_manage_financials` |
| Bill actions | `can_manage_financials` |

Backend endpoints enforce via DRF permission classes. The SPA hides
per-target rows when the atom is missing — defense-in-depth, not the
authority.

## 7. Tests

- **`tests/test_email_models.py`** — `EmailRecord.purchase_order` and
  `EmailRecord.bill` FK round-trips; SET_NULL behavior when the target
  is deleted.
- **`tests/test_email_models.py`** (service layer) —
  `EmailService.associate_with` happy paths for all three target
  fields, reject-unknown-field, target-not-found, email-not-found.
  Backwards-compat smoke test that `associate_with_job` still works
  through the shim.
- **`tests/test_api_email.py`** —
  - `link-to-po` / `unlink-from-po` happy path, 404 missing email,
    404 missing PO, 400 bad payload, 403 without `CanManageFinancials`.
  - Same for `link-to-bill` / `unlink-from-bill`.
  - `create-po` happy path: PO row exists after, email is linked,
    response has `{po_id, po_number}`.
  - `EmailRecordSerializer` list response includes `purchase_order` +
    `po_number` and `bill` + `vendor_invoice_number`.
- **SPA** — no JS test runner; manual verification per target on the
  email detail page:
  - Panel shows Create + Link when unlinked, Linked + Disassociate when
    linked.
  - Create PO wizard prefills vendor from sender.
  - Create Bill navigates to `#/bills/new?email=<id>&vendor=<id>`
    (Bill page itself is the deferred stub).
  - Per-permission row hiding for users without the atom.

## 8. Files touched

| File | Change |
|---|---|
| `apps/core/models.py` | Add `EmailRecord.purchase_order`, `EmailRecord.bill` |
| `apps/core/services.py` | `EmailService.associate_with` / `disassociate_from`; existing job methods become shims |
| `apps/api/email/views.py` | Five new endpoints; `_link_email_to` helper |
| `apps/api/email/urls.py` | Register the five new paths |
| `apps/api/email/serializers.py` | Add `purchase_order`, `po_number`, `bill`, `vendor_invoice_number` |
| `frontend/src/components/email/SenderResolutionForm.svelte` | **new** |
| `frontend/src/components/email/EmailActionPanel.svelte` | **new** |
| `frontend/src/routes/email/EmailDetailPage.svelte` | Mount `EmailActionPanel`; drop inline action links |
| `frontend/src/routes/email/EmailCreateJobPage.svelte` | Refactor to wrap `SenderResolutionForm` |
| `frontend/src/routes/email/EmailCreatePOPage.svelte` | **new** |
| `frontend/src/routes/email/EmailCreateBillPage.svelte` | **new** |
| `frontend/src/routes/email/EmailAssociatePOPage.svelte` | **new** |
| `frontend/src/routes/email/EmailAssociateBillPage.svelte` | **new** |
| `frontend/src/App.svelte` | Register four new routes |
| `frontend/src/lib/email.js` | Five new methods |
| `tests/test_email_models.py` | FK round-trip + parameterized service tests |
| `tests/test_api_email.py` | Five-endpoint coverage + serializer assertions |
| migration | Auto-generated for the two new FKs |

## 9. Docs to update post-implementation

- `docs/designs/users-and-permissions.md` — extend the endpoint→atom
  table with the five new endpoints (all `can_manage_financials`).
- `docs/designs/data-constraints.md` — note the new `EmailRecord` FKs
  alongside the existing `job`.

## 10. Deferred / explicitly out of scope

1. **Bill creation form (`#/bills/new`)** — placeholder URL that
   `EmailCreateBillPage` navigates to after creating/resolving the
   Contact+Business. The Bill page itself is future work; it should
   read `?email=<id>&vendor=<business_id>`, create the Bill (with line
   items etc.), then call `POST /api/emails/<id>/link-to-bill/` to
   associate with the email. Tracked externally.
2. **Picker scaling + recency sort** — Job, PO, and Bill association
   pickers all use `?page_size=100` with each list endpoint's default
   ordering. Existing LATER.md note covers it (and now also captures
   the per-entity "which lifecycle date implies recent" decision).
3. **Outbound email** — the action panel doesn't surface
   compose/reply. Still deferred to a separate spec.
