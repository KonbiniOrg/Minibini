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
- Minimal Bill detail page (`/bills/:id`) — new, read-only.
- `CustomerPicker` shared component — new.
- Backend: list serializers + filtering (status presets, due-date range) +
  ordering for invoices and bills; balance/total/customer fields.

**Out of scope (future / later passes)**

- A `/financials` hub/landing page with at-a-glance totals (the "option 3"
  submenu idea). May revisit.
- Bill editing, bill line-item CRUD UI, "New Bill" creation flow from the list.
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

### Bill detail endpoint

`BillViewSet.retrieve` already returns `BillSerializer`. Confirm it serializes
header fields, the linked PO (number + id), line items, and a `balance` (add
the coarse balance to `BillSerializer` too so the detail page matches the list).

### Permissions

- Invoice and Bill **list/retrieve reads stay `IsAuthenticated`** (unchanged).
  The sidebar gate (`can_manage_financials`) is the discovery control; the
  pages additionally guard on `$canManageFinancials` and show a not-authorized
  state on deep-link by a non-financials user.
- No write endpoints added in this pass.

## Frontend pages

Conventions: follow existing list pages (`PurchaseOrderListPage`,
`ExpenseListPage`) — `.data-table`, `lib/pagination.js` helpers, status
`<select>`, `api.js` GET, row link/button to detail. Register routes in
`App.svelte`.

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
Sort `<select>` (default Due ↑). Pagination.

### Bill detail — minimal (`/bills/:id` → `routes/bills/BillDetailPage.svelte`)

Read-only. Header: vendor (business), vendor invoice #, linked PO (link to the
PO detail when present), status, dates (created / due / received / paid),
**Balance**. Read-only line-items table (`.data-table`: description, qty,
units, price, line total). No edit/line-item CRUD this pass — note in-page or
in docs that editing is the next pass.

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

**Frontend** (`frontend/`, Vitest, `npm run test:run`):

- `CustomerPicker`: dual-source merge + tagging; emits `{type,id}`; clear.
- Invoice/Bill list pages: render rows, default filters applied, sort/filter
  controls wire to query params, customer picker → correct param, row links.
- Bill detail: renders header + line items + balance; PO link conditional.

## Docs to update (same session as implementation)

- `docs/designs/invoicing-and-expenses.md` — replace "Standalone invoice list
  page … No `#/invoices/` route today" with the shipped list; add the
  Financials nav grouping.
- `docs/designs/materials-inventory-and-purchasing.md` — add the Bill list +
  minimal Bill detail surfaces (§15-ish); add the `qbo_amount_paid`-needed note
  in §13's "forthcoming" QBO area.
- `docs/designs/architecture-and-conventions.md` §8 — update the sidebar link
  list with the Financials section.
- `docs/designs/LATER.md` — "track bill partial-payment amounts (add
  `Bill.qbo_amount_paid`) when bill QBO payment sync lands."
- `frontend/README.md` if it catalogs shared components — add `CustomerPicker`.

## Open questions

None outstanding. Naming locked: section = "Financials", component =
`CustomerPicker`.
