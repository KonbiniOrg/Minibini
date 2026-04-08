# PO Line Item Cancellation & Receipt Reversal

## Problem

When a PO line item has been partially received and then needs to be cancelled, the current implementation sets a `cancelled` boolean and ignores the received portion entirely. There is also no way to correct a receipt that was recorded in error.

These are two distinct problems:

1. **Cancel remaining** — a business decision: we got some, don't need or expect the rest.
2. **Reverse receipt** — a data correction: the receipt was recorded incorrectly.

## Model Changes

### PurchaseOrderLineItem

**Add:** `qty_cancelled` (DecimalField, max_digits=10, decimal_places=2, default=0)

**Remove:** `cancelled` (BooleanField)

**Derived states (not stored):**

- **Done** (nothing more expected): `qty_received + qty_cancelled == qty`
- **Fully cancelled** (nothing received, all cancelled): `qty_cancelled == qty`

**Validation:** `qty_received + qty_cancelled` must never exceed `qty`.

## Operations

### Cancel Remaining

Sets `qty_cancelled = qty - qty_received`, meaning "stop expecting the rest."

**Preconditions:**
- PO status is ISSUED or PARTLY_RECEIVED
- Line item has outstanding quantity: `qty_received + qty_cancelled < qty`

**Effects:**
- Sets `qty_cancelled = qty - qty_received`
- Creates HistoryEntry recording the cancellation and the quantity cancelled
- Triggers `_update_po_status`
- No inventory impact — received goods stay

**Not supported:** Partial cancellation (cancelling some but not all of the outstanding quantity). If part of the remaining is still desired, a new PO can be issued for it.

### Reverse Receipt

Resets `qty_received` to 0, undoing all receiving on the line item. Full reversal only — if 5 of 5 received were wrong and 2 were fine, reverse all 5 then re-receive 2.

**Preconditions:**
- `qty_received > 0`
- PO status is ISSUED, PARTLY_RECEIVED, or RECEIVED_IN_FULL

**Effects:**
- Resets `qty_received` to 0
- Clears `received_by`, `received_date`, `receipt_note`
- If line item's PriceListItem is inventoried: decrements `qty_on_hand` by the reversed quantity, creates a reversal InventoryAdjustment
- If `qty_cancelled > 0`: resets `qty_cancelled` to 0 (the outstanding quantity is restored since the receipt that preceded cancellation is being undone)
- Creates HistoryEntry recording the reversal and the quantity reversed
- Triggers `_update_po_status`

### PO Status Calculation (`_update_po_status`)

Replaces the current logic that filters on `cancelled=False`.

- An item is **done** when `qty_received + qty_cancelled == qty`
- An item is **active** (still expecting delivery) when `qty_received + qty_cancelled < qty`

Status rules:
- **RECEIVED_IN_FULL**: all items are done AND at least one has `qty_received > 0`
- **PARTLY_RECEIVED**: any item has `qty_received > 0` AND not all items are done
- **CANCELLED**: all items are done AND none have `qty_received > 0` (everything was cancelled, nothing received). Auto-sets `cancel_date`.
- Otherwise: no status change (stays ISSUED)

## API Changes

### Updated Endpoint

`POST /api/purchase-orders/{id}/cancel-line-item/`
- Request: `{"line_item_id": <id>, "note": "optional reason"}`
- Uses `qty_cancelled` instead of the removed `cancelled` boolean

### New Endpoint

`POST /api/purchase-orders/{id}/reverse-receipt/`
- Request: `{"line_item_id": <id>, "note": "optional reason"}`
- Full reversal of all received quantity on the specified line item

### Serializer Changes

- Remove `cancelled` from POLineItemSerializer fields and read_only_fields
- Add `qty_cancelled` to fields and read_only_fields

## Migration Notes

- Add `qty_cancelled` field
- Data migration: convert existing `cancelled=True` rows to `qty_cancelled = qty - qty_received`
- Remove `cancelled` field
- Grep entire codebase for references to the old `cancelled` field
