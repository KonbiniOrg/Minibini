# Entity-picker consolidation & searchable type-aheads — design

_Spec — 2026-06-20_

## Problem

Entity selection across the SPA is inconsistent. Several places that pick a
**contact / business / job / purchase order / bill** from a long, growing list
use a plain `<select>` with no search — the worst being the **new-PO and new-Bill
forms** (every contact/business listed) and the three **email-association pages**
(`?page_size=500` silently capped at 100 by `StandardPagination`, so older rows
are unreachable).

Where type-aheads *do* exist they were each built at a different time and each
re-implements the same interaction behavior with subtly different bugs:

- `ContactPicker` — bare-id value; prefill-by-id with a `if (value === id)` race guard; Change/Cancel.
- `JobPicker` — partial-object value `{job_id, job_number}`; Clear only; no prefill resolve.
- `CustomerPicker` — dual contact+business; `{type, id}` value.
- `PriceListItemPicker` — full-row "fill-in"; client-side filtering over the whole catalog (`page_size=9999`); focus/blur dropdown with a `setTimeout(200)` blur delay; "None (freeform)" option.
- `PurchaseOrderPicker` — fetches one vendor's POs, then client-side filters.

## The seam

The duplication that matters is **not** the markup (an `<input>` + a `<ul>`) and
**not** an excuse to fuse every entity into one `model="…"`-parameterized
component (which only drags each entity's *disparate* needs — inventory's full row,
a contact's nested business, a PO's vendor label, a job's number-and-name — into one
body where they curdle into `if (model === …)` branches).

The real duplication is the **interaction behavior**: debounce the query, fire the
search, hold results, open/close on focus/blur (including the blur delay so a click
registers), resolve-by-id for prefill (with the race guard), and the
selected/clear transitions. That is ~60–90 lines of logic copy-pasted across the
pickers today, and it is where the bugs live.

So the consolidation is: a **`SearchPicker` base component that owns the
behavior** and takes **snippets** for the per-entity display, plus **thin
per-entity pickers** that supply the search call, the row rendering, and the emit
shape. Everything that genuinely differs stays in the per-entity picker.

Snippets (`{#snippet}` / `{@render}`) are already idiomatic in this codebase
(~10 components use them); no new `.svelte.js`/composable pattern is introduced.

## Output contract

For the **single-model** pickers (Business, Job, Contact, PurchaseOrder, Bill,
InventoryItem):

- `value` — **bindable id** (number) or `null`. What forms submit.
- `selectedItem` — optional **full object** the parent already has, so an edit
  screen renders the selected label with **no resolve fetch**.
- `onSelect(row | null)` — fires on selection change, handing back the **whole
  row**. Every picker emits the full row (not just a label): consumers routinely
  want more than the id — a job's number *and* name, a contact *and* its nested
  business. "Fill-in" consumers (inventory) just read more fields off the same row
  everyone gets.

`CustomerPicker` keeps its own shape — `value` = `{type, id}`, `onSelect({type,id})`
— because it searches two models. It rides the same base; only its search and
emit differ.

## Architecture

### `SearchPicker.svelte` (new — behavior core)

Owns all interaction; treats `value` **opaquely** (only "null vs set", and watches
it to trigger prefill). Knows nothing about endpoints or entity shapes.

**Props**

| Prop | Type | Notes |
|---|---|---|
| `value` | bindable, any | selection token; opaque to the base |
| `selectedItem` | object \| null | optional prefill object, forwarded to `resolveLabel` |
| `search` | `(query) => Promise<row[]>` | entity search (per-picker) |
| `resolveLabel` | `(value, selectedItem?) => Promise<string \| null>` | produce the label for the current selection; base owns the `$effect` + race guard that calls it |
| `rowLabel` | `(row) => string` | default row rendering (or use the `row` snippet) |
| `onPick` | `(row) => void` | user chose a result |
| `onClear` | `() => void` | user cleared |
| `disabled` | boolean | |
| `placeholder` | string | |

**Snippets**

- `row(item)` — optional; richer per-result rendering (falls back to `rowLabel`).
- `selected(label)` — optional; richer selected-state rendering (falls back to the
  label text + Change/Clear).
- `header()` — optional; rendered atop the results list (InventoryItemPicker uses
  it for its "None (freeform)" row).

**Behavior owned by the base**

- Debounced (~250 ms) invocation of `search` on input — an improvement; today's
  pickers fire on every keystroke.
- Results dropdown with focus/blur open/close, including the blur delay so a
  result click registers.
