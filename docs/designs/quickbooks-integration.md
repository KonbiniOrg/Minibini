# QuickBooks Online Integration

QBO is Minibini's accounting system of record. Minibini pushes invoices, bills, and expense purchases into QBO; QBO calculates tax, owns the customer-facing payment experience, and is polled for payment status. Estimates are not pushed.

This doc owns the QBO push mechanics, OAuth lifecycle, sync log, and polling. Domain models on the Minibini side live with their owning docs:

- `Invoice`, `Expense`, `Reimbursement` — [invoicing-and-expenses.md](invoicing-and-expenses.md)
- `Bill`, `PurchaseOrder` — [materials-inventory-and-purchasing.md](materials-inventory-and-purchasing.md)
- `Estimate` (not pushed) — [estimates-and-prices.md](estimates-and-prices.md)

Developer setup (env file, redirect URI registration, dependencies, first-connect walkthrough) and the production cutover checklist (real QBO company instead of a sandbox) are in the Appendices at the end of this doc.

## Models

### `QBOConnection` — `apps/qbo/models.py`

Singleton per Minibini instance. Stores OAuth tokens and connection metadata.

| Field | Notes |
|---|---|
| `realm_id` | QBO company ID |
| `access_token` | Refreshed automatically by `QBOService.get_client` when expired |
| `refresh_token` | 100-day rolling lifetime |
| `access_token_expires_at` | One hour after issue |
| `refresh_token_expires_at` | 100 days after issue; reset on every refresh |
| `is_active` | Only one row may be active at a time; `qbo_callback` deactivates any existing rows in the same transaction. Inactive rows are kept (not deleted) so the historical record of which `realm_id` Minibini was connected to and when remains queryable — useful for diagnosing past pushes whose `qbo_id` belongs to a now-disconnected company. The dead tokens cost nothing. |
| `connected_at`, `last_sync_at` | Metadata |

Properties:

- `is_access_token_expired` — used by `get_client` to decide whether to refresh.
- `is_refresh_token_expiring_soon` — true if within 7 days of refresh-token expiry; surfaced to the settings UI as a warning.

`db_table = 'qbo_connection'`.

### `QBOSyncLog` — `apps/qbo/models.py`

Append-only audit trail. Every push attempt writes a row, success or failure.

| Field | Notes |
|---|---|
| `entity_type` | `'invoice'`, `'bill'`, `'expense'`, `'reimbursement'`, `'customer'`, `'vendor'`, `'contact_customer'` |
| `entity_id` | Minibini PK |
| `qbo_entity_type` | `'Invoice'`, `'Bill'`, `'Purchase'`, `'Customer'`, `'Vendor'` |
| `qbo_entity_id` | QBO ID on success; empty string on failure |
| `action` | `'create'`, `'update'`, `'delete'` |
| `status` | `'success'` or `'failed'` |
| `error_message` | Exception string on failure; blank otherwise |
| `triggered_by` | User FK (SET_NULL, nullable) — **who initiated this QBO call.** Auto-set by `log_sync` from the active request context (`current_request_user()`): the acting user for an API-triggered push/retry/void, `None` for a cron/poller sync. No threading — `log_sync` reads the same `HistoryContext` the `@history` decorator uses. Pass an explicit `triggered_by=` only to override. |
| `synced_at` | `auto_now_add` |

Default ordering is `-synced_at`. No retention policy — log grows forever.

`db_table = 'qbo_sync_log'`.

## OAuth lifecycle

| Step | Endpoint | Caller | Notes |
|---|---|---|---|
| Initiate | `GET /api/qbo/connect/` | Browser redirect from settings page | Generates state token, stores in session, redirects to Intuit |
| Callback | `GET /api/qbo/callback/` | Intuit redirects back here | Validates state token, exchanges code for tokens, deactivates any existing connection, creates new `QBOConnection`, redirects to `{SPA_BASE_URL}/#/settings` |
| Status | `GET /api/qbo/status/` | SPA on settings page mount | Returns connection state + `refresh_token_expiring_soon` |
| Disconnect | `POST /api/qbo/disconnect/` | SPA settings page | Sets `is_active=False` on the active connection |

`qbo_connect` and `qbo_callback` are plain Django views (not DRF) because they involve browser redirects, not XHR. Both require `core.can_manage_config`.

### Token refresh

`QBOService.get_client()` is the only sanctioned way to obtain a python-quickbooks client. It:

1. Looks up the active `QBOConnection`.
2. If `is_access_token_expired`, calls `AuthClient.refresh()`, then writes `access_token`, `refresh_token`, `access_token_expires_at` (now + 1h), and `refresh_token_expires_at` (now + 100 days) back to the connection.
3. Returns a `QuickBooks` client bound to that connection.

Because each refresh resets the 100-day refresh-token clock, any QBO API call within the 100-day window keeps the connection alive indefinitely. Idle longer than 100 days requires reconnecting via the OAuth flow.

## Configuration

Environment variables — see `minibini/settings.py`:

| Variable | Purpose | Dev default |
|---|---|---|
| `QBO_CLIENT_ID` | Intuit app client ID | (empty) |
| `QBO_CLIENT_SECRET` | Intuit app secret | (empty) |
| `QBO_REDIRECT_URI` | Must match what's registered in the Intuit developer dashboard | `http://localhost:8000/api/qbo/callback/` |
| `QBO_ENVIRONMENT` | `sandbox` or `production` | `sandbox` |
| `SPA_BASE_URL` | Where `qbo_callback` redirects after OAuth | `http://localhost:9000` (dev); leave empty for same-origin prod |

