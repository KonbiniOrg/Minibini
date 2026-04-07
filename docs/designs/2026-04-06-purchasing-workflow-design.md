# Purchasing Workflow Design

**Date:** 2026-04-06
**Scope:** Svelte PO CRUD, PO emailing, goods receiving

## Overview

Enable users to create purchase orders, send them to vendors via email, and record receipt of goods. Three stages of work, each building on the previous.

## Out of Scope

- Bills (existing backend, untouched this round)
- QBO sync for POs (POs are commitments, not financial transactions — QBO sync lives on Bills)
- Three-way matching (PO vs receipt vs bill)
- Return/rejection tracking (notes are sufficient for now; `qty_received` means correct items accepted)

---

## Stage 1: Svelte PO CRUD

Port the existing Django HTML PO views to the Svelte SPA, following the same patterns as existing jobs/contacts/businesses pages.

### Routes

| Route | Purpose |
|---|---|
| `#/purchase-orders` | List view |
| `#/purchase-orders/new` | Create form |
| `#/purchase-orders/:id` | Detail view |
| `#/purchase-orders/:id/edit` | Edit form (draft only) |

### List View

Table with columns: PO number, vendor (business name), status, created date, requested date, total amount. Filterable by status.

### Create / Edit

Form fields:
- Business (required)
- Contact (optional, filtered by selected business)
- Requested date

Same validation as Django — contact must belong to selected business. Edit is only available for draft POs.

### Detail View

- Header: PO number, vendor info, status badge, dates
- Status action buttons (context-dependent):
  - Draft: "Issue & Send" (Stage 2), "Mark as Issued" (Stage 2), "Edit", "Delete"
  - Issued: "Resend" (Stage 2), "Cancel"
  - Issued / Partly Received: "Resend" (Stage 2), "Receive All", "Receive Items" (Stage 3)
  - Per line item (issued/partly received): "Cancel Line" for unreceived lines
- Line items table: line number, description, qty, units, price, line total
  - After receiving begins: additional column showing qty received and received date per line
- Running total at bottom
- Line item management: add (manual or from PLI), reorder up/down, delete

### Line Item Cancellation

Available on issued or partly received POs. For when a vendor confirms an item won't be shipped (discontinued, backordered indefinitely, etc.).

- "Cancel" action per line item on the detail view
- Sets a `cancelled` flag on the line item (new BooleanField, default False)
- Cancelled lines are excluded from receiving calculations and displayed with a visual strikethrough/indicator
- Optional note on cancellation (saved as HistoryEntry)
- After cancellation, PO status is recalculated: if all non-cancelled lines are fully received → `received_in_full`
- Cannot cancel a line that has already been fully received

### Line Item Entry

Two modes (matching Django pattern):
1. **Manual:** description, qty, units, price, accounting category
2. **From Price List:** select PLI, enter qty — auto-fills description, units, price, accounting category

### Permissions

- Read (list, detail): any authenticated user
- Mutations (create, edit, delete, line items, issuing): `can_manage_financials`

### API

Uses existing endpoints:
- `GET/POST /api/purchase-orders/`
- `GET/PUT /api/purchase-orders/:id/`
- `DELETE /api/purchase-orders/:id/` (with confirm pattern)
- `POST /api/purchase-orders/:id/status/` (via StatusTransitionMixin)
- Line item endpoints via LineItemMixin

---

## Stage 2: PO Email & Issuing

Two paths from draft to issued, plus PDF generation for emailing.

### PDF Generation

- New module: `apps/purchasing/pdf.py` (follows `apps/invoicing/pdf.py` pattern)
- New template: `templates/purchasing/purchase_order_pdf.html`
- Uses WeasyPrint to render Django template to PDF
- PDF contains: PO number, vendor info (business, contact), requested date, line items table (description, qty, units, price, line total), grand total

### Issue & Send

Available on draft POs with at least one line item.

1. User clicks "Issue & Send"
2. Form/modal opens pre-populated with:
   - **To:** vendor contact's email (editable)
   - **Subject:** from configurable boilerplate template
   - **Body:** from configurable boilerplate template, editable before sending
3. User reviews/edits, clicks Send
4. Backend atomically: transitions PO to `issued`, sets `issued_date`, generates PDF, sends email
5. PO detail reflects new status

**Configuration keys:**
- `po_email_subject_template` — e.g. `"Purchase Order {po_number} from {company_name}"`
- `po_email_body_template` — default boilerplate with `{po_number}`, `{vendor_name}`, `{company_name}` placeholders

Defaults are provided if keys don't exist yet.

**API:** `POST /api/purchase-orders/:id/send/`
- Accepts: `to`, `subject`, `body`
- Validates PO is in `draft` status with at least one line item
- Returns updated PO with `issued` status
- Creates HistoryEntry recording the send (to address, timestamp)

### Resend PO

