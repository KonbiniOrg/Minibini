# PO order flow — design spec

_2026-10-14. Branch `feature/po-flows`. Disposable: delete once shipped; the
durable record goes into `docs/designs/materials-inventory-and-purchasing.md`
§9–§11 and `quickbooks-integration.md` is untouched._

## 1. Problem

Three of the eight ways a PO comes into existence skip the information the
buyer actually has at that moment, and the fourth hides a silent-duplicate
trap:

- **Order from a material row** (`POST /api/materials/{id}/order/`) creates a
  vendor-less draft PO on the first click, or asks only "which open draft".
  The buyer then has to open the PO and hunt for the vendor.
- **Order stock from the catalog** (`POST /api/inventory/{id}/order/`) asks a
  quantity and otherwise behaves the same.
- **Create PO from an email** is a full page (`/email/:id/create-po`) that
  resolves the sender and creates a header-only PO; the matched contact is
  not stored on the PO.
- **PO detail → Add Line Item** offers a Job picker but no way to attach the
  line to a *specific* pending material. The resolver claims only on an
  exact single match and otherwise creates a duplicate material, silently.

Nothing in the system remembers which vendor carries an item, and there is
no field for the vendor's part number on a PO line.

Surveyed entry points (for scope reference; unchanged ones are listed so
nobody wonders): (1) material-row Order, (2) catalog Order, (3) PO list "New
Purchase Order" + Business/Contact page "New purchase order", (4) email
Create PO, (5) PO detail Add Line Item, (6) reconciliation invoice-only
lines, (7) draft line Job edit, (8) issued/received "Change Job". This spec
changes 1, 2, 4, 5 and removes dead prefill plumbing that once fed 3 → 5.
Paths 3, 6, 7, 8 are untouched.

## 2. Decisions (RM, 2026-10-14)

- **Vendor knowledge is derived from PO history, not curated.** No
  vendor-item table, no preferred-vendor flag, no "is vendor" marker on
  Business. If history recommends the wrong vendor often, revisit.
- **Vendor SKU lives on the PO line** (`PurchaseOrderLineItem.vendor_sku`),
  nowhere else. History suggests it; the quote overrides it.
- **One Order modal** replaces the two one-click dialogs and the email
  create-PO page. It is a PO header form plus one line, and **creates
  nothing until Submit**. New PO + first line are one transaction.
- **Append-or-new is an explicit choice** inside the modal once the vendor
  is known. Neither is the default when both exist; with no open draft for
  the vendor the choice simply doesn't appear.
- **The inventory item on the modal's line is fixed.** From a material it is
  the material's item; from the catalog it is the clicked item. A wrong pick
  is corrected by cancelling and re-picking. Qty, units, price, description,
  SKU and accounting category are editable.
- **Email path reuses the sender-resolution form** inside the modal, the
  way `EmailCreateJobModal` does, including creating an unknown vendor's
  contact/business with duplicate detection as in-modal sub-states.
- **PO detail Add Line gets an explicit material picker** once a Job is
  chosen: attach to one of that job's pending unlinked materials, or create
  new. The resolver's claim step stays for API callers; the form never
  relies on it.
- **Out of scope:** the service-PO design pass (receiving-completes-the-
  task, per-task rate prompt), vendor-only business search, contact-name →
  business picker, PO PDF changes other than the SKU column.

## 3. Schema

One migration, `purchasing`:

```
PurchaseOrderLineItem.vendor_sku = CharField(max_length=100, blank=True, default='')
```

Editable on draft lines through the existing line PATCH; read-only after
issue like the other ordering fields (reconciliation's `final_price`
whitelist is unchanged — SKU is not a reconciliation field). Shown as a
column on the PO detail line table and on the PO PDF
(`templates/purchasing/purchase_order_pdf.html`), blank when empty. The
LATER item "PO line items should show the inventory item's code" is picked
up in the same table/PDF pass: code column beside the SKU column, blank for
freeform lines.

No other schema change. `PurchaseOrder.business` stays nullable (path 3's
form and any API caller may still make a vendor-less draft; the issue-time
`clean()` gate stands), but paths 1, 2 and 4 no longer produce one.

## 4. Backend

### 4.1 Vendor history — `GET /api/inventory/{id}/vendor-history/`

