# Financials list views — design spec

**Date:** 2026-06-12
**Branch:** feature/financial-views
**Status:** Approved design, pre-implementation

## Goal

Give `can_manage_financials` users standalone list views for **Invoices** (A/R)
and **Bills** (A/P), grouped with **Expenses** under a new "Financials" sidebar
section. Build a minimal **Bill detail** page so bill rows have somewhere to
land, and extract a reusable **CustomerPicker** typeahead for filtering by
customer/vendor. POs stay where they are.

This is the "lists down and viewable" pass. Richer per-document views (bill
editing, invoice list polish, a possible `/financials` hub page) come later.

## Scope

**In scope**

- New sidebar "Financials" section (Invoices, Bills, Expenses) above "Admin".
- Invoice list page (`/invoices`) — new.
- Bill list page (`/bills`) — new.
- Bill detail page (`/bills/:id`) — new, **interactive** (see "Bill editing").
- **Bill editing** — header form (new + edit), draft line-item CRUD, status
  lifecycle actions, draft delete. New.
- `CustomerPicker` shared component — new.
- Backend: list serializers + filtering (status presets, due-date range) +
  ordering for invoices and bills; balance/total/customer fields; a
  `BillService.update_bill` header-update method + viewset `perform_update`;
  expanded bill `status_actions`.

**Out of scope (future / later passes)**

- A `/financials` hub/landing page with at-a-glance totals (the "option 3"
  submenu idea). May revisit.