Setup details (`.env` file format, redirect URI registration in Intuit dashboard, dependencies, first-connect walkthrough) are in the Appendix at the end of this doc.

### `Configuration['qbo_payment_accounts']`

JSON list of payment accounts (Bank, Credit Card, Other Current Asset) used by the expense sync. Populated from the settings UI via `/api/qbo/payment-accounts/`. Each entry:

```json
{ "qbo_account_id": "35", "display_name": "Business Checking", "account_type": "Bank" }
```

Read via `QBOExpenseSyncService._load_payment_accounts()`; individual lookup via `_lookup_account(payment_account_id)` (raises `ValueError` if not configured).

## The `QBOService` mock boundary

`QBOService` — `apps/qbo/services.py` — is a thin wrapper around the python-quickbooks SDK and is the only sanctioned mock point for tests. Production code obtains its QBO client via `QBOService.get_client()` and logs sync attempts via `QBOService.log_sync(...)`.

Test code mocks at this layer rather than at the python-quickbooks SDK level. Mocking deeper (`quickbooks.objects.invoice.Invoice.save`, etc.) is fragile against SDK upgrades; mocking shallower (the requests library) leaks unrelated HTTP traffic.

## Shared sync scaffolding

The per-entity sync services (`QBOCustomerSyncService`, `QBOVendorSyncService`, `QBOInvoiceSyncService`, `QBOBillSyncService`, `QBOExpenseSyncService`) are organized by QBO entity — each owns the *builder* for its QBO object, which genuinely differs (a `Customer`, an `Invoice`, a `BillPayment`, a `Purchase`…). What they used to duplicate has been factored into four shared pieces:

- **`QBOSyncable`** (`apps/core/models.py`) — abstract model base carrying the sync-state fields `qbo_id`, `qbo_sync_status` (`pending` / `synced` / `sync_failed`), `qbo_sync_error`, **`qbo_pending_op`** (`''` / `create` / `update` / `delete` — the operation a `sync_failed` record still owes QBO), plus `mark_synced(qbo_id)` (clears the op) / `mark_failed(error, op)` (records the op). Adopted by `Expense`, `Reimbursement`, and `BillPayment`. (`Expense.status` is business-only — `submitted`/`reimbursed`/`rejected`; its QBO sync state lives in the inherited `qbo_sync_status`. `Reimbursement`'s sole status *is* its `qbo_sync_status`.)
- **`QBOSyncService`** (`apps/qbo/services.py`) — the push orchestrators, one per verb: `run_create(record, push_callable)`, `run_update(record, update_callable)`, `run_delete(record, delete_callable)`. Each runs its callable and on failure calls `record.mark_failed(e, record.OP_<verb>)` — so a `sync_failed` row is **self-describing** about which operation to retry. `run_create`/`run_update` **swallow** (a QBO failure never blocks the local write that already committed); `run_delete` **re-raises** so a refused delete aborts the local removal and retains the row. (`run_update` was formerly named `run_resync` — "resync" now means *retry a failure*, not "an edit happened, push the update.")
- **`QBOService.save_and_log(qbo_obj, client, *, entity_type, qbo_entity_type, entity_id, action='create')`** — saves a QBO SDK object, writes the success/failure `QBOSyncLog` row, returns `str(qbo_obj.Id)`, re-raises on error. Every create/update push method calls it, so the save-and-log boilerplate lives in one place. (The `void_*` deletes and the invoice send — whose log lands after `_mark_as_sent` — keep their own shape.)
- **`QBOPaymentAccountService`** (`apps/qbo/services.py`) — owns the `Configuration['qbo_payment_accounts']` lookup (`load_accounts()` / `lookup(id)`), shared by the expense/reimbursement `Purchase` push and the bill-payment push.

A typical push method is now: short-circuit on existing id → get client (raise if none) → build the QBO object → `save_and_log(...)` → persist the id on the record; wrapped by `run_create`/`run_update` where the record is a `QBOSyncable`.

### Audit & attribution

Two separate audit trails, with a clean seam between them — and **attribution flows from the request context, never threaded**:

- **QBO-mechanics audit → `QBOSyncLog`** (the swap-the-backend seam): every push/update/void writes a row; `triggered_by` records who initiated it (auto from the request context; `None` for cron). QBO-coupled facts (qbo ids, sync status, error text) live only here.
- **Domain audit → the history partitions** (`docs/designs/architecture-and-conventions.md`): `Expense` is `@history`-decorated into a new **`ExpensesHistory`** partition (`object_type='expense'`/`'reimbursement'`), with `exclude=[…, qbo_id, qbo_sync_status, qbo_sync_error, qbo_pending_op]` so QBO sync churn never enters the domain timeline. The two **adjuncts** record their lifecycle imperatively on their **primary's** timeline via `record_action(object_type, object_id, action)`: `BillPayment` → the **Bill** (`'bill'`: recorded / edited / deleted), `Reimbursement` → each member **Expense** (`'expense'`: reimbursed-in-batch / unwound). `record_action` and `log_sync` both default their author to `current_request_user()`, so no service threads an actor.

### Retry & sync failures

Each domain service exposes the same small sync-dispatch surface so a failure can be retried as the *operation it actually owes*:

- `_push_create(record)` / `_push_update(record)` — the create and update push wrappers (the update one carries any domain routing, e.g. a personal `Expense`'s edit resyncs its reimbursement **batch**, not the expense).
- `retry(record, …)` — guards `qbo_sync_status == sync_failed`, then **dispatches on `qbo_pending_op`**: `delete` → re-run the full delete (re-void + local removal); `update` → `_push_update`; `create`/blank → `_push_create`. This fixes the old bug where a blind retry always create-pushed — which **short-circuited on `qbo_id` and silently marked a failed *update* as synced without re-applying the edit**, and abandoned a failed *delete*.
- `ExpenseService.retry`, `ReimbursementService.retry`, `BillPaymentService.retry` (each backed by a per-entity `POST …/retry-sync/` endpoint). Bill payments' retry endpoint is `POST /api/bills/{id}/payments/{pid}/retry-sync/`.

**Cross-entity failures view.** `QBOSyncFailureService.list_failures()` aggregates every `sync_failed` company `Expense` (personal expenses never carry their own failure — their batch does), `Reimbursement`, and `BillPayment` into one list (`entity_type`, `id`, `label`, `amount`, `qbo_pending_op`, `qbo_sync_error`, `retry_url`). Exposed at:

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/qbo/sync-failures/` | `can_manage_financials` | List all QBO sync failures across the three money pushes |
| `POST` | `/api/qbo/sync-failures/retry-all/` | `can_manage_financials` | Retry each (isolated per-record); returns `{retried, still_failing}` |

The SPA surfaces this as `QBOSyncFailures.svelte` (per-row Retry + Retry all) on the Settings page; the failures view covers **only** the three `QBOSyncable` money pushes (Customers/Vendors/Invoices use ad-hoc sync state and are out of scope).

## Customer sync — `QBOCustomerSyncService`

Customers are pushed lazily. `QBOInvoiceSyncService.push_invoice` resolves the QBO customer ID from `invoice.job.contact.business` (preferred) or `invoice.job.contact` (individual customer), and pushes the missing record if needed.

Two push entry points:

- `push_customer(business)` — pushes a `Business`, stores `qbo_customer_id` on it.
- `push_contact_as_customer(contact)` — pushes an individual `Contact` with no business, stores `qbo_customer_id` on the contact.

Both are no-ops if the target already has a `qbo_customer_id`.

### DisplayName collision logic — `QBODisplayNameService`

QBO requires unique `DisplayName` per entity type. The same Minibini `Business` may be both a customer (the company issues them invoices) and a vendor (the company also buys from them). Rules:

- First push for a business uses the plain `business_name`.
- If the business already has the *other* role's QBO ID (e.g. pushing as customer and `qbo_vendor_id` is set), the display name gets a ` (Customer)` or ` (Vendor)` suffix.
- `QBO_DISPLAY_NAME_MAX = 500`; long names are truncated before the suffix is appended.

The current logic only inspects Minibini's own QBO IDs. It does not handle the case where the user's QBO file already contains a customer named "Acme Inc." that was created outside Minibini. That collision surfaces as an SDK error and the sync log records a failure.

### What gets pushed

| Field | Source |
|---|---|
| `CompanyName` (business) | `business.business_name` |
| `DisplayName` | per the rules above |
| `GivenName` / `FamilyName` (contact) | `contact.first_name`, `contact.last_name` |
| `PrimaryPhone` | `business.business_phone` or `contact.phone()` |
| `PrimaryEmailAddr` | `default_contact.email` (business) or `contact.email` |

Billing address, shipping address, payment terms, tax exemption, and notes are not pushed.

## Vendor sync — `QBOVendorSyncService`

Parallel to customer sync. `push_vendor(business)` is called lazily by `QBOBillSyncService.push_bill` and (transitively) by anything else that needs a vendor ID. Same DisplayName collision logic. Stores `qbo_vendor_id` on the `Business`.

## Invoice push — `InvoiceEmailService.send_invoice`

The invoice QBO push is **fused into the invoice's Send action** — there is no separate `send-to-qbo` endpoint for invoices (bills have one; invoices do not). Entry point: `POST /api/invoices/{id}/send` (the `send` action on `InvoiceViewSet`, `apps/api/invoicing/views.py`). Requires `can_manage_financials`. Body:

```json
{ "to": "customer@example.com", "subject": "...", "body": "...", "cc": "...", "bcc": "..." }
```

The action delegates to `InvoiceEmailService.send_invoice` (`apps/invoicing/services.py`), which performs the QBO push (only when `invoice.qbo_id` is unset) and then emails the customer — push and send are one operation, not two buttons. It uses the `QBOInvoiceSyncService` *helpers* (`_build_qbo_invoice`, `_mark_as_sent`, `_download_qbo_pdf`); there is no `QBOInvoiceSyncService.push_invoice` method.

Service flow (`InvoiceEmailService.send_invoice`, `apps/invoicing/services.py`):

1. **Gate** — `_assert_all_lines_categorized` raises before any external call if any line lacks an accounting category.
2. **Short-circuit** — if `invoice.qbo_id` is set, skip the push (retry path).
3. **Resolve QBO customer** — push `business` (or `contact`) as customer if not yet synced.
4. **Build QBO Invoice, per-line** — `_build_qbo_invoice(invoice, qbo_customer_id, client)`. One `SalesItemLine` per `InvoiceLineItem`, in `line_number` order — the QBO invoice mirrors the konbini invoice exactly (no more per-category bundling; `InvoiceGroupingService` was deleted 2026-07-21). Per line: `Amount` = `total_amount`, `Description` = the line's text **verbatim** (wizard edits ride along), `ItemRef` from `_resolve_item_ref` (below), `TaxCodeRef` = `'TAX'`/`'NON'` straight from the line's `accounting_category.taxable` flag (the per-line `taxable_override` phantom was removed along with `TaxCalculationService`). Invoice-level: `CustomerMemo` = `"Job {job_number} — {job name}"`, `BillEmail` from the job contact's email, and `AllowOnlineCreditCardPayment` / `AllowOnlineACHPayment` both true (the hosted invoice carries the Pay button when QBO Payments is active).
5. **Save** — `qbo_invoice.save(qb=client)`. **Immediately persist `qbo_id` AND `invoice_number` (from QBO's `DocNumber`)** on the Minibini invoice — QBO owns invoice numbering (see invoicing-and-expenses.md). A retry send whose invoice predates the writeback backfills `DocNumber` via `Invoice.get`.
6. **Fetch the payment link** — `_fetch_invoice_link(client, qbo_id)` reads the invoice back with `include=invoiceLink` (built directly on the client — the installed python-quickbooks `get()` can't pass query params) and substitutes the URL into the email subject/body wherever the `{payment_link}` placeholder appears.
7. **Generate the Minibini job-statement PDF** — `generate_job_statement_pdf(invoice)` (in `apps/invoicing/pdf.py`). The PDF is attached to the customer email only; it is **not** uploaded to QBO.
8. **Mark as sent** — `_mark_as_sent` re-fetches the invoice, sets `EmailStatus = 'EmailSent'`, and re-saves. This prevents QBO from showing the invoice as "needs to be sent" in its own UI, and suppresses QBO's own email.
9. **Download QBO PDF** — `_download_qbo_pdf` retrieves QBO's rendered invoice PDF.
10. **Send email via Minibini** — `OutboundEmailService.send_tracked` with both PDFs attached, Configuration-driven subject/body templates, To/CC/BCC from the send dialog, and a job-linked `EmailRecord`.
11. **Log success** to `QBOSyncLog`.

On any exception, `QBOSyncLog` records `status='failed'` with the error message, and the exception re-raises. There is no compensating action — if step 8 succeeds but step 9 fails, the invoice exists in QBO with `qbo_id` set on Minibini but is in an inconsistent "marked sent, not emailed" state. Manual cleanup is required.

### ItemRef resolution — `QBOInvoiceSyncService._resolve_item_ref`

Each pushed line's `ItemRef` resolves in order:

1. **The line's catalog entity's mirrored QBO Item** — `_catalog_entity_for_line` finds the single `InventoryItem` or `ServiceItem` the line sells: the line's direct `inventory_item` FK, else its source atoms (all task sources sharing one `Task.service_item`, or all material sources sharing one `Material.inventory_item`). Adjustment lines, expense/fee sources, provisional materials, mixed bundles, and hand lines have no catalog identity → fall through.
2. **The category's generic fallback Item** — `AccountingCategory.qbo_item_id` (the pre-existing per-category mapping, now demoted to fallback).
3. **No ItemRef** — QBO applies its default item.

### Lazy Item minting — `QBOItemMintService.ensure_item(entity, client)`

When step 1 finds a catalog entity with no `qbo_id`, the QBO Item is created mid-push: `InventoryItem` → Type `NonInventory` (never QBO's `Inventory` type — stock stays konbini-side), Name = `code`; `ServiceItem` → Type `Service`, Name = `template_name`. `IncomeAccountRef` is **copied from the category's generic fallback Item** fetched live from QBO — the bookkeeper configures income accounts exactly once, in QBO, on the per-category Items; konbini never stores income accounts. On QBO's duplicate-name error (`6240`), the existing Item is adopted by name (also how pre-existing QBO catalogs converge). If the entity's category has no `qbo_item_id` mapped, nothing is minted and the resolution falls through. The minted/adopted id persists on `entity.qbo_id` (plain CharField — not `QBOSyncable`; a failed mint fails the invoice push, whose retry path covers it). Catalog renames do NOT propagate to QBO Items (LATER).

## Bill push — `QBOBillSyncService.push_bill`

Entry point: `POST /api/bills/{id}/send-to-qbo/` (defined in `apps/api/purchasing/views.py`). Requires `can_manage_financials`.

Flow:

1. Short-circuit on `bill.qbo_id`.
2. Require `bill.business` (vendor). Raise `ValueError` if missing.
3. Lazy-push vendor via `QBOVendorSyncService.push_vendor` if `qbo_vendor_id` is not set.
4. Build a QBO `Bill` with `VendorRef`, optional `DocNumber` from `bill.vendor_invoice_number`, and one `AccountBasedExpenseLine` per `BillLineItem`. Each line's `AccountRef` comes from `AccountingCategory.qbo_expense_account_id`. Lines without a category, or with a category that has no expense account mapped, will fail at the QBO end.
5. Save, store `qbo_id`, log.

Bills do not push attachments, do not mark-as-sent, and do not send emails. The push is one-way and silent.

### Bill payment push — `QBOBillSyncService.push_bill_payment` / `update_bill_payment` / `void_bill_payment`

The bill-payment push lives **inside the Minibini payment process**, not as a separate user action. `BillPaymentService.record_payment` calls `push_bill_payment(payment)` immediately after recording a `BillPayment`; `update_payment` resyncs on edit; `delete_payment` voids on delete. All three are best-effort — failures are swallowed-and-logged (`record_payment`/`update_payment` go through `QBOSyncService.run_create`/`run_resync`; `void_bill_payment` swallows internally) so a QBO hiccup never blocks the local write.

`push_bill_payment` (live):

1. **Idempotent** — short-circuit if `payment.qbo_id` is already set.
2. **Connection / account required** — `QBOService.get_client()`; raise `ValueError('No active QBO connection')` if none, and `ValueError` if `payment.payment_account_id` is blank. Both land the payment in `qbo_sync_status='sync_failed'` with the message (the recovery path is editing the payment, which re-pushes). The API requires `payment_account_id` while QBO is connected (400 otherwise).
3. **Ensure the parent Bill exists** — `push_bill(bill)` if `bill.qbo_id` unset (which in turn lazy-pushes the vendor).
4. **Build the QBO `BillPayment`** — `VendorRef` from `bill.business.qbo_vendor_id`; `TotalAmt`; one `Line` with a `LinkedTxn` (`TxnId = bill.qbo_id`, `TxnType = 'Bill'`) — that link is what pays the bill down; `DocNumber` from `reference`. **PayType is driven by the selected payment account's `account_type`** (resolved via `QBOPaymentAccountService.lookup(payment.payment_account_id)`): `Credit Card` → `PayType='CreditCard'` + `CreditCardPayment.CCAccountRef`; anything else (`Bank`, `Other Current Asset`, incl. a Petty-Cash account used for a cash payment) → `PayType='Check'` + `CheckPayment.BankAccountRef`.
5. **Save + log + write back** — via `QBOService.save_and_log`; `run_create` then writes `qbo_id` and `qbo_sync_status='synced'` onto the payment.

`update_bill_payment` re-fetches the QBO `BillPayment`, rebuilds `TotalAmt`/`DocNumber`/line amount, saves. `void_bill_payment` deletes the QBO `BillPayment` (logs but never raises — the caller is mid-delete). On edit, `update_payment` resyncs when `payment.qbo_id` is set, else pushes fresh (covers a payment first recorded while disconnected).

The `BillPayment` model carries the result via the shared `QBOSyncable` fields (`qbo_id` written by the push, `qbo_sync_status`, `qbo_sync_error`); `cleared_date` remains the deferred clearance-poller's field. There is no `method` field — the human descriptor is derived from the payment account + reference.

## Expense push — `QBOExpenseSyncService`

The Minibini-side workflow (entering expenses, batching reimbursements, voiding) is described in `invoicing-and-expenses.md`. This section covers the QBO mechanics.

### Push targets

| Minibini entity | QBO entity | Trigger |
|---|---|---|
| `Expense` (company-paid) | `Purchase` | `push_expense(expense)` on save |
| `Reimbursement` batch (personal expenses) | `Purchase` with one line per included `Expense` | `push_reimbursement(batch)` when batch is finalized |

Both produce QBO `Purchase` records — the difference is whether the line items come from a single expense or a batch.

### Payment account resolution

Every `Purchase` needs an `AccountRef` (which Minibini bank/CC/cash account it was paid from). The mapping comes from `Configuration['qbo_payment_accounts']`. The user picks `payment_account_id` on the expense or batch; `_lookup_account` resolves that ID to the QBO account dict, and `_derive_payment_type` decides the QBO `PaymentType`:

| Minibini `account_type` | `reference_number` set? | QBO `PaymentType` |
|---|---|---|
| `Credit Card` | (any) | `CreditCard` |
| `Bank` | yes | `Check` |
| `Bank` | no | (unset — defaults to Cash in QBO) |
| `Other Current Asset` | (any) | (unset) |

`reference_number` also becomes the QBO `DocNumber` when set.

### Line items

`_build_expense_line(expense)` is shared between single-expense pushes and reimbursement-batch pushes. It produces one `AccountBasedExpenseLine` with:

- `Amount = float(expense.amount)`
- `Description = expense.description or f"Expense #{expense.pk}"`
- `AccountRef = expense.accounting_category.qbo_expense_account_id` (if both are set)

Personal reimbursement batches do **not** set `EntityRef` on the Purchase. That would point to a QBO Employee record, and Employee-as-Vendor sync is not yet implemented (see Unfinished work, and the matching pointer in `invoicing-and-expenses.md`).

### Update and void

| Method | Behavior |
|---|---|
| `push_expense` / `push_reimbursement` | Create-only; short-circuits if `qbo_id` already set |
| `update_expense` / `update_reimbursement` | Re-fetch the QBO `Purchase`, rebuild fields, save. Raises if `qbo_id` not set |
| `void_expense` / `void_reimbursement` | Delete the QBO `Purchase`. **Logs but does not raise** on failure — the caller is mid-delete and the local row must still be removed |

## Inventory write-offs are not pushed (by design)

`InventoryService.write_off` zeroes a lot's on-hand and books the remainder to `qty_wasted`, recording an `InventoryHistory` entry — it pushes **nothing** to QBO, deliberately. Inventory cost is *expensed at purchase time*: Bills push as a QBO `Bill` and company-paid Expenses as a QBO `Purchase`, both with `AccountBasedExpenseLine`s posting to an **expense / COGS account** (`AccountingCategory.qbo_expense_account_id`), never to a capitalized inventory asset. So the cost already hit QBO's P&L when the bill/expense was recorded; a write-off is a pure quantity event in Minibini with no QBO consequence, and pushing one would **double-count** the cost. This only changes if QBO is ever switched to true inventory-asset tracking (Items with quantities, COGS on sale) — then write-offs would need to relieve the asset; that is a much larger change and is not planned.

## Accounting categories — `QBOAccountsService`

Two endpoints feed the settings UI mapping page:

| Method | Pulls | Used for |
|---|---|---|
| `get_income_items()` | QBO `Item` records with `Type` in `('Service', 'NonInventory')`, `Active=True` | Mapping `AccountingCategory.qbo_item_id` — invoice lines reference QBO Items, not accounts |
| `get_expense_accounts()` | QBO `Account` records with `AccountType` in `('Expense', 'Cost of Goods Sold')`, `Active=True` (dedupe by ID) | Mapping `AccountingCategory.qbo_expense_account_id` — bill and purchase lines reference accounts directly |

Both fields live on `apps.core.models.AccountingCategory`. Both are `CharField(max_length=50, blank=True, default='')`. A category used only for invoicing needs only `qbo_item_id`; one used only for bills/expenses needs only `qbo_expense_account_id`; categories that flow both directions need both.

Both methods are live fetches against QBO — there is no caching layer and no "refresh accounts" endpoint, just `GET /api/qbo/accounts/`.

## Payment polling

Polling is the *only* mechanism for learning about payments — there are no webhooks.

### Invoice polling — `QBOPaymentPollingService.poll_all()`

Walks every `Invoice` where `qbo_id` is set and the Minibini status is still `open` or `partly-paid`. For each, fetches the QBO invoice and derives, from QBO's `Balance` / `TotalAmt`, both a **raw cache** value and a target Minibini status:

| Condition | `qbo_payment_status` (cache) | `Invoice.status` |
|---|---|---|
| `Balance == 0` | `'Paid'` | → `paid` |
| `0 < amount_paid` | `'Partial'` | → `partly-paid` |
| `amount_paid == 0` | `'Unpaid'` | (unchanged) |

`qbo_payment_status` and `qbo_amount_paid` (`= TotalAmt - Balance`) remain the raw cache of what QBO last reported. The service now also **drives `Invoice.status`**: on a status change it does a full `invoice.save()` (which stamps `closed_date` and, on `paid`, fires `_maybe_complete_job` to auto-complete the job once all its invoices are resolved) and writes a `system`-attributed `action` HistoryEntry. If there is no active QBO connection, `poll_all` returns an `error` key and the command records a `skipped` run rather than failing.

**First-run healing:** an invoice left at `open` with a stale cached `qbo_payment_status='Paid'` (from the old cache-only polling) will transition to `paid` — and complete its job — on the first run under the status-driving code. See `invoicing-and-expenses.md` for the full status-machine view.

### Bill clearance polling — `QBOBillPaymentPollingService.poll_all()` (stubbed)

Walks every `BillPayment` where `cleared_date` is null and `qbo_id` is non-empty (i.e. payments pushed to QBO but not yet confirmed as cleared). When the live QBO fetch lands (**all polling is deferred to a later session**), this service will write `cleared_date` per `BillPayment`. **Today the inner loop body is a stub** — no QBO fetch or `cleared_date` write occurs. Note the bill-payment *push* is now live and writes `qbo_id`, so rows can match this filter; the stub simply doesn't act on them yet.

### Unified inbound orchestrator — `QBOInboundPollingService`

`QBOInboundPollingService.poll_all()` is the single entry point for all QBO → Minibini polling:

```python
{
    'invoices': QBOPaymentPollingService.poll_all(),
    'bills': QBOBillPaymentPollingService.poll_all(),
}
```

Both sub-pollers run in the same call; the invoice branch is live, the bill branch is stubbed.

### Management command

`python manage.py poll_qbo_payments` (`apps/invoicing/management/commands/poll_qbo_payments.py`) drives `QBOInboundPollingService.poll_all()` — **both invoice and bill polling** (bill branch currently stubbed). It is a `ScheduledProcessCommand` (`architecture-and-conventions.md` §9), so each run records a `ScheduledProcessRun` row (`ok` / `failed` / `skipped`). The scheduler **is** wired: the docker-compose `cron` service runs it every 15 minutes.

**Operational note — credentials and timezone.** The cron service runs in its own container; the committed `docker-compose.yml` mirrors only the `DATABASE_*` env onto it. QBO OAuth credentials and the email/IMAP credentials are injected at deploy time and **must reach the cron container too** — otherwise `poll_qbo_payments` records `skipped` runs (no QBO connection) and the email-related jobs `failed` runs. The cron schedules are evaluated in the **container timezone (UTC by default)**; set `TZ` on the cron service to schedule in local time.

## UI

Settings page — `frontend/src/routes/SettingsPage.svelte`:

- `QBOConnectionCard.svelte` — calls `/api/qbo/status/`, shows realm ID, connected date, last sync, refresh-token-expiring-soon warning. "Connect to QuickBooks" / "Reconnect" link to `/api/qbo/connect/`. "Disconnect" button.
- Category mapping panel (lives elsewhere on the settings page) — uses `/api/qbo/accounts/` to populate `qbo_item_id` and `qbo_expense_account_id` dropdowns for each `AccountingCategory`.
- Payment-account selection — uses `/api/qbo/payment-accounts/` to populate the `Configuration['qbo_payment_accounts']` list.

Invoice detail — `frontend/src/routes/invoices/InvoiceDetailPage.svelte`:

- A "Send Invoice" link (relabelled "Resend Invoice" once `invoice.qbo_id` is set) navigates to the invoice send page (`#/invoices/{id}/send`). That page posts to `POST /api/invoices/{id}/send`, which performs the QBO push (first send only) and the customer email together. There is no separate "Send to QuickBooks" button or `SendToQBODialog`. Once `qbo_id` is set, the detail page also shows read-only QBO ID / payment-status / amount-paid rows.

The send flow on the Minibini side is documented in `invoicing-and-expenses.md`.

## API endpoints

All endpoints are mounted under `/api/qbo/` via `apps/qbo/urls.py`.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/qbo/connect/` | `can_manage_config` | Browser redirect to Intuit OAuth |
| `GET` | `/api/qbo/callback/` | `can_manage_config` | OAuth callback; redirects to SPA settings page |
| `GET` | `/api/qbo/status/` | `can_manage_config` | Connection state for settings card |
| `POST` | `/api/qbo/disconnect/` | `can_manage_config` | Deactivate active connection |
| `GET` | `/api/qbo/accounts/` | `can_manage_config` | Live fetch of QBO Items + expense accounts for category mapping |
| `GET` | `/api/qbo/payment-accounts/` | `can_manage_config` | Live fetch of Bank / Credit Card / Other Current Asset accounts for payment-account config |

Push endpoints live on the owning resource's viewset:

| Method | Path | Permission | Service |
|---|---|---|---|
| `POST` | `/api/invoices/{id}/send` | `can_manage_financials` | `InvoiceEmailService.send_invoice` — QBO push fused into the send-email action; **no** separate invoice send-to-qbo endpoint |
| `POST` | `/api/bills/{id}/send-to-qbo/` | `can_manage_financials` | `QBOBillSyncService.push_bill` |

Expense and reimbursement pushes are triggered server-side from their respective save / finalize flows in `apps/expenses` and `apps/reimbursements` — not via dedicated REST actions.

There is no `GET /api/qbo/sync-log/` endpoint yet; `QBOSyncLog` is currently inspected via the Django admin.

## Unfinished work

- **Bill clearance polling.** `QBOBillPaymentPollingService` is folded into `QBOInboundPollingService` and called by `poll_qbo_payments`, but the inner loop body (QBO fetch + `cleared_date` write) is stubbed. **All QBO → Minibini polling is deferred to a dedicated later session** — the bill-payment *push* is live (writes `qbo_id`) but its inbound clearance confirmation is not yet built.
- **Sync log UI.** No `/api/qbo/sync-log/` endpoint or settings panel showing recent push attempts; failures are visible only via the Django admin.
- **Employee-as-Vendor sync for personal reimbursements** — tracked in `invoicing-and-expenses.md`.
- **Job P&L view.** Phase 5 of the original plan — pull QBO-reported actuals back into Minibini for a per-job profit & loss view. Tracked in `invoicing-and-expenses.md`.
- **Estimate push.** Not currently supported. Minibini-direct estimate send is also unimplemented; see `estimates-and-prices.md`.
- **Webhooks.** Polling was chosen for simplicity. QBO does support a webhook channel for invoice payment notifications; revisit if polling latency or load becomes a problem.
- **Chart-of-accounts drift detection.** If a mapped QBO Item or expense Account is renamed or deleted in QBO, Minibini won't notice until the next push fails. No proactive drift check.
- **Richer customer field push.** Only display name, phone, and email currently push. Billing/shipping address, payment terms, tax exemption, notes do not.
- **Cross-source DisplayName collisions.** `QBODisplayNameService` only checks Minibini's own QBO IDs. A name collision with a customer/vendor created outside Minibini surfaces as a save failure from QBO, not a graceful suffix.
- **Custom invoice email templates.** Subject and body for the invoice send-email step are hard-coded strings; there's no per-user or per-customer template system.
- **Partial-failure handling.** If any step after `qbo_id` is persisted fails, Minibini has a `qbo_id` but the QBO record may be in an inconsistent state (e.g. marked-sent but no email actually sent). There is no resume / retry tool; recovery is manual.
- **"Resend to QBO" action.** Once `qbo_id` is set, the send-to-qbo path short-circuits. If the original push partially failed, there's no UI for retrying just the failed steps.
- **"View in QBO" deep link.** No button in the invoice detail UI to jump to the QBO invoice URL.
- **Connection health beyond `is_refresh_token_expiring_soon`.** No proactive token refresh well before the 100-day window closes, no email alert, no dashboard pulse.
- **CDC reverse-sync for QBO-first Purchases.** Research notes preserved as an appendix in `invoicing-and-expenses.md`.

---

## Appendix: Production cutover

What changes when a deployment points at a real QBO company instead of a sandbox. **No code changes are required** — `QBO_ENVIRONMENT` flows all the way through: `intuitlib`'s `AuthClient` picks its OAuth endpoints from it, and python-quickbooks infers its API base URL from the auth client's environment (sandbox vs production). Everything below is portal work, deployment config, and in-app reconfiguration.

### 1. Intuit developer portal (one-time)

- An Intuit app has two separate credential sets: **Development keys** (sandbox-only, what dev uses today) and **Production keys**, which don't exist until the app completes Intuit's "go to production" checklist — app details, EULA and privacy-policy URLs, and a short questionnaire for the Accounting scope. Straightforward for a private internal app, but it is a gate; do it ahead of the deployment date.
- Register the production redirect URI (`https://<prod-host>/api/qbo/callback/`) under the **production** keys tab. Intuit **requires HTTPS** for production redirect URIs; plain http is only tolerated for localhost dev.

### 2. Deployment environment values

The production instance's env:

| Variable | Production value |
|---|---|
| `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | The **production** keyset — different values from the dev keys |
| `QBO_REDIRECT_URI` | `https://<prod-host>/api/qbo/callback/` (must exactly match the portal registration) |
| `QBO_ENVIRONMENT` | `production` |
| `SPA_BASE_URL` | empty (same-origin) |

The keyset and environment must pair correctly: production keys only work with `QBO_ENVIRONMENT=production`, dev keys only with `sandbox`.

Per the operational note in [Management command](#management-command): these vars must reach the **cron container** too, not just the web container — otherwise `poll_qbo_payments` silently records `skipped` runs.

Staging/test instances need none of this — they keep the dev keyset with `QBO_ENVIRONMENT=sandbox`. One Intuit app serves every environment: the sandbox *company* is chosen during the OAuth connect (stored as `realm_id` on `QBOConnection`), not by the credentials, and one app can register multiple redirect URIs. Separate sandbox companies per instance therefore need no per-instance credential changes.

### 3. In-app reconfiguration after connecting

Every QBO ID stored in Minibini is scoped to one specific QBO company. After connecting the production instance to the real company (settings page → Connect to QuickBooks), redo in the production instance's settings UI:

- **Category mappings** — `AccountingCategory.qbo_item_id` and `qbo_expense_account_id`. The real company's items and chart of accounts have completely different IDs than any sandbox.
- **Payment accounts** — the `Configuration['qbo_payment_accounts']` list.

**Start production from a fresh database.** A database that has already pushed to a sandbox must never be pointed at production: every stored `qbo_id`, `qbo_customer_id`, and `qbo_vendor_id` would be a stale sandbox ID, and the push short-circuits ("already has `qbo_id` → skip") would silently skip pushes that never happened in the real company.

### Repointing a dataset at a different company — `purge_qbo_data`

For the non-production version of the same problem — prepping a sample dataset for a staging instance that connects to a *different sandbox company* — `python manage.py purge_qbo_data <input.json> <output.json>` reads a `dumpdata` JSON dump and writes a copy with every QBO-company-scoped value stripped. It operates on the file only — **it never touches a database** (output path may equal input for in-place):

- `core.accountingcategory`: `qbo_item_id` / `qbo_expense_account_id` → `''`
- `core.configuration` rows with key `qbo_payment_accounts` → dropped (other keys untouched)
- `invoicing.invoice`: `qbo_id` → null, plus its poll caches `qbo_payment_status` → `''` and `qbo_amount_paid` → null; `purchasing.bill`: `qbo_id` → null and `qbo_payment_status` → `''`
- `contacts.business` `qbo_customer_id` / `qbo_vendor_id` and `contacts.contact` `qbo_customer_id` → null
- The `QBOSyncable` trio (`expenses.expense`, `expenses.reimbursement`, `purchasing.billpayment`): `qbo_id` → `''`, `qbo_sync_status` → `pending`, `qbo_sync_error` / `qbo_pending_op` cleared
- All `qbo.qboconnection` and `qbo.qbosynclog` records → dropped

It prints per-model scrubbed/dropped counts. Only fields actually present in a record are overwritten, so a dump from an older schema stays loadable. The flip side: models with no data in the dump (e.g. QBO features unfinished at dump time) exercise nothing — **when new QBO-coupled models or fields land, extend the command's tables and recheck against a fresh dump.** **What it does not touch:** domain state derived from the old company stays as-is — invoices remain `paid`/`partly-paid` with no QBO record behind them (accepted follow-on effect), and `payment_account_id` values on expenses/reimbursements/payments are kept even though they now dangle (the which-account information stays readable). After loading the purged dump, the new instance must connect to its new sandbox account and regenerate the category mappings and payment-account list per §3 above.  The existing domain state will remain inconsistent with the new sandbox, acceptable in a staging environment.

## Appendix: Developer setup

QBO integration requires OAuth credentials and a `.env` file. One-time setup per developer.

### Connect to QBO

1. **Get credentials.** Ask the project owner for the Intuit developer account, or create your own at https://developer.intuit.com/. You need a sandbox app with a client ID and client secret.

2. **Create `.env`** in the project root (gitignored):

   ```
   QBO_CLIENT_ID=your_client_id_here
   QBO_CLIENT_SECRET=your_client_secret_here
   QBO_REDIRECT_URI=http://localhost:8000/api/qbo/callback/
   QBO_ENVIRONMENT=sandbox
   SPA_BASE_URL=http://localhost:9000
   ```

   Variable meanings are documented in the Configuration section above.

3. **Register the redirect URI** — in the Intuit developer dashboard, open your app's **Keys & credentials** and add `http://localhost:8000/api/qbo/callback/` as a Redirect URI. Must match exactly.

4. **Install dependencies** — `pip install -r requirements.txt` (adds `python-quickbooks` and `python-dotenv`).

5. **Run migrations** — `python manage.py migrate` (creates `qbo_connection` and `qbo_sync_log` tables, and adds QBO fields to `businesses` and `accounting_categories`).

6. **Connect** — start both servers with `./dev.sh`, go to `http://localhost:9000/#/settings`, click "Connect to QuickBooks". Log in with the Intuit sandbox credentials and authorize.

The user connecting must have `can_manage_config`.

### Accessing the sandbox company

The sandbox company login is not directly linked from the main developer-portal app page. To reach it:

1. In the developer portal (developer.intuit.com), open your app and click the **API Explorer** tab.
2. Near the top of the API Explorer there's a pulldown menu (showing a company identifier). Open it.
3. At the bottom of that pulldown, click **Manage Sandbox**.
4. That takes you to `developer.intuit.com/sandbox-companies`, which lists all your sandbox companies.
5. Click the company you want. The portal runs through several automatic redirects and logs you into that company's QBO environment.

The direct URL `qbo.sandbox.intuit.com` does not work reliably — use the Manage Sandbox route.