`IsAuthenticated`. Returns the item's distinct vendors from PO lines on POs
that are **not draft and not cancelled**, most recent first:

```json
{
  "vendors": [
    {"business_id": 17, "business_name": "Rugby Architectural",
     "contact_id": 88, "last_ordered": "2026-08-02", "last_price": "62.40",
     "vendor_sku": "BB34P-48", "po_number": "PO0120", "times": 6}
  ],
  "earmarks": [
    {"job_id": 39, "job_number": "08157", "quantity": "4.00"}
  ],
  "open_drafts": [
    {"po_id": 131, "po_number": "PO0131", "business_id": 17,
     "business_name": "Rugby Architectural", "line_count": 2}
  ]
}
```

- `vendors` — one row per business; `last_*` and `vendor_sku` come from
  the newest line for that business (SKU may be `''`). `contact_id` is the
  PO's contact on that newest line's PO, or `null`.
- `earmarks` — the item's committed earmarks by job (the LATER "show
  earmarks when ordering" item), **excluding** the calling material's own
  job when `?exclude_job=<id>` is passed, so the modal can say "also needed
  by …".
- `open_drafts` — every draft PO (vendor-less drafts included, flagged by
  `business_id: null`) so the modal can filter client-side by the chosen
  vendor without a second request. Capped at 100 like today's choosers.

Service: `InventoryService.vendor_history(item, *, exclude_job=None)` in
`apps/inventory/services.py`. Minted `LOT-*` items return empty `vendors`
(they have no past) but still return `open_drafts`.

### 4.2 Order endpoints

Both existing order actions change their contract from "create now, choose
draft" to "here is the whole PO":

`POST /api/materials/{id}/order/` and `POST /api/inventory/{id}/order/`,
`CanManageFinancials`, body:

```json
{
  "po_id": 131,                      // append mode — OR —
  "po": {"business": 17, "contact": 88, "requested_date": "2026-10-20"},
  "line": {"qty": "4", "units": "sheet", "price": "62.40",
           "description": "...", "vendor_sku": "BB34P-48",
           "accounting_category": 3}
}
```

Exactly one of `po_id` / `po` is required (`non_field_errors` otherwise).
`po.business` is required in `po` mode (`{'po': {'business': [...]}}`), so
these two paths can no longer mint a vendor-less PO. `line.inventory_item`
is **not accepted**: the item is the material's / the clicked item's
(`{'line': {'inventory_item': ['Cannot change the item here.']}}` if sent).
Every `line` field is optional and defaults from the item/material as the
old one-shot did. Response: `{po_id, po_number, line_item_id}`, 201.

Services:

- `MaterialService.order(material, *, po=None, po_fields=None, line=None)`
  — same refusals as today (provisional, non-pending, customer-supplied,
  already linked, non-draft `po`); `transaction.atomic()` around
  `PurchaseOrderService.create_po(**po_fields)` + `add_line_item_from_pli(
  po.pk, material.inventory_item_id, qty, job=material.job_id,
  material_id=material.pk, **line_overrides)`. The resolver's explicit path
  links the material; `_apply_po_line_cost` pushes the line price to the
  material as today.
- `InventoryService.order_stock(item, *, po=None, po_fields=None, line=None)`
  — same shape, no job, no material.
- `add_line_item_from_pli` grows `price=None, description=None, units=None,
  vendor_sku='', accounting_category=None` overrides (None → item default).

### 4.3 Email create-PO — `POST /api/emails/{id}/create-po/`

Body grows to `{vendor_business_id, contact_id?, requested_date?, line?}`
where `line` is the same shape as §4.2 **plus** `inventory_item` (the email
path has no fixed item). Creates the PO with `business` and `contact`,
links the email, adds the line if given — one transaction. The old
header-only call (`{vendor_business_id}` alone) still works, so no client
other than the modal needs to change.

### 4.4 PO detail Add Line — `POST /api/purchase-orders/{id}/line-items/`

No contract change: the explicit `material_id` path already exists. Two
service guards are added in `PurchaseOrderService.add_line_item`:

- `is_comment` with `job` or `material_id` → `{'job': ['A comment line
  cannot be attributed to a job.']}` (today it would mint a 0-qty material).
