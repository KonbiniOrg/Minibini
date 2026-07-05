# Catalog Area UI — Spec

**Status:** implemented 2026-07-05. Branch: `feature/inventory_again`.

## Summary

Promote the catalog surfaces out of Settings and unify them under one
top-level **Catalog** area with per-tab routes. The sidebar's "Inventory"
link becomes "Catalog". Three tabs: **Inventory**, **Service Items**,
**Earmarks** (new). Settings' "Catalog" tab becomes **Pricing** after
ServiceItemManager leaves it.

## Routes

| Route | Content |
|---|---|
| `/catalog` | Inventory tab (default) — the existing inventory list |
| `/catalog/service-items` | ServiceItemManager (moved from Settings) |
| `/catalog/earmarks` | New read-only earmarks table |

- Real routes, not local-state tabs: bookmarks, refresh, and back-button
  land on the right tab. Tab strip is `<a use:link>` navigation (links
  navigate; buttons act).
- `/inventory` route is **deleted** with no redirect (pre-production, no
  bookmarks). Sidebar link text "Inventory" → "Catalog", href `/catalog`.
- The whole area is visible to every authenticated user (same as the old
  Inventory link).

## Inventory tab

The existing `InventoryListPage` content, unchanged except:

- The existing per-row `order` button (which navigated to
  `/purchase-orders/new?inventory_item=N`) is replaced by the new
  **stock-order flow** (below). Still rendered only for
  `canManageFinancials`.
- Item edit/write-off/merge gating is unchanged
  (`canManageFinancials || canManageConfig` — already true in code and on
  the API).

## Service Items tab

`ServiceItemManager` moves here from Settings, gaining a read-only mode:

- The table is always visible (any authenticated user).
- Add / Edit / Delete buttons render only when the user has **any** of
  `can_manage_jobs`, `can_manage_financials`, `can_manage_config`.
- Backend: `ServiceItemViewSet` write permissions widen to a new
  `CanManageJobsOrFinancialsOrConfig` class for create/update/delete
  (today: create is jobs-or-config, update/delete config-only;
  list/retrieve stay `IsAuthenticated`).

## Earmarks tab

Read-only commitment report. Earmarks remain entirely system-managed
(created at establish/order, shrunk by restock, deleted by consume/
release) — no create/edit/delete UI.

- One row per earmark (item + job). All rows fetched at once (earmarks
  stay small); **client-side sortable columns**.
- Columns: item code (link → nothing yet; plain text is fine since there
  is no item detail page — keep as text), description, units, job number
  (link → `#/jobs/{id}`), qty earmarked (this row), QOH (item), on order
  (item), **shortfall** (item-level, see below), PO link(s), Order button.
- PO links: every distinct non-cancelled PO that currently has an
  **outstanding** line for this item (`qty − qty_received − qty_cancelled
  > 0`) — there can be several; render each `po_number` as a link to
  `#/purchase-orders/{id}`.
- Order button: `canManageFinancials` only; runs the stock-order flow.

### Shortfall (item-level)

`max(0, item.qty_earmarked_total − item.qty_on_hand − item.qty_on_order)`

Computed at **item** level, not per earmark row, and repeated on each of
an item's rows (exactly like QOH / on-order repeat). Per-row arithmetic
lies when two jobs earmark the same item: two jobs × 5 with QOH 5 would
each show 0 while the shop is 5 short. Item-level reads "to cover every
commitment on this item you need N more" — the number you'd purchase.
Self-correcting against double-buying: ordering from one row raises
on-order, so after reload the sibling row's shortfall drops.

The same value pre-fills the stock-order quantity prompt (both tabs; on
the Inventory tab the identical formula uses the list serializer's
`qty_earmarked`/`qty_on_hand`/`qty_on_order` fields).

### New API: `GET /api/earmarks/`

Read-only list viewset, `IsAuthenticated`, **no pagination** (returns all
rows — earmarks stay small; matches the pull-all-sort-in-browser design).
Per row:

```json
{
  "earmark_id": 1,
  "inventory_item": 7,
  "item_code": "LOT-12",
  "item_description": "3mm acrylic",
  "units": "sheet",
  "job": 3,
  "job_number": "JOB-2026-0011",
  "quantity": "4.00",
  "created_date": "...",
  "qty_on_hand": "1.00",
  "qty_on_order": "2.00",
  "qty_earmarked_total": "6.00",
  "pos": [{"po_id": 9, "po_number": "PO-2026-0042"}]
}
```

`qty_on_hand` / `qty_on_order` / `qty_earmarked_total` are the item-level
figures; `pos` is the outstanding-PO list defined above. Shortfall is
computed client-side from the three quantities.

## Stock-order flow (Order button, both tabs)

Ordering an inventory item **to stock** — a plain PO line for the item,
no material link, no job. Legit to order without any job needing it;
receipt lands in QOH via the normal PO receiving path.

- UI: quantity prompt pre-filled with the item-level shortfall (editable —
  round up to a pack, over-buy deliberately). Then the standard
  append-or-create flow: zero open draft POs → create silently; one or
  more → chooser (append to a draft / start new PO). Same pattern and
  success message (link to the PO) as the material Order flow on the task
  list. Shared dialog component used by both tabs.
- API: `POST /api/inventory/{id}/order/` body `{"quantity": "5",
  "po_id": <optional draft>}`, permission `CanManageFinancials`. Response
  includes `po_id` + `po_number`.
- Service: `InventoryService.order_stock(item, quantity, po=None)` —
  validates quantity > 0 and (when given) that the PO is a draft; creates
  a PO via `PurchaseOrderService.create_po()` when none given; adds the
  line via `PurchaseOrderService.add_line_item_from_pli(po.pk, item.pk,
  quantity)` (no `job`, no `material_id`). Wrapped in a transaction.

## Settings readjustment

- Tab `catalog` renamed **Pricing** (key `pricing`). Contents: material
  markup default, **default material accounting category** (see below),
  RateSchemeManager. The "Work templates — not yet implemented" stub is
  deleted (a future work-templates UI belongs in the Catalog area).
- The default-material-accounting-category picker currently embedded in
  `AccountingCategories.svelte` is extracted into its own component
  (`components/settings/DefaultMaterialCategorySetting.svelte`) and
  rendered in **both** the Accounting tab and the Pricing tab — one
  implementation, two placements.

## Permission summary (deltas only)

| Surface | Before | After |
|---|---|---|
| Service item create | jobs \| config | jobs \| financials \| config |
| Service item update/delete | config | jobs \| financials \| config |
| Earmarks list (new) | — | IsAuthenticated |
| Stock order (new) | — | financials |
| Inventory item writes | financials \| config | unchanged |

## Out of scope

- Converting Settings / JobHistory local-state tabs to routes (noted for
  later by RM).
- Item detail pages, earmark editing, work-templates UI.