Available on already-issued POs (for email typos, vendor didn't receive, etc.).

1. User clicks "Resend" on an issued/partly received PO
2. Same email form as "Issue & Send" — pre-populated, editable
3. Backend generates PDF and sends email, but does NOT change PO status (already issued)
4. Creates HistoryEntry recording the resend (to address, timestamp)

**API:** Same `POST /api/purchase-orders/:id/send/` endpoint — if PO is `draft`, it issues and sends. If PO is already `issued` or `partly_received`, it just resends. Endpoint is valid for `draft`, `issued`, and `partly_received` statuses.

### Mark as Issued

Available on draft POs with at least one line item. For orders placed by phone, in person, etc.

1. User clicks "Mark as Issued"
2. Small form with optional note field (e.g., "ordered by phone", "outside rep took order")
3. Backend transitions PO to `issued`, sets `issued_date`, creates HistoryEntry with the note

**API:** Uses existing `POST /api/purchase-orders/:id/status/` with `status: "issued"` plus an optional `note` field.

### Permissions

- Issue & Send: `can_manage_financials`
- Mark as Issued: `can_manage_financials`

---

## Stage 3: Goods Receiving

Record receipt of goods against PO line items. Receipt fields live directly on `PurchaseOrderLineItem` (no separate model). HistoryEntry provides the audit trail for multi-delivery scenarios.

### Model Changes

**New fields on PurchaseOrderLineItem:**

| Field | Type | Default | Notes |
|---|---|---|---|
| `qty_received` | DecimalField | 0 | Cumulative correct items accepted |
| `received_by` | FK to User | null | Last user to record receipt |
| `received_date` | DateTimeField | null | Timestamp of last receipt |
| `receipt_note` | TextField | blank | For problem cases (wrong item, damage) |
| `cancelled` | BooleanField | False | Line cancelled (vendor won't ship) |

**Permissions note:** The receiving fields (`qty_received`, `received_by`, `received_date`, `receipt_note`) are updated via the receiving endpoints, which require only authentication — not `can_manage_financials`. Any authenticated user can receive goods, even though creating/editing line items themselves requires `can_manage_financials`.

**Key semantic:** `qty_received` means "quantity of the correct item accepted." Wrong or damaged items are not recorded as received — a note explains what happened, and the line stays open until the vendor makes it right.

### Receiving UX

Two paths, both available on the PO detail page when status is `issued` or `partly_received`.

**Happy path: "Receive All"**
- Single button with confirmation
- Sets `qty_received = qty` on all unreceived/partially received lines
- Sets `received_by` and `received_date` on each
- Creates HistoryEntry: "All items received by {user}"

**Line-by-line: "Receive Items"**
- Form showing all lines where `qty_received < qty`
- Each line shows: description, qty ordered, qty already received, input for qty receiving now
- Note field per line (surfaced for problem cases — e.g., "received wrong item, returning to vendor")
- Submit updates affected line items, creates HistoryEntry with details

### PO Status Auto-Transition

After any receipt action, the receiving service checks all line items:
- Cancelled lines are excluded from all calculations
- If every non-cancelled line has `qty_received >= qty` → status becomes `received_in_full`, `received_date` set on PO
- If any non-cancelled line has `qty_received > 0` but not all fully received → status becomes `partly_received`
- Status transitions happen automatically in the service, not manually

### Inventory Integration

On each receipt, per line item:
- **Line references a PriceListItem:** auto-increment `PriceListItem.qty_on_hand` by qty received, create an `InventoryAdjustment` record for audit
- **Line does NOT reference a PLI:** receipt is recorded normally. After the receipt is saved, the UI shows a follow-up prompt per non-PLI line: "Create inventory item for [description]?" If yes, creates PLI (pre-filled from line item data) and adjusts inventory. If no, no inventory impact. This prompt does not block the receipt — goods are received regardless.

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/purchase-orders/:id/receive/` | POST | Line-by-line receipt. Body: list of `{po_line_item_id, qty_received, note?}` |
| `/api/purchase-orders/:id/receive-all/` | POST | Receive all remaining. No body needed. |
| `/api/purchase-orders/:id/receipts/` | GET | Receipt summary (current state of all line items + relevant history entries) |

### Permissions

- Receiving (all endpoints): any authenticated user (no extra permission required)

---

## Status Flow Summary

```
PurchaseOrder:

  draft ──→ issued ──→ partly_received ──→ received_in_full
              │                                   ▲
              │         └─────────────────────────┘
              │
              └──→ cancelled

  draft → issued: via "Issue & Send" or "Mark as Issued"
  issued → partly_received: automatic on first partial receipt
  issued → received_in_full: automatic when all lines fully received
  partly_received → received_in_full: automatic when remaining lines received
  issued → cancelled: manual action
```

## Implementation Notes

- Svelte components follow existing patterns in `frontend/src/` (jobs, contacts, businesses)
- PDF follows `apps/invoicing/pdf.py` pattern (WeasyPrint + Django template)
- Email sending uses existing `apps/core/services.py` infrastructure
- Services in `apps/purchasing/services.py` — extend existing PurchaseOrderService
- All receipt actions wrapped in `transaction.atomic()` (receipt + inventory adjustment + status transition)
- HistoryEntry records created for: issuing (with optional note), each email send/resend (to address, timestamp), each receipt event, line item cancellation (with optional note), PO cancellation