- Selected state: shows the label (via `resolveLabel` / `rowLabel`) with a
  Change/Clear affordance.
- Prefill: a single `$effect` watching `value`; when it changes and no label is
  cached, calls `resolveLabel(value, selectedItem)` with the `if (value === token)`
  race guard — the bug-prone bit, now written once.
- Click selection only (parity with today). Arrow-key navigation is **out of
  scope** (note for a later pass).

### Per-entity pickers (thin — ~20–40 lines each)

Each imports `SearchPicker`, supplies `search` (its endpoint + any fixed params),
`resolveLabel`/`rowLabel`, and maps `onPick`/`onClear` to its `value`/`onSelect`.

| Picker | Status | Endpoint | value | Notes |
|---|---|---|---|---|
| `BusinessPicker` | **new** | `/api/businesses/` | `business_id` | label `business_name` |
| `JobPicker` | rewritten on base | `/api/jobs/` | `job_id` | label `{job_number} — {name}` |
| `ContactPicker` | rewritten on base | `/api/contacts/` | `contact_id` | label `name` + nested `business`; emits full contact |
| `PurchaseOrderPicker` | rewritten on base, **global** | `/api/purchase-orders/` | `po_id` | label `{po_number} — {business_name}`; replaces the retired vendor-scoped client-filter version |
| `BillPicker` | **new**, global | `/api/bills/` | `bill_id` | label `{vendor_invoice_number or PO#} — {business_name}` |
| `InventoryItemPicker` | **renamed** from `PriceListItemPicker`, on base | `/api/inventory/` | `inventory_item_id` | full-row consumers; `params` prop for fixed filters (e.g. `is_active=true`); keeps the "None (freeform)" `header` snippet |
| `CustomerPicker` | rewritten on base | businesses + contacts | `{type, id}` | dual-source `search`; own emit shape |

Illustrative `JobPicker` (the shape they all take):

```svelte
<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (j) => `${j.job_number} — ${j.name ?? ''}`;
  const search = (q) =>
    api.get(`/api/jobs/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/jobs/${id}/`).then(label).catch(() => null);
</script>
<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(row) => { value = row.job_id; onSelect(row); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search jobs…" />
```

**`InventoryItemPicker` specifics:** kept as its own picker (consumers read
`description`, `units`, `selling_price`/`price`, `accounting_category`,
`is_inventoried`, on-hand/earmark). Switch from the client-side `page_size=9999`
load to server `/api/inventory/?search=` (fulfilling its own TODO). Add a general
`params` prop (extra fixed query filters). Keep the freeform option via the base
`header` snippet. No merge-specific behavior.

**Retired:** the old `PurchaseOrderPicker` body (vendor-scoped client-filter) is
replaced by the global one above.

## Backend: add `?search=`

`contacts`, `businesses`, `jobs` already implement `?search=` by hand in
`get_queryset` (no DRF `SearchFilter`). Mirror that pattern — do **not** introduce
`SearchFilter` — in:

| Viewset | File | Search fields (`icontains`, OR'd) |
|---|---|---|
| `PurchaseOrderViewSet` | `apps/api/purchasing/views.py` | `po_number`, `business__business_name` |
| `BillViewSet` | `apps/api/purchasing/views.py` | `vendor_invoice_number`, `purchase_order__po_number`, `business__business_name` |
| `InventoryItemViewSet` | `apps/api/inventory/views.py` (`/api/inventory/`) | `code`, `description` |

Each adds, inside the existing `get_queryset` (PO and Bill already read a
`business` query param there, so it slots alongside):

```python
search = self.request.query_params.get('search', '').strip()
if search:
    qs = qs.filter(Q(<field1>__icontains=search) | Q(<field2>__icontains=search) | ...)
```

## Call-site migration

| Site | Today | After |
|---|---|---|
| `PurchaseOrderForm` business | raw `<select>` | `BusinessPicker` |
| `PurchaseOrderForm` contact | raw `<select>` (business-scoped) | **stays pulldown** |
| `BillFormPage` business | raw `<select>` | `BusinessPicker` |
| `BillFormPage` contact | raw `<select>` (scoped) | **stays pulldown** |
| `BillFormPage` PO | old `PurchaseOrderPicker` (vendor-scoped) | **plain pulldown** of vendor POs |
| `ContactForm` business | raw `<select>` | `BusinessPicker` |
| `EmailAssociatePage` job | raw `<select>` (`page_size=500`, capped) | `JobPicker` |
| `EmailAssociatePOPage` PO | raw `<select>` | `PurchaseOrderPicker` (global) |
| `EmailAssociateBillPage` bill | raw `<select>` | `BillPicker` |
| `DuplicateJobPage` contact | old `ContactPicker` | `ContactPicker` (on base) |
| `ExpenseForm` job | old `JobPicker` | `JobPicker` (on base) |
| `LineItemForm` (PO) job | old `JobPicker` | `JobPicker` (on base) |
| `PurchaseOrderDetail` job ×2 | old `JobPicker` | `JobPicker` (on base) |
| `InvoiceListPage` / `BillListPage` customer filter | old `CustomerPicker` | `CustomerPicker` (on base) |
| `LineItemModal`, `MaterialModal`, `PlanMaterialModal`, `MaterialPicker`, `LineItemForm` material | `PriceListItemPicker` | `InventoryItemPicker` |

**`JobPicker`-consumer refactor.** The three job sites round-trip
`value = {job_id, job_number}` today. They switch to `value = <id>` and pass the
existing record as `selectedItem` for edit-mode prefill (or let `resolveLabel`
fetch). Touches `ExpenseForm.svelte`, PO `LineItemForm.svelte`,
`PurchaseOrderDetail.svelte`, including the spots reconstructing
`{job_id, job_number}` from `expense.job` / `li.effective_job_id`.

**Removing the `page_size=500` loads.** The three email-associate pages stop
bulk-loading their lists; the pickers fetch on demand. The "older rows unreachable
past 100" bug is fixed as a side effect.

## Out of scope (unchanged)

- All enum-ish `<select>`s: status, units, payment method/terms, accounting
  category, templates, rate schemes, user lists (Assign / TimeEdit / Expense
  purchased-by / JobEdit PM — bounded by worker count), list-page status/ordering
  filters.
- Business-scoped sub-lists stay plain pulldowns (a business's contacts; a
  vendor's POs).
- `InventoryListPage` merge keep/discard — deferred to the merge-UX-rework note;
  this spec only makes `InventoryItemPicker` capable (server search + `params`) so
  that rework can drop it in.
- The future job-scoped "attach to existing material" picker — will be a pulldown.
- Arrow-key navigation in the dropdown.

## Testing

**Backend (TDD).** A test per new `?search=` endpoint: a matching query returns the
row, a non-matching query excludes it, and each declared search field matches
(a PO by `po_number` and vendor name; a Bill by vendor invoice number, PO number,
and vendor name; an inventory item by `code` and `description`).

**Frontend (Vitest, `frontend/tests/`).** Per `docs/designs/frontend-testing.md`:

- `SearchPicker` base — the behavior, tested once with a stub `search`/`resolveLabel`:
  typing fires a debounced `search`, results render via `rowLabel`/`row`, `onPick`
  fires with the row, `value`-without-`selectedItem` triggers `resolveLabel`,
  `selectedItem` short-circuits it, Clear fires `onClear`, the focus/blur dropdown
  opens/closes.
- Thin pickers — a light test each that the right endpoint/params are called and the
  right `value`/`onSelect` shape is emitted (especially `CustomerPicker`'s
  `{type,id}` and `InventoryItemPicker`'s full row + `params` + freeform header).
- Delete/retarget obsolete tests that asserted the old `{job_id, job_number}` shape
  or the old client-filter inventory load.

## Docs to update on completion

- `docs/designs/jobs-tasks-and-worksheets.md`, `materials-inventory-and-purchasing.md`
  — picker references → `SearchPicker` + the per-entity pickers and the contract.
- `docs/designs/architecture-and-conventions.md` — document `SearchPicker` (behavior
  core + snippets) and the picker contract under the `?search=` / type-ahead
  convention.
- `LATER.md` — close the parts these deliver in the four picker notes
  (email-association cap; customer/contact-picker consolidation; the search-picker
  portions of the inventory-merge note), leaving the merge-UX-rework remainder.

## Implementation order

1. Backend `?search=` for PO, Bill, inventory (+ tests). _Unblocks the pickers._
2. `SearchPicker.svelte` base + tests.
3. Per-entity pickers on the base: `BusinessPicker`, `BillPicker` (new); rewrite
   `JobPicker`, `ContactPicker`, `PurchaseOrderPicker` (global), `CustomerPicker`;
   rename `PriceListItemPicker` → `InventoryItemPicker` (server search + `params`).
   Update the five inventory-picker imports.
4. Migrate call sites (incl. the `JobPicker`-consumer refactor); revert BillFormPage
   PO field to a pulldown.
5. Docs + `LATER.md`.
