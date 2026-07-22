# Spec: Remove Bill from konbini — bills live entirely in QBO

Branch: `feature/qbo`. Second of the three QBO-deepening changes (first:
QBO-primary invoicing, shipped on this branch; third, later: setup-time pull
of QBO data into konbini).

## Goal

Delete the Bill domain from konbini. Vendor invoices (bills) are entered,
tracked, and paid in QBO only. Konbini keeps the purchasing side it is
actually good at — POs, receiving, stock intake — and keeps one breadcrumb:
vendor-invoice emails link to the PO.

QBO context (verified): QBO bills do NOT require POs — bills stand alone
against a vendor. Konbini will not use QBO's PO or inventory systems.

## What today's code showed (grounding facts)

- **Job costing is untouched.** `spend_breakdown` (`apps/jobs/financials.py`)
  reads Expenses + consumed Materials + blep labor. Bills never feed it.
- **Stock intake is untouched.** Receiving is PO-driven
  (`PurchaseOrderService.receive_items` bumps `qty_on_hand`); bills play no
  part.
- **`push_vendor`'s only caller is the bill push** — `QBOVendorSyncService`
  is orphaned by this change.
- **`poll_qbo_payments` covers invoices AND bills** — the bill slice
  (`bills_checked` / `bills_cleared` stats and the code behind them, plus the
  BillPayment deferred-clearance polling) goes; invoice polling stays.

## Decisions

### 1. Model removal

- Delete `Bill`, `BillLineItem`, `BillPayment` (models + a migration dropping
  the three tables). No data export/migration — pre-production; real bills
  will be born in QBO.
- `PurchaseOrder` loses `billed_total` / `is_fully_billed` and the `bills`
  reverse relation. PO status machine unchanged — lifecycle ends at
  `received_in_full` / `cancelled`. No "billed" state or flag is added:
  invoice-vs-PO reconciliation is bookkeeper work done in QBO; a konbini-side
  flag verified against nothing would drift.
- KEEP: `AccountingCategory.qbo_expense_account_id` and
  `Configuration['qbo_payment_accounts']` (+`QBOPaymentAccountService`) —
  expenses/reimbursements use both. KEEP `Business.qbo_vendor_id` (harmless;
  the future QBO-pull may repopulate it; `QBODisplayNameService` reads it for
  the suffix rule).

### 2. QBO layer

- Delete `QBOBillSyncService` entirely (bill push, bill-payment
  push/update/void) and `QBOVendorSyncService` (orphaned).
- Remove the BillPayment rows from the sync-failures list/retry-all surface
  (`QBOSyncFailureService`, `/api/qbo/sync-failures*`).
- Remove the bill/BillPayment slice from `poll_qbo_payments` (invoice slice
  stays) and from any clearance polling.
- `QBOSyncLog` rows with `entity_type` in `bill` / `bill_payment` / `vendor`
  are retained as history (append-only log; the types simply stop occurring).
  The `purge_qbo_data` FIELD_RESETS entries for bills/billpayments are
  removed along with the models they reset.

### 3. Email breadcrumb (the one retained capability)

- Inbound vendor-invoice emails link to the **PurchaseOrder** instead of a
  Bill. The email action panel's link-to-bill action becomes
  link-to-purchase-order, reusing the existing `PurchaseOrderPicker` and the
  existing `EmailRecord.purchase_order` association (already used by
  outbound PO sends). The PO detail's email panel then shows that the vendor
  invoice arrived.
- Drop the `EmailRecord.bill` FK and the `'bill'` entry in
  `OutboundEmailService._ASSOC_FIELDS`.

### 4. SPA removal

- Delete: `BillListPage`, `BillDetailPage`, `BillFormPage`, `BillPicker`,
  bill routes + nav entry, the PO detail "billed" section, bills in Search
  results, the bills slice of the business financials rollup, and the
  BillPayment slice of the QBO sync-failures settings card.
- The email action panel swaps its bill affordance for the PO one (§3).

### 5. Sweep

- `apps/api/purchasing/` bill viewsets/serializers/urls; `apps/search`
  bill queries; `apps/contacts` deletion-protection checks that reference
  bills; `validate_data`; `scripts/seed_data.sh`; fixtures; the e2e seed +
  any bill specs; the nealsdata converter stops emitting bills (MUST run
  `tests.test_neals_builders` per standing rule; `converted.json`
  regenerated).
- `can_manage_financials` loses its bill endpoints (permissions doc table).
- Docs same-session: `materials-inventory-and-purchasing.md` (Bill/PO
  sections), `quickbooks-integration.md` (bill push, vendor sync, polling,
  models table), `invoicing-and-expenses.md` (if it references bills),
  `contacts-and-businesses.md` (financials rollup), `data-constraints.md`
  (Bill/BillLineItem/BillPayment sections, PO cross-refs),
  `users-and-permissions.md` (endpoint table), `CLAUDE.md` (model tables,
  URL list, workflows), `architecture-and-conventions.md` (mixin/viewset
  catalogs if bills appear).

## Out of scope

- QBO setup-time data pull (third changeset).
- Any QBO-side automation for creating bills from konbini POs.
- Cancel-invoice-from-konbini and other previously queued items.

## Testing

- Backend: delete bill test modules (`test_qbo_bill_push`,
  `test_qbo_bill_polling` bill slice, `test_bill_payment_qbo_lifecycle`,
  `test_qbo_bill_payment_push`, bill parts of purchasing/API/search/email
  tests); update PO tests that touch `billed_total`/bills; new tests for
  email→PO linking action. Full suite fresh (migrations — no `--keepdb`).
- Vitest: delete bill component specs; update PO detail, email action panel,
  search, nav, sync-failures specs; new spec for link-email-to-PO.
- E2E: strip bills from the committed seed; delete/adjust bill flows; the
  email→PO link flow gets a spec if an email fixture exists in the e2e seed
  (else note the exemption).

## Verification checkpoints (implementation-time)

- `grep -rn "Bill" apps/ frontend/src/ tests/ e2e/specs/` (case-sensitive,
  reviewed hit-by-hit — "billable"/"billing" false positives expected) →
  no live Bill-domain references remain.
- PO receive flow and expense/reimbursement QBO pushes still green — they
  share `qbo_expense_account_id` / payment accounts with the deleted code.