- **All Bill ↔ QBO integration** — the `send-to-qbo` action endpoint already
  exists but the new UI does not surface it; bill QBO push, payment sync, and
  the `partly_paid` status (which needs a paid amount we don't track yet) all
  wait for a later pass.
- Invoice detail-page changes (already exists; untouched here).
- Refactoring `ContactPicker` / `JobPicker` into a generic typeahead.
- Tracking bill partial-payment amounts (see "Bill balance is lossy" below).

## Navigation

Edit `frontend/src/components/Sidebar.svelte`. New section label **above** the
existing Admin label. Section label + items render only when
`$canManageFinancials`.

```
Home
Jobs               → /jobs/board
Schedule
Activity
Contacts
Email
Purchasing         → /purchase-orders        (unchanged, above the line)
─── Financials ───  (label only if can_manage_financials)
Invoices           → /invoices               (NEW)
Bills              → /bills                   (NEW)
Expenses           → /expenses               (MOVED from Admin)
─── Admin ───       (label only if can_manage_config)
Users              → /users
Settings           → /settings
[spacer]
LITE | FULL
─────────────
<username>         → /profile
Logout
```

- Expenses relocates from the Admin group into Financials. Admin shrinks to
  Users + Settings.
- The existing Admin label currently shows if the user has *any* admin perm;
  after this change the Financials label is its own `$canManageFinancials`
  gate and the Admin label is its own `$canManageConfig` gate. Verify the
  combined-label logic so a financials-only user sees Financials (not Admin)
  and a config-only user sees Admin (not Financials).

## CustomerPicker (new shared component)

`frontend/src/components/CustomerPicker.svelte`. A dual-source typeahead for
selecting a customer **or** vendor — the same control reused across financials
filters (and intended for "so many other places" later).

- On input, fire **both** `/api/contacts/?search=` and
  `/api/businesses/?search=` in parallel (the merge pattern already used by
  `ContactListPage.loadAll`), `page_size=10` each.
- Merge results, tag each with its type, render with a type hint, e.g.
  `Acme Co. (business)` and `Jane Roe — Acme Co. (contact)`.
- Emit a selection of shape `{ type: 'business' | 'contact', id }`. Bindable
  `value` plus an `onSelect` callback, matching house picker conventions
  (Svelte 5 runes; `onmousedown` on result rows; blur-delay to allow clicks).
- A clear/change affordance to reset the selection.
- Leave `ContactPicker` and `JobPicker` untouched.

Consumers translate the emitted `{ type, id }` into the API's two optional
params: `?business=<id>` when `type === 'business'`, `?contact=<id>` when
`type === 'contact'`. (Two params, not a combined one — leaves room to AND
them later.)

## Balance semantics

### Invoice balance — clean

- `total` = sum of line items (`qty * price`).
- `amount_paid` = `Invoice.qbo_amount_paid` (existing field; may be null → 0).
- `balance` = `total - amount_paid`.

### Bill balance — lossy (decision: ship coarse now)

`Bill` has **no amount-paid field** (only `qbo_payment_status`, a string), so a
`partly_paid` bill's remaining balance is unknown. Approach (a), accepted:

- `total` = sum of line items.
- `balance` = `total` for `draft` / `received` / `partly_paid`; `0` for
  `paid_in_full` / `cancelled` / `refunded`.
- A `partly_paid` bill therefore **overstates** its balance. Footnote the Bill
  list's Balance column: "partial payments not yet tracked."
- The real fix — add `qbo_amount_paid` to `Bill` — is deferred until bill QBO
  payment sync lands. Noted in `materials-inventory-and-purchasing.md` §13 (the
  "forthcoming" QBO area) and `docs/designs/LATER.md`.

## Backend

### Invoice list endpoint (`/api/invoices/`)

`apps/api/invoicing/views.py` + `apps/api/invoicing/serializers.py`.

- **List serializer** (new lightweight `InvoiceSummarySerializer`, do **not**
  ship nested `line_items` in list responses). Fields:
  `invoice_id`, `invoice_number`, `status`, `job`, `job_number`, `job_name`,
  `customer_name` (job's business name, else contact name), `sent_date`,
  `due_date`, `is_late` (reuse existing serializer-method logic),
  `total`, `amount_paid`, `balance`.
- `InvoiceViewSet.list` uses the summary serializer; `retrieve` keeps the full
  `InvoiceSerializer`.
- **Filters** (extend `get_queryset`, which today only handles `?job=`):
  - `?status=` preset: `open` (→ `open` + `partly-paid`), `paid`, `draft`,
    `cancelled`, `all`. Default when absent: **open**.
  - `?business=<id>` → invoices whose `job.contact.business_id` matches
    (business rolls up all its contacts' invoices).
  - `?contact=<id>` → invoices whose `job.contact_id` matches (exact).
  - `?due_from=` / `?due_to=` → range on the derived due date. Due date =
    `sent_date + 30d`; null `sent_date` rows are excluded from a bounded range
    and sort last otherwise.
- **Ordering** `?ordering=`: `due_date` (default, ascending; nulls last),
  `-due_date`, `-balance`, `-total`, `customer_name`, `-sent_date`.
  Default = due_date ascending so the most-overdue row is on top.
- **Implementation note:** invoice due date is **derived, not a DB column**
  (`sent_date + 30d`), so the ORM cannot filter/order on it directly. Implement
  the due-date filter/sort against `sent_date` — annotate
  `due_date = sent_date + timedelta(30)` (e.g. `ExpressionWrapper` /
  `F('sent_date') + ...`) and filter/order on the annotation, or equivalently
  shift the bounds (`sent_date` between `due_from - 30d` and `due_to - 30d`).
  `balance` and `total` are also computed (sum of line items minus paid), so
  ordering by them likewise needs an annotation, not a plain field sort.

### Bill list endpoint (`/api/bills/`)

`apps/api/purchasing/views.py` + `apps/api/purchasing/serializers.py`.

- **List serializer** — extend `BillSummarySerializer` (today:
  `bill_id, status, vendor_invoice_number, created_date, contact_name,
  po_number`). Add: `vendor_name` (business name), `due_date`,
  `received_date`, `total`, `balance`.
- **Filters** (`get_queryset` already supports `?business=` / `?contact=`):
  - `?status=` preset: `open` (→ `received` + `partly_paid`), `paid`
    (→ `paid_in_full`), `draft`, `cancelled`, `refunded`, `all`. Default:
    **open**.
  - `?business=<id>` / `?contact=<id>` already work — exact match on the bill's
    own FK (a bill links a business directly).
  - `?due_from=` / `?due_to=` → range on `due_date` (null sorts last).
- **Ordering** `?ordering=`: `due_date` (default ascending; nulls last),
  `-due_date`, `-balance`, `-total`, `vendor_name`, `-received_date`.

### Bill detail + write endpoints

`BillViewSet.retrieve` already returns `BillSerializer`. Confirm it serializes
header fields, the linked PO (number + id), line items, and a `balance` (add
the coarse balance to `BillSerializer` too so the detail page matches the list).

Write plumbing to add/verify (mirror `PurchaseOrderService` / `PurchaseOrderViewSet`):

- **`BillService.update_bill(pk, **kwargs)`** — new; draft-only header update
  via `_validate_draft`, mirroring `PurchaseOrderService.update_po`. Editable
  header fields: `business`, `contact`, `vendor_invoice_number`, `due_date`.
  (`purchase_order` link is set at creation and shown read-only this pass;
  changing it post-create is an edge case, deferred.) Re-runs `Bill.clean()`
  (business/contact-belongs-to-business validation already lives there).
- **`BillViewSet.perform_update`** — new override delegating to
  `BillService.update_bill` (today PATCH falls through to the default DRF
  `serializer.save()`, bypassing the service — fix this to match the
  viewset-delegates-to-service convention).
- **`BillSerializer`** — ensure `business`, `contact`, `vendor_invoice_number`,
  `due_date`, `purchase_order` are writable on create; `vendor_invoice_number` /
  `business` / `contact` / `due_date` writable on update. Header writes are
  draft-only (enforced in the service).
- **Line-item PLI routing** — the catalog ("From Price List") add must route to
  `BillService.add_line_item_from_pli(bill_id, price_list_item_id, qty)` when
  the POST carries `price_list_item`, mirroring how the invoice line-item add
  handles catalog vs. manual. Verify `LineItemMixin` passes the kwarg through,
  or override `line_items` POST as the invoice viewset does.
- **`status_actions`** — extend beyond the existing `cancel`:
  - `receive` → `draft → received` (the model's `clean()` already blocks this
    with zero line items).
  - `mark-paid` → `received → paid_in_full` (stamps `paid_date`; coarse balance
    drops to 0). `partly_paid` is **not** exposed (no paid-amount tracking;
    waits for QBO). `paid_in_full → refunded` also deferred.
  - Keep `cancel` (`requires_reason: True`).
  All status actions stay `IsAuthenticated + CanManageFinancials`.
- **`send-to-qbo`** action is left in place but **not** wired into the new UI.

### Permissions

- Invoice and Bill **list/retrieve reads stay `IsAuthenticated`** (unchanged).
  The sidebar gate (`can_manage_financials`) is the discovery control; the
  pages additionally guard on `$canManageFinancials` and show a not-authorized
  state on deep-link by a non-financials user.
- All Bill **writes** (create, update, line-item CRUD, status actions, delete)
  require `CanManageFinancials` — already the case in `BillViewSet.get_permissions`
  and `LineItemMixin`. No invoice write endpoints added in this pass.

## Frontend pages

Conventions: follow existing list pages (`PurchaseOrderListPage`,
`ExpenseListPage`) — `.data-table`, `lib/pagination.js` helpers, status
`<select>`, `api.js` GET, row link/button to detail. Detail/form pages follow
`InvoiceDetailPage` (line items) and `PurchaseOrderDetailPage` /
`PurchaseOrderFormPage` (status actions, two-mode form).

New routes to register in `App.svelte`:

| Route | Component |
|---|---|
| `/invoices` | `routes/invoices/InvoiceListPage.svelte` |
| `/bills` | `routes/bills/BillListPage.svelte` |
| `/bills/new` | `routes/bills/BillFormPage.svelte` (new mode) |
| `/bills/:id` | `routes/bills/BillDetailPage.svelte` |
| `/bills/:id/edit` | `routes/bills/BillFormPage.svelte` (edit mode) |

### Invoice list (`/invoices` → `routes/invoices/InvoiceListPage.svelte`)

Columns: **Invoice #** (link → `/invoices/:id`) · **Job** (link → `/jobs/:id`)
· **Customer** · **Status** · **Sent** · **Due** (late flag when `is_late`) ·
**Amount** · **Paid** · **Balance**.

Filter bar: status `<select>` (default Open) · due-date range (two date
inputs) · `CustomerPicker`. Sort `<select>` (default Due ↑). Pagination.

### Bill list (`/bills` → `routes/bills/BillListPage.svelte`)

Columns: **Vendor Inv #** (link → `/bills/:id`) · **Vendor** · **PO #**
(link → `/purchase-orders/:id` when present) · **Status** · **Received** ·
**Due** · **Amount** · **Balance** (footnoted re: partial payments).

Filter bar: status `<select>` (default Open) · due-date range · `CustomerPicker`.
Sort `<select>` (default Due ↑). Pagination. **New Bill** button
(`can_manage_financials` only) → `/bills/new`.

### Bill form (`/bills/new` and `/bills/:id/edit` → `routes/bills/BillFormPage.svelte`)

Header create + edit, mirroring `PurchaseOrderFormPage` (new + edit modes in
one page). Fields: vendor (business) + optional contact — reuse
`PurchaseOrderForm`'s business/contact selection pattern; `vendor_invoice_number`;
`due_date`. New mode optionally accepts `?po=<id>` to pre-link a PO (routes
`perform_create` through `create_bill_from_po`). Edit mode is draft-only — for a
non-draft bill, the page shows the header read-only with a "received bills can't
be edited" note. A **"New Bill"** button on the Bill list (financials-only)
links here.

> Judgment call (flag for review): standalone "New Bill" creation was cut in the
> first scope pass, but it falls out almost free here — `PurchaseOrderFormPage`
> is a direct two-mode template and `create_bill` already backs it, and an AP
> Bills list with no create affordance is awkward. Included; trim if unwanted.

### Bill detail (`/bills/:id` → `routes/bills/BillDetailPage.svelte`)

Interactive, mirroring `InvoiceDetailPage` (line items) and
`PurchaseOrderDetail` (status actions). Header: vendor (business), vendor
invoice #, linked PO (link to PO detail when present), status, dates
(created / due / received / paid / cancelled), **Balance** (footnoted re:
partial payments). Bill-level history panel if the existing purchasing history
surface applies (PO detail has one).

- **Edit header** — "Edit" link → `/bills/:id/edit`, shown only on `draft`
  bills to `can_manage_financials`.
- **Line items** — `.data-table` (description, qty, units, price, line total).
  On `draft` bills, `can_manage_financials` users add / edit / delete / reorder
  via the shared **`LineItemModal.svelte`** (same modal as estimates/invoices —
  manual entry or "From Price List" catalog mode). Bill lines have no job /
  material linkage (unlike PO lines), so the simpler invoice-style modal fits;
  no `JobPicker`. Deletes go through the renumber service (already the case in
  `BillService.delete_line_item`).
- **Status actions** — buttons reflecting the bill state machine:
  - `draft`: **Mark Received** (disabled with a hint until ≥1 line item),
    **Delete** (draft-only, irreversible → confirm).
  - `received`: **Mark Paid in Full**, **Cancel** (Cancel requires a reason).
  - terminal (`paid_in_full` / `cancelled` / `refunded`): no actions.
  - `partly_paid` not reachable from the UI this pass.
  No "Send to QBO" button (deferred).

## Reuse notes

- `CustomerPicker` is the deliberately-reusable artifact; structure it to drop
  into estimates/jobs/PO contexts later. Keep it config-free at the call site
  (no entity-type prop needed — it always searches both).
- Reuse `lib/pagination.js`, `.data-table`, and the status-`<select>` pattern
  from `PurchaseOrderListPage` rather than re-rolling.
- The dual-fetch merge logic mirrors `ContactListPage.loadAll`; lift the shape,
  not the page.

## Testing (TDD)

**Backend** (`tests/`, `python manage.py test` — one runner at a time):

- Invoice list: default status filter = open(+partly-paid); each preset;
  `business` rollup vs. `contact` exact; due-date range; ordering incl.
  due-ascending-nulls-last; `total`/`amount_paid`/`balance`/`customer_name`
  correctness (incl. null `qbo_amount_paid` → 0).
- Bill list: status presets (open = received+partly_paid; paid =
  paid_in_full); `business`/`contact`; due-date range; ordering; coarse balance
  per status (partly_paid → full total; paid_in_full → 0).
- Bill detail: balance present and matches list.
- Bill editing (service + viewset):
  - `BillService.update_bill` updates header on draft; **rejects** non-draft
    (raises like the other `_validate_draft` services); re-runs `clean()`
    (contact-belongs-to-business).
  - `perform_update` routes PATCH through the service (a header PATCH on a
    non-draft bill 400s, doesn't silently save).
  - Line-item add (manual + PLI), edit, delete-with-renumber, reorder — all
    draft-only; non-draft attempts rejected.
  - `status_actions`: `receive` blocked with zero line items, allowed with ≥1;
    `mark-paid` stamps `paid_date` and zeroes balance; `cancel` requires reason;
    invalid transitions (e.g. `draft → paid_in_full`) rejected by `clean()`.
  - Write actions require `CanManageFinancials` (403 without).

**Frontend** (`frontend/`, Vitest, `npm run test:run`):

- `CustomerPicker`: dual-source merge + tagging; emits `{type,id}`; clear.
- Invoice/Bill list pages: render rows, default filters applied, sort/filter
  controls wire to query params, customer picker → correct param, row links;
  Bill list "New Bill" button gated on `canManageFinancials`.
- Bill detail: renders header + line items + balance; PO link conditional;
  edit/line-item/status controls present only on the right status + permission;
  status buttons call the right endpoints; Mark Received disabled with no lines.
- Bill form: new + edit modes; edit blocked/read-only for non-draft.

## Docs to update (same session as implementation)

- `docs/designs/invoicing-and-expenses.md` — replace "Standalone invoice list
  page … No `#/invoices/` route today" with the shipped list; add the
  Financials nav grouping.
- `docs/designs/materials-inventory-and-purchasing.md` — add the Bill list,
  detail, and form surfaces + the editing flow (`BillService.update_bill`,
  expanded `status_actions`) to §13 / §15; the `qbo_amount_paid`-needed note in
  §13's "forthcoming" QBO area is already added.
- `docs/designs/architecture-and-conventions.md` §8 — update the sidebar link
  list with the Financials section.
- `docs/designs/LATER.md` — "track bill partial-payment amounts (add
  `Bill.qbo_amount_paid`) when bill QBO payment sync lands."
- `frontend/README.md` if it catalogs shared components — add `CustomerPicker`.

## Open questions

None outstanding. Naming locked: section = "Financials", component =
`CustomerPicker`.
