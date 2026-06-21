# Entity-picker consolidation & searchable type-aheads — design

_Spec — 2026-06-20_

## Problem

Entity selection across the SPA is inconsistent. Several places that pick a
**contact / business / job / purchase order / bill** from a long, growing list
use a plain `<select>` with no search — the worst being the **new-PO and new-Bill
forms** (every contact/business listed) and the three **email-association pages**
(`?page_size=500` silently capped at 100 by `StandardPagination`, so older rows
are unreachable).

Where type-aheads *do* exist they were each built at a different time with no
shared contract:

- `ContactPicker` — `value` is a bare id; has prefill-by-id + a Change/Cancel flow.
- `JobPicker` — `value` is a partial object `{job_id, job_number}`; Clear only.
- `CustomerPicker` — dual contact+business, `value` is `{type, id}`.
- `PriceListItemPicker` — full-row "fill-in" picker; client-side filtering over the
  whole catalog (`page_size=9999`).
- `PurchaseOrderPicker` — fetches one vendor's POs, then client-side filters.

This spec standardizes the **single-model "reference" pickers** onto one generic
component, upgrades inventory selection to server-side search, and adds the missing
`?search=` API endpoints.

## Scope decisions (settled during brainstorming)

- **Two intents, kept as two components.** Most consumers only need an **id + a
  display label** ("reference"). One — `PriceListItemPicker` — needs the **whole
  row** to auto-fill a form ("fill-in"). Both are satisfied by the same output
  contract, but the fill-in picker stays a **separate component** rather than being
  folded into the generic one.
- **`CustomerPicker` is out of scope** — it searches two models and emits
  `{type, id}`; left untouched.
- **Business-scoped sub-lists stay plain `<select>` pulldowns.** A set already
  narrowed to one business (a business's contacts; a vendor's POs) is never large
  enough to need search. This *removes* one existing type-ahead: BillFormPage's
  vendor-scoped PO field reverts to a pulldown and `PurchaseOrderPicker` is retired.
- **The generic picker needs no scoping prop.** After the rule above, every
  generic-picker site is a **global** search (business, job, contact, PO, bill).
- **Inventory merge conversion is out of scope.** The `InventoryListPage` merge
  keep/discard selects are left to the dedicated merge-UX-rework note in
  `LATER.md` (row-driven selection + before-commit preview). This spec only makes
  the inventory picker *capable* (server search + a general `params` filter) so the
  future rework can drop it in cleanly; it does not touch `InventoryListPage`.
- **No shared inner widget.** `EntityPicker` and `InventoryItemPicker` will
  duplicate ~30 lines of dropdown markup. That duplication is acceptable; do not
  extract a shared presentational component for it now.

## Output contract (shared by EntityPicker + InventoryItemPicker)

- `value` — **bindable id** (number) or `null`. This is what forms submit.
- `selectedItem` — optional **full object** the parent already has, used to render
  the selected label on edit **without** a resolve fetch.
- `onSelect(fullRow | null)` — fires on every selection change, handing back the
  **whole row** (or `null` on clear). Fill-in consumers read everything off this;
  reference consumers can ignore it.

Reference consumers bind `value`; if they also display a number/name they read it
from `selectedItem`/`onSelect`. The fill-in consumer ignores `value` and reads
`onSelect(fullRow)`.

## Components after the reorg

### 1. `EntityPicker.svelte` (new — generic single-model reference picker)

**Props**

| Prop | Type | Notes |
|---|---|---|
| `model` | required string | one of `'business' \| 'job' \| 'contact' \| 'purchase_order' \| 'bill'` |
| `value` | bindable number \| null | the selected id |
| `selectedItem` | object \| null | optional prefill object (skip resolve fetch) |
| `onSelect` | `(row \| null) => void` | optional |
| `disabled` | boolean | |
| `placeholder` | string | optional override |

**Internal registry** maps each `model` to its endpoint, id field, and label
function:

| model | endpoint | idField | label(row) |
|---|---|---|---|
| `business` | `/api/businesses/` | `business_id` | `business_name` |
| `contact` | `/api/contacts/` | `contact_id` | `name` (+ ` — {business.business_name}` when present) |
| `job` | `/api/jobs/` | `job_id` | `{job_number} — {name/description}` |
| `purchase_order` | `/api/purchase-orders/` | `po_id` | `{po_number} — {business.business_name}` |
| `bill` | `/api/bills/` | `bill_id` | `{vendor_invoice_number or PO#} — {business.business_name}` |

**Behavior**

- On input (debounced ~250 ms), `GET <endpoint>?search=<q>&page_size=10`; render
  results in a focus/blur dropdown listbox (the UI pattern from the current
  `PriceListItemPicker` — it is the most complete).
- When `value` is set with no matching `selectedItem`, resolve the label via
  `GET <endpoint><id>/` (mirrors `ContactPicker`'s prefill-by-id `$effect`).
- Selected state shows the label + a **Change/Clear** affordance.
- `pick()` sets `value = row[idField]`, calls `onSelect(row)`.

**Retires:** `ContactPicker.svelte`, `JobPicker.svelte`, `PurchaseOrderPicker.svelte`.

### 2. `InventoryItemPicker.svelte` (renamed from `PriceListItemPicker.svelte`)

Kept separate — its consumers need the full row (`description`, `units`,
`selling_price`/`price`, `accounting_category`, `is_inventoried`, on-hand/earmark
fields).

**Changes**

- **Rename** the component (model was renamed `PriceListItem` → `InventoryItem`;
  the component name never followed). Update all five imports.
- **Server-side search:** replace the client-side filter over
  `GET /api/inventory/?page_size=9999&is_active=true` with
  `GET /api/inventory/?search=<q>` (debounced), fulfilling the existing TODO in the
  file. Keep the focus/blur dropdown UI, the `selectedItem` prefill, the
  `onSelect(fullRow)` callback, and the existing "None (freeform)" option.
- **New `params` prop** — extra query filters merged into the search call (e.g.
  `is_active=true`, or `is_catalog=false`). General capability, not merge-specific.

> Note: this picker is left functionally as-is apart from rename + server search +
> `params`. No merge-specific changes (no `allowFreeform` prop). The merge keep/
> discard selects are **not** converted in this spec.

### 3. `CustomerPicker.svelte` — unchanged.

## Backend: add `?search=`

`contacts`, `businesses`, `jobs` already implement `?search=` by hand in
`get_queryset` (no DRF `SearchFilter`). Mirror that pattern — do **not** introduce
`SearchFilter` — in:

| Viewset | File | Search fields (case-insensitive `icontains`, OR'd) |
|---|---|---|
| `PurchaseOrderViewSet` | `apps/api/purchasing/views.py` | `po_number`, `business__business_name` |
| `BillViewSet` | `apps/api/purchasing/views.py` | `vendor_invoice_number`, `purchase_order__po_number`, `business__business_name` |
| `InventoryItemViewSet` | `apps/api/inventory/views.py` (`/api/inventory/`) | `code`, `description` |

Each adds, inside the existing `get_queryset`:

```python
search = self.request.query_params.get('search', '').strip()
if search:
    qs = qs.filter(Q(<field1>__icontains=search) | Q(<field2>__icontains=search) | ...)
```

Both PO and Bill viewsets already read a `business` query param in `get_queryset`,
so the `search` block slots in alongside it.

## Call-site migration

| Site | Today | After |
|---|---|---|
| `PurchaseOrderForm` business | raw `<select>` | `EntityPicker model="business"` |
| `PurchaseOrderForm` contact | raw `<select>` (business-scoped) | **stays pulldown** |
| `BillFormPage` business | raw `<select>` | `EntityPicker model="business"` |
| `BillFormPage` contact | raw `<select>` (scoped) | **stays pulldown** |
| `BillFormPage` PO | `PurchaseOrderPicker` (vendor-scoped typeahead) | **plain pulldown** of vendor POs |
| `ContactForm` business | raw `<select>` | `EntityPicker model="business"` |
| `EmailAssociatePage` job | raw `<select>` (`page_size=500`, capped) | `EntityPicker model="job"` |
| `EmailAssociatePOPage` PO | raw `<select>` | `EntityPicker model="purchase_order"` |
| `EmailAssociateBillPage` bill | raw `<select>` | `EntityPicker model="bill"` |
| `DuplicateJobPage` contact | `ContactPicker` | `EntityPicker model="contact"` |
| `ExpenseForm` job | `JobPicker` | `EntityPicker model="job"` |
| `LineItemForm` (PO) job | `JobPicker` | `EntityPicker model="job"` |
| `PurchaseOrderDetail` job ×2 | `JobPicker` | `EntityPicker model="job"` |
| `LineItemModal`, `MaterialModal`, `PlanMaterialModal`, `MaterialPicker`, `LineItemForm` material | `PriceListItemPicker` | `InventoryItemPicker` (rename only) |

**`JobPicker`-consumer refactor.** The three job sites currently round-trip
`value = {job_id, job_number}` (so they can redisplay the number on edit without a
fetch). They switch to `value = <id>` and pass the existing record as `selectedItem`
for edit-mode prefill. Touches `ExpenseForm.svelte`, PO `LineItemForm.svelte`,
`PurchaseOrderDetail.svelte` — including the spots that reconstruct
`{job_id, job_number}` from `expense.job` / `li.effective_job_id`.

**Removing the `page_size=500` loads.** The three email-associate pages stop
bulk-loading their lists; the picker fetches on demand. The bug where older rows are
unreachable past 100 is fixed as a side effect.

## Out of scope (unchanged)

- All enum-ish `<select>`s: status, units, payment method/terms, accounting
  category, templates, rate schemes, user lists (Assign / TimeEdit / Expense
  purchased-by / JobEdit PM — bounded by worker count), list-page status/ordering
  filters.
- `CustomerPicker`.
- `InventoryListPage` merge keep/discard — deferred to the merge-UX-rework note.
- The future job-scoped "attach to existing material" picker — will be a pulldown.

## Testing

**Backend (TDD).** A test per new `?search=` endpoint: a matching query returns the
row, a non-matching query excludes it, and each declared search field matches
(e.g. a PO by `po_number` and by vendor name; a Bill by vendor invoice number, PO
number, and vendor name; an inventory item by `code` and `description`).

**Frontend (Vitest, `frontend/tests/`).** Per `docs/designs/frontend-testing.md`:

- New `EntityPicker` tests, parametrized across models: typing triggers a debounced
  `?search=` call, results render, `pick()` sets `value` and calls `onSelect(row)`,
  `selectedItem` renders the label with no resolve fetch, `value`-without-
  `selectedItem` triggers the resolve fetch, Clear resets.
- Updated `InventoryItemPicker` tests: server `?search=` (not the old bulk load),
  the `params` filter is forwarded, prefill + `onSelect(fullRow)` still hold.
- Delete/redirect the obsolete `ContactPicker` / `JobPicker` / `PurchaseOrderPicker`
  tests; retarget any that asserted the `{job_id, job_number}` shape.

## Docs to update on completion

- `docs/designs/jobs-tasks-and-worksheets.md` and
  `materials-inventory-and-purchasing.md` — picker references (`ContactPicker`,
  `JobPicker`, `PriceListItemPicker`) → new component names/contract.
- `docs/designs/architecture-and-conventions.md` — note the standard `EntityPicker`
  contract under the server-side `?search=` / type-ahead convention.
- `LATER.md` — close the parts these deliver in the four picker notes
  (email-association cap; customer/contact-picker consolidation; the search-picker
  portions of the inventory-merge note), leaving the merge-UX-rework remainder.

## Implementation order

1. Backend `?search=` for PO, Bill, inventory (+ tests). _(Unblocks the pickers.)_
2. `EntityPicker.svelte` + tests.
3. `InventoryItemPicker` rename + server search + `params` (+ tests); update 5 imports.
4. Migrate reference call sites (incl. `JobPicker`-consumer refactor); retire the
   three old pickers.
5. Revert BillFormPage PO field to a pulldown.
6. Docs + `LATER.md`.