- `material_id` whose material's `inventory_item` differs from the line's
  `inventory_item` (both non-null) → `{'material_id': ['This material
  needs <code>, not <code>.']}`. Receipt bumps the line's item; a mismatched
  link could never be satisfied.

No new read endpoint for the picker: `GET /api/jobs/{id}/` already
returns the job's `materials` with `consumption_state`, `po_line_item_id`,
`cost_source`, `item_code` and `quantity`; the form filters client-side to
pending, unlinked, not customer-supplied. (`/api/jobs/{id}/materials/` is
POST-only — create — and stays that way.)

One existing-behavior fix on the explicit path: when `material_id` names a
**provisional** material and the line carries an `inventory_item`,
`_apply_po_line_cost` today calls `establish` with no item and mints a
`LOT-*` lot, so the material and the line end up on different items and
receipt can never satisfy the material. Change it to
`establish(material, inventory_item=line.inventory_item, unit_cost=price,
cost_source='po')` so a catalog PO line establishes the material **onto the
line's item**. The freeform-line case (line has no item → mint lot and
repoint the line) is unchanged.

### 4.5 Dead code removal

`LineItemForm`'s `materialId` / `defaultJob` props and the
`prefill_material` / `prefill_inventory_item` / `default_job` /
`?job` / `?material` / `?inventory_item` query handling in
`PurchaseOrderFormPage.svelte` and `PurchaseOrderDetailPage.svelte` have no
producers (survey 2026-10-14). Delete them. `?business` / `?contact` on
`/purchase-orders/new` are live (Business/Contact pages) and stay.

## 5. Frontend

### 5.1 `OrderModal.svelte` (`components/purchaseorders/`)

One component, three **sources**, selected by props:

| source | opened from | item | vendor tier seed | line |
|---|---|---|---|---|
| `material` | MaterialRow "Order" (task list, task detail) | fixed, the material's | item vendor history | prefilled from material; qty = `orderPrefillQty(material)` |
| `item` | Catalog Inventory + Earmarks "order" | fixed, the clicked item | item vendor history | prefilled from item; qty = item shortfall (today's rule) |
| `email` | Email action panel "Create new" PO | none fixed; optional line with an `InventoryItemPicker` | sender resolution | empty, optional |

Layout, top to bottom:

1. **Vendor** — `VendorPicker` (§5.2) or, in `email` source,
   `SenderResolutionForm` (existing, unchanged).
2. **Contact** — select of the vendor's contacts, defaulting to the
   history row's `contact_id`, else the business's `default_contact`.
   Optional (the model allows null). Hidden in `email` source — the
   resolver yields it.
3. **Requested date** — optional, as on the PO form.
4. **Open drafts for this vendor** — appears only when `open_drafts`
   contains at least one draft whose `business_id` equals the chosen
   vendor. Radio group: "Start a new PO" / "Add to PO0131 (2 lines)". No
   preselection; Submit is disabled until one is picked. Choosing a draft
   collapses 2–3 (the draft already has them). Vendor-less drafts are
   never offered (a vendor-less draft is path 3's business).
5. **Line** — item (read-only code + description, or picker in `email`),
   qty, units, price, description, vendor SKU, accounting category. Under
   qty, when `earmarks` is non-empty: "Also needed: 08149 ×3, 08157 ×4" so
   the buyer can size the order. Picking a different vendor re-seeds SKU
   (and price) from that vendor's history row, if any; a hand-edited SKU is
   not overwritten (track `skuTouched`).
6. Buttons: **Create PO** / **Add to PO0131** (label follows the choice),
   Cancel. Enter-on-form submits; Esc cancels (`Modal.svelte` conventions).

Submit → §4.2 / §4.3 call → `push('/purchase-orders/{po_id}')` with a
success overlay naming the PO. Errors through `triageError`: `po.*` and
`line.*` field errors land under their inputs, `non_field_errors` /
`detail` in `FormMessage`.

`MaterialFulfillmentModals.svelte` keeps `startReceipt`; `startOrder`
becomes "open `OrderModal` with `source='material'`". `StockOrderDialog.svelte`
is deleted; the two catalog pages open `OrderModal` with `source='item'`.
`EmailCreatePOPage.svelte` and the `/email/:id/create-po` route become a
`RedirectTo` stub to the email detail page, which opens `OrderModal` with
`source='email'` (mirrors the 2026-10-10 create-job change).

### 5.2 `VendorPicker.svelte`

Props: `vendors` (history rows), `value` (bindable business id),
`onSelect(row|business)`. Two modes:

- **Recent** — a native `<select>` of history rows, most recent first,
  preselected to the first, option text "Rugby Architectural — last Aug 2
  at $62.40 · SKU BB34P-48" (price/SKU segments omitted when absent), plus
  a last option "Search all businesses…". Choosing it → search mode.
- **Search** — the existing `BusinessPicker` (`SearchPicker` under it),
  auto-focused. While nothing is chosen and `vendors` is non-empty, a
  "back to recent vendors" link sits under the input. A pick shows
  `SearchPicker`'s selected chip + Clear; **Clear returns to recent mode**
  when `vendors` is non-empty, else stays in search.

Empty `vendors` → opens in search mode with no back link.

### 5.3 PO detail Add Line — `LineItemForm.svelte`

After the Job picker, when a job is chosen and no task is picked:

- Read the job's materials from the job detail payload (§4.4), filtered
  to pending, unlinked, not customer-supplied. If none: a line
  "No unordered materials on this job — a new material will be created."
- Else a radio list: one row per material ("BBPLY.75P · 4 sheet · 3/4"
  Baltic Birch …") and a final "Create a new material for this line".
  **No preselection**; Submit disabled until one is chosen. Picking a
  material in **From Inventory** mode sets the Inventory Item to the
  material's item and locks it (the §4.4 guard backs this); in **Manual**
  mode the line stays freeform and links to the (provisional or
  established) material exactly as the explicit resolver path does today.
- Payload: `material_id` when a material is picked; `job` only when "create
  new". (Sending both is still valid for the API; the form sends one.)

The Task picker remains the pure-attribution branch and hides the material
list, as now. The `is_comment` checkbox disables the Job picker (§4.4
guard).

### 5.4 PO detail line table + PDF

Add **Code** (item code, blank for freeform) and **SKU** columns to the
draft/issued line table in `PurchaseOrderDetail.svelte` and the PDF
template. SKU is editable in the draft line-edit row.

## 6. Permissions (RM 2026-10-15: making a PO opens to manage-jobs, incl. PM)

Creating a PO is no longer financials-only. Two new composites in
`apps/api/permissions.py`:

- `CanManageJobsOrFinancials` — either atom (superuser bypasses as
  always). **Not** config: the existing inventory comment is right that
  purchasing is not an admin act.
- `CanManageFinancialsOrJobOrPM` — the financials atom, else defer to
  `CanManageJobOrPM` (jobs atom, or PM of the request's target job via
  `view.get_permission_target_job`).

| Endpoint | Was | Now |
|---|---|---|
| `POST /api/materials/{id}/order/` | financials | `CanManageFinancialsOrJobOrPM`, target job = the material's job (the material viewset gains `get_permission_target_job` via `JobScopedPermissionMixin` if it lacks it) |
| `POST /api/inventory/{id}/order/` | financials | `CanManageJobsOrFinancials` — no job in play, so PM scoping has nothing to scope to |
| `POST /api/emails/{id}/create-po/` | financials | `CanManageJobsOrFinancials` |
| `POST /api/purchase-orders/` (create) | financials | `CanManageJobsOrFinancials` |
| `GET /api/inventory/{id}/vendor-history/` | — | `IsAuthenticated` |

Buttons follow the same split. MaterialRow's Order button shows when
`$canManageFinancials || material.can_manage`; both `MaterialSerializer`s
gain `can_manage` from `JobScopedCanManageMixin` (the same flag Task and
Job already expose). The catalog "order" buttons, the PO list's "New
Purchase Order", the Business/Contact "New purchase order", and the email
panel's "Create new" show when `$canManageFinancials || $canManageJobs`.
(`stores/permissions.js` already derives both.)

**PO-level writes open the same way (RM 2026-10-15).** Every write on an
existing PO that is financials-only today — header edit, add / edit /
delete / cancel line, issue, cancel PO, delete draft, change line job,
send — becomes `CanManageFinancialsOrJobsOrLinkedPM`:

- financials atom → allowed; jobs atom → allowed;
- else allowed when the user is `project_manager` of **any job linked to
  any line on this PO**, where "linked" means a Material whose
  `po_line_item` is on the PO (`Material.job`) or a line whose `task` is on
  the user's job (`task.job`). Resolved per request from the PO the URL
  names (`view.get_object()`), so no stored flag.

Known and accepted: a PM's access is only as durable as the link. Removing
or re-jobbing the one line that ties their job to the PO drops their
access to that PO on the next request. The SPA doesn't try to warn about
this; the PO page simply re-renders read-only after the mutation.

`PurchaseOrderSerializer` exposes `can_manage` (same three-way rule) and
the PO page gates its buttons on `po.can_manage` instead of
`$canManageFinancials`. The PO **list's** "New Purchase Order" stays on
the atom check (no PO to be linked to yet).

**Stated assumption, pending RM:** `reconcile` (recording the vendor
bill's total / reference / line finals, §10a of the materials doc) stays
`CanManageFinancials`. The docs frame it as the bookkeeping half of the
QBO bill; opening it to jobs/PM would let a non-financials user write
job-costing actuals. Everything else on the PO opens. Say so if reconcile
should open too.

## 7. Tests

Backend (`tests/`):
- `test_vendor_history.py` — ordering, draft/cancelled exclusion, SKU and
  contact from newest line, `exclude_job`, LOT item → empty vendors,
  open_drafts includes vendor-less.
- `test_material_order.py` (extend existing order tests) — `po` mode
  creates PO+line atomically (failure in line add rolls back the PO), `po_id`
  mode appends, both/neither → 400, `inventory_item` in line → 400, vendor
  required, line overrides applied, price flows to material cost.
- `test_inventory_order_stock.py` — same matrix without the material.
- `test_email_create_po.py` — contact stored, optional line, legacy body
  still works, atomic.
- `test_po_line_items.py` — comment+job guard, material/item mismatch
  guard, provisional material + catalog line establishes onto the line's
  item (no stray lot).
- `test_po_permissions.py` — create: jobs atom allowed, PM-only denied;
  material order: PM of the material's job allowed, PM of another job
  denied; PO writes: PM linked via Material allowed, via `task.job`
  allowed, unlinked PM denied, and **access drops after the linking line
  is deleted / re-jobbed**; reconcile stays financials-only;
  `can_manage` on PO and material serializers matches the view rule.
- PDF test: SKU + code columns render, blank for freeform.

Frontend (Vitest, `frontend/tests/`):
- `OrderModal.test.js` — three sources; draft radio only when a draft
  matches the vendor; Submit disabled until the choice; item is read-only;
  SKU re-seeds on vendor change but not after hand edit; earmark line;
  payload shape per mode; navigation on success.
- `VendorPicker.test.js` — recent/search modes, "Search all…" option,
  back link, Clear → recent, empty history → search.
- `LineItemForm.test.js` — material radio list, no preselection, item lock,
  payload `material_id` vs `job`, comment disables Job.
- Delete `StockOrderDialog.test.js`; update `MaterialFulfillmentModals`
  and email action-panel tests.

E2E (Playwright, `e2e/`), one spec `po-order-flow.spec.js`: order a
material with history → vendor preselected → Create PO → lands on PO with
the line and SKU; order again with that PO still draft → "Add to" choice →
line appended; catalog order with no history → search mode; email create
PO with a matched sender → PO carries contact; PO detail add line → attach
to existing material (no duplicate on the job).

## 8. Docs to update when shipped

`materials-inventory-and-purchasing.md` §9 (fields: `vendor_sku`), §10
(`add_line_item_from_pli` overrides, guards), §11 (Order / Order-to-stock
contracts, vendor history, the picker), §16/§17 (SPA surfaces);
`architecture-and-conventions.md` endpoint list; `users-and-permissions.md`
if the vendor-history route is listed; `data-constraints.md` for
`vendor_sku`; `frontend/README.md` Modals list. LATER: remove "Show a
material's earmarks on the PO", "PO line items should show the inventory
item's code"; fix the stale "create-PO-from-email not built" fragment.
